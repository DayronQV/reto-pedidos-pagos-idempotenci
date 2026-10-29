"""Order API: crea pedidos, reserva inventario, inicia el pago y expone el estado.

Ejecutar:  python order_api/app.py   (puerto 5000 por defecto)
"""
import hashlib
import json
import os
import sqlite3

import requests
from flask import Flask, jsonify, request

import db
import payment_client

PORT = int(os.getenv("ORDER_API_PORT", "5000"))
SIMULACIONES_VALIDAS = ("aprobado", "rechazado", "timeout")

app = Flask(__name__)
app.json.ensure_ascii = False  # respuestas JSON con tildes legibles


db.init_db()


def _pedido_a_dict(fila, reserva, idempotente=False):
    """Arma el pedido con el formato del contrato (sección POST /orders).

    idempotente=True se usa cuando la respuesta es la repetición de una solicitud.
    """
    return {
        "id": fila["id"],
        "idempotency_key": fila["idempotency_key"],
        "producto_id": fila["producto_id"],
        "cantidad": fila["cantidad"],
        "monto": fila["monto"],
        "payment_key": fila["payment_key"],
        "estado": fila["estado"],
        "reserva": (
            {"estado": reserva["estado"], "cantidad": reserva["cantidad"]}
            if reserva
            else None
        ),
        "idempotente": idempotente,
    }


@app.errorhandler(404)
def no_encontrado(_e):
    # Rutas inexistentes (p. ej. GET /orders/abc) también responden JSON, como el contrato.
    return jsonify(error="recurso no encontrado"), 404


@app.get("/health")
def health():
    return jsonify(status="ok", servicio="order-api")


@app.get("/products")
def listar_productos():
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT id, nombre, precio, stock FROM productos ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return jsonify([dict(f) for f in filas])


@app.get("/orders")
def listar_pedidos():
    conn = db.get_connection()
    try:
        pedidos = conn.execute("SELECT * FROM pedidos ORDER BY id").fetchall()
        reservas = {
            r["pedido_id"]: r for r in conn.execute("SELECT * FROM reservas").fetchall()
        }
    finally:
        conn.close()
    return jsonify([_pedido_a_dict(p, reservas.get(p["id"])) for p in pedidos])


@app.get("/orders/<int:pedido_id>")
def obtener_pedido(pedido_id):
    conn = db.get_connection()
    try:
        pedido = conn.execute(
            "SELECT * FROM pedidos WHERE id = ?", (pedido_id,)
        ).fetchone()
        if pedido is None:
            return jsonify(error="pedido no encontrado"), 404
        reserva = conn.execute(
            "SELECT * FROM reservas WHERE pedido_id = ?", (pedido_id,)
        ).fetchone()
    finally:
        conn.close()
    return jsonify(_pedido_a_dict(pedido, reserva))


def _error(mensaje, codigo):
    return jsonify(error=mensaje), codigo


def _es_entero(valor):
    return isinstance(valor, int) and not isinstance(valor, bool)


def _calcular_hash(producto_id, cantidad, simular_pago):
    """Huella del cuerpo de la solicitud: detecta la misma Idempotency-Key con otro cuerpo."""
    cuerpo = {"producto_id": producto_id, "cantidad": cantidad, "simular_pago": simular_pago}
    return hashlib.sha256(json.dumps(cuerpo, sort_keys=True).encode()).hexdigest()


def _cargar_pedido(conn, pedido_id):
    pedido = conn.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
    reserva = conn.execute(
        "SELECT * FROM reservas WHERE pedido_id = ?", (pedido_id,)
    ).fetchone()
    return pedido, reserva


