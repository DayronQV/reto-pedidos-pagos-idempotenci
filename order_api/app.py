"""Order API: crea pedidos, reserva inventario, inicia el pago y expone el estado.

Ejecutar:  python order_api/app.py   (puerto 5000 por defecto)
"""
import hashlib
import json
import os

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
    """Huella del cuerpo de la solicitud (la usará el issue #6 para detectar otro cuerpo)."""
    cuerpo = {"producto_id": producto_id, "cantidad": cantidad, "simular_pago": simular_pago}
    return hashlib.sha256(json.dumps(cuerpo, sort_keys=True).encode()).hexdigest()


def _cargar_pedido(conn, pedido_id):
    pedido = conn.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
    reserva = conn.execute(
        "SELECT * FROM reservas WHERE pedido_id = ?", (pedido_id,)
    ).fetchone()
    return pedido, reserva


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


def procesar_resultado_pago(conn, pedido_id, pago):
    """Aplica al pedido el resultado del pago que respondió el mock.

    Hoy solo resuelve APROBADO: pedido PAGADO y reserva CONFIRMADA, en una transacción.
    Sirve tanto para un pedido recién pagado como para uno que se concilió desde
    PAGO_INCIERTO. Devuelve True si lo aplicó. RECHAZADO (compensación, issue #8) se
    conecta aquí.
    """
    if pago.get("estado") != "APROBADO":
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE pedidos SET estado = 'PAGADO', actualizado_en = datetime('now') "
            "WHERE id = ? AND estado IN ('PENDIENTE_PAGO', 'PAGO_INCIERTO')",
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


def marcar_pago_incierto(conn, pedido_id):
    """Pasa el pedido a PAGO_INCIERTO (la reserva sigue RESERVADA, no se toca el stock)."""
    conn.execute(
        "UPDATE pedidos SET estado = 'PAGO_INCIERTO', actualizado_en = datetime('now') "
        "WHERE id = ? AND estado = 'PENDIENTE_PAGO'",
        (pedido_id,),
    )


@app.post("/orders/<int:pedido_id>/reconciliar")
def reconciliar_pedido(pedido_id):
    """Averigua el estado real de un pago incierto consultando al Payment Mock.

    Nunca cobra a ciegas: primero consulta. Solo si el mock responde 404 (el cobro nunca se
    registró) reenvía el cobro, con la misma payment_key del pedido.
    """
    conn = db.get_connection()
    conn.isolation_level = None  # transacciones manuales con BEGIN IMMEDIATE
    try:
        pedido, reserva = _cargar_pedido(conn, pedido_id)
        if pedido is None:
            return _error("pedido no encontrado", 404)
        if pedido["estado"] not in ("PENDIENTE_PAGO", "PAGO_INCIERTO"):
            return jsonify(_pedido_a_dict(pedido, reserva))  # ya es final: no se hace nada

        payment_key = pedido["payment_key"]
        print(f"[ORDER] pedido {pedido_id} en {pedido['estado']}; consultando {payment_key}")
        try:
            pago = payment_client.consultar_pago(payment_key)
            if pago is None:
                print(f"[ORDER] el mock no tiene {payment_key}; reenviando el cobro con la misma clave")
                pago = payment_client.crear_pago(
                    payment_key, pedido_id, pedido["monto"], pedido["simular_pago"]
                )
        except requests.RequestException:
            print(f"[ORDER] el mock no respondió; el pedido {pedido_id} sigue incierto")
            respuesta = _pedido_a_dict(pedido, reserva)
            respuesta["mensaje"] = "el Payment Mock no respondió; el pago sigue en verificación"
            return jsonify(respuesta), 503

        print(f"[ORDER] pago {payment_key} en el mock: {pago['estado']}")
        if not procesar_resultado_pago(conn, pedido_id, pago):
            # RECHAZADO: la compensación (compensar_pedido) es del issue #8 y aún no está.
            pedido, reserva = _cargar_pedido(conn, pedido_id)
            respuesta = _pedido_a_dict(pedido, reserva)
            respuesta["mensaje"] = "pago rechazado; compensación pendiente (issue #8)"
            return jsonify(respuesta), 501
        pedido, reserva = _cargar_pedido(conn, pedido_id)
        return jsonify(_pedido_a_dict(pedido, reserva))
    finally:
        conn.close()


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

    conn = db.get_connection()
    conn.isolation_level = None  # transacciones manuales con BEGIN IMMEDIATE
    try:
        producto = conn.execute(
            "SELECT * FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if producto is None:
            return _error("producto no encontrado", 404)

        pedido_id = crear_pedido_con_reserva(
            conn, idempotency_key, _calcular_hash(producto_id, cantidad, simular_pago),
            producto, cantidad, simular_pago,
        )
        pedido, reserva = _cargar_pedido(conn, pedido_id)
        if pedido["estado"] == "SIN_STOCK":
            return jsonify(_pedido_a_dict(pedido, reserva)), 409

        # El pedido y la reserva ya tienen commit: si algo falla desde aquí, quedan guardados.
        try:
            pago = payment_client.crear_pago(
                pedido["payment_key"], pedido_id, pedido["monto"], simular_pago
            )
        except (requests.Timeout, requests.ConnectionError):
            # No sabemos si el mock cobró: no se reintenta, se deja PAGO_INCIERTO y se
            # averigua después consultando (POST /orders/<id>/reconciliar).
            marcar_pago_incierto(conn, pedido_id)
            print(
                f"[ORDER] pedido {pedido_id} en PAGO_INCIERTO; "
                f"hay que consultar {pedido['payment_key']}"
            )
            pedido, reserva = _cargar_pedido(conn, pedido_id)
            respuesta = _pedido_a_dict(pedido, reserva)
            respuesta["mensaje"] = "pago en verificación"
            return jsonify(respuesta), 202
        except requests.RequestException:
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
#   Idempotency-Key en POST /orders                                  -> issue #6
#   Compensación cuando el pago es rechazado                         -> issue #8


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True)