def _buscar_por_clave(conn, idempotency_key):
    """Devuelve el pedido guardado con esa Idempotency-Key, o None si no existe."""
    return conn.execute(
        "SELECT * FROM pedidos WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()


def conciliar_pago_incierto(conn, pedido_id):
    """Punto de enganche con la conciliación de pagos inciertos (issue #7).

    Se llama al repetir una solicitud cuyo pedido está en PAGO_INCIERTO: en vez de devolverlo
    tal cual, #7 consulta GET /payments/<payment_key> en el mock y deja el pedido en su
    estado final. Mientras #7 no esté listo no hace nada y el pedido se devuelve como está.
    """


def responder_repeticion(conn, existente, request_hash):
    """Responde a una Idempotency-Key ya usada, sin tocar stock, reserva ni mock.

    Mismo cuerpo -> 200 con el pedido guardado e "idempotente": true.
    Otro cuerpo  -> 409.
    """
    if existente["request_hash"] != request_hash:
        return _error("la Idempotency-Key ya se usó con otra solicitud", 409)
    if existente["estado"] == "PAGO_INCIERTO":
        conciliar_pago_incierto(conn, existente["id"])
    pedido, reserva = _cargar_pedido(conn, existente["id"])
    return jsonify(_pedido_a_dict(pedido, reserva, idempotente=True)), 200


def crear_pedido_con_reserva(conn, idempotency_key, request_hash, producto, cantidad, simular_pago):
    """Descuenta stock y guarda pedido y reserva en una sola transacción (BEGIN IMMEDIATE).

    Devuelve el id del pedido. Queda en PENDIENTE_PAGO con su reserva RESERVADA si había
    stock, o en SIN_STOCK (sin reserva ni payment_key) si no alcanzó.
    """
    monto = producto["precio"] * cantidad
    conn.execute("BEGIN IMMEDIATE")
    try:
        descontado = conn.execute(
            "UPDATE productos SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (cantidad, producto["id"], cantidad),
        ).rowcount
        if descontado == 1:
            estado, payment_key = "PENDIENTE_PAGO", "PAY-" + idempotency_key
        else:
            estado, payment_key = "SIN_STOCK", None
        pedido_id = conn.execute(
            "INSERT INTO pedidos (idempotency_key, request_hash, producto_id, cantidad, "
            "monto, simular_pago, payment_key, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (idempotency_key, request_hash, producto["id"], cantidad, monto,
             simular_pago, payment_key, estado),
        ).lastrowid
        if descontado == 1:
            conn.execute(
                "INSERT INTO reservas (pedido_id, producto_id, cantidad, estado) "
                "VALUES (?, ?, ?, 'RESERVADA')",
                (pedido_id, producto["id"], cantidad),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return pedido_id


def compensar_pedido(conn, pedido_id):
    """Libera la reserva del pedido, devuelve el stock y deja el pedido en RECHAZADO.

    Todo en una sola transacción. El stock se devuelve solo si el UPDATE de la reserva
    (RESERVADA -> LIBERADA) cambió 1 fila: llamarla otra vez sobre el mismo pedido no
    encuentra reserva RESERVADA y no vuelve a sumar stock. Un pedido en estado final
    (PAGADO, RECHAZADO, SIN_STOCK) no cambia.

    La usan el rechazo del pago al crear el pedido y la conciliación de pagos (issue #7).
    Devuelve True si en esta llamada liberó la reserva y devolvió el stock.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        reserva = conn.execute(
            "SELECT producto_id, cantidad FROM reservas "
            "WHERE pedido_id = ? AND estado = 'RESERVADA'",
            (pedido_id,),
        ).fetchone()
        liberada = conn.execute(
            "UPDATE reservas SET estado = 'LIBERADA', actualizado_en = datetime('now') "
            "WHERE pedido_id = ? AND estado = 'RESERVADA'",
            (pedido_id,),
        ).rowcount == 1
        if liberada:
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id = ?",
                (reserva["cantidad"], reserva["producto_id"]),
            )
        conn.execute(
            "UPDATE pedidos SET estado = 'RECHAZADO', actualizado_en = datetime('now') "
            "WHERE id = ? AND estado IN ('PENDIENTE_PAGO', 'PAGO_INCIERTO')",
            (pedido_id,),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return liberada


def procesar_resultado_pago(conn, pedido_id, pago):
    """Aplica al pedido el resultado del pago que respondió el mock.

    APROBADO: pedido PAGADO y reserva CONFIRMADA, en una transacción.
    RECHAZADO: compensar_pedido (reserva LIBERADA, stock devuelto, pedido RECHAZADO).
    Devuelve True si lo aplicó. La conciliación de un pago incierto (issue #7) se conecta aquí.
    """
    if pago.get("estado") == "RECHAZADO":
        compensar_pedido(conn, pedido_id)
        return True
    if pago.get("estado") != "APROBADO":
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE pedidos SET estado = 'PAGADO', actualizado_en = datetime('now') "
            "WHERE id = ? AND estado = 'PENDIENTE_PAGO'",
            (pedido_id,),
        )
        conn.execute(
            "UPDATE reservas SET estado = 'CONFIRMADA', actualizado_en = datetime('now') "
            "WHERE pedido_id = ? AND estado = 'RESERVADA'",
            (pedido_id,),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return True


@app.post("/orders")
def crear_pedido():
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not idempotency_key:
        return _error("falta el header Idempotency-Key", 400)

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return _error("el cuerpo debe ser un JSON válido", 400)
    producto_id = datos.get("producto_id")
    cantidad = datos.get("cantidad")
    simular_pago = datos.get("simular_pago", "aprobado")
    if not _es_entero(producto_id):
        return _error("falta producto_id (entero)", 400)
    if not _es_entero(cantidad) or cantidad < 1:
        return _error("cantidad debe ser un entero mayor o igual a 1", 400)
    if simular_pago not in SIMULACIONES_VALIDAS:
        return _error("simular_pago debe ser: " + ", ".join(SIMULACIONES_VALIDAS), 400)

    request_hash = _calcular_hash(producto_id, cantidad, simular_pago)
    conn = db.get_connection()
    conn.isolation_level = None  # transacciones manuales con BEGIN IMMEDIATE
    try:
        # Antes de crear nada: si la clave ya se usó, es el mismo intento.
        existente = _buscar_por_clave(conn, idempotency_key)
        if existente is not None:
            return responder_repeticion(conn, existente, request_hash)

        producto = conn.execute(
            "SELECT * FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if producto is None:
            return _error("producto no encontrado", 404)

        try:
            pedido_id = crear_pedido_con_reserva(
                conn, idempotency_key, request_hash, producto, cantidad, simular_pago,
            )
        except sqlite3.IntegrityError:
            # Otra petición con la misma clave se coló entre el SELECT y el INSERT: el UNIQUE
            # frenó el duplicado y crear_pedido_con_reserva ya hizo rollback (el stock vuelve).
            existente = _buscar_por_clave(conn, idempotency_key)
            if existente is None:
                raise
            return responder_repeticion(conn, existente, request_hash)
        pedido, reserva = _cargar_pedido(conn, pedido_id)
        if pedido["estado"] == "SIN_STOCK":
            return jsonify(_pedido_a_dict(pedido, reserva)), 409

        # El pedido y la reserva ya tienen commit: si algo falla desde aquí, quedan guardados.
        try:
            pago = payment_client.crear_pago(
                pedido["payment_key"], pedido_id, pedido["monto"], simular_pago
            )
        except requests.RequestException:
            # Timeout y recuperación: issue #7. Mientras tanto el pedido sigue PENDIENTE_PAGO.
            return _error("no se pudo confirmar el pago; el pedido quedó pendiente", 503)

        if not procesar_resultado_pago(conn, pedido_id, pago):
            pedido, reserva = _cargar_pedido(conn, pedido_id)
            respuesta = _pedido_a_dict(pedido, reserva)
            respuesta["mensaje"] = "resultado del pago pendiente de procesar"
            return jsonify(respuesta), 202
        pedido, reserva = _cargar_pedido(conn, pedido_id)
        return jsonify(_pedido_a_dict(pedido, reserva)), 201
    finally:
        conn.close()


@app.post("/admin/reset")
def reiniciar_datos():
    db.reset_db()
    return jsonify(mensaje="datos reiniciados")


# Rutas pendientes (ver docs/contrato-api.md):
#   PAGO_INCIERTO y POST /orders/<id>/reconciliar                    -> issue #7


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True)
