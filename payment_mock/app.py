"""Payment Mock API: simula un proveedor de pagos (aprobado, rechazado o timeout).

No procesa tarjetas ni dinero real.
Ejecutar:  python payment_mock/app.py   (puerto 5001 por defecto)
"""
import os
import sqlite3

from flask import Flask, jsonify, request

import db

PORT = int(os.getenv("PAYMENT_MOCK_PORT", "5001"))
# Cuánto tarda en responder cuando simula la respuesta perdida (issue #3).
# Debe ser mayor que PAYMENT_TIMEOUT_SECONDS de la Order API.
MOCK_TIMEOUT_DELAY_SECONDS = float(os.getenv("MOCK_TIMEOUT_DELAY_SECONDS", "5"))

# Resultado que se guarda según el valor de "simular" (el modo timeout llega en el issue #3).
ESTADO_POR_SIMULACION = {"aprobado": "APROBADO", "rechazado": "RECHAZADO"}

app = Flask(__name__)
app.json.ensure_ascii = False  # respuestas JSON con tildes legibles

db.init_db()


def pago_a_dict(fila, nuevo=None):
    pago = {
        "payment_key": fila["payment_key"],
        "pedido_id": fila["pedido_id"],
        "monto": fila["monto"],
        "estado": fila["estado"],
    }
    if nuevo is not None:
        pago["nuevo"] = nuevo
    pago["creado_en"] = fila["creado_en"]
    return pago


def buscar_pago(conn, payment_key):
    return conn.execute(
        "SELECT * FROM pagos WHERE payment_key = ?", (payment_key,)
    ).fetchone()


def error(mensaje, codigo):
    return jsonify(error=mensaje), codigo


@app.get("/health")
def health():
    return jsonify(status="ok", servicio="payment-mock")


@app.post("/payments")
def crear_pago():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return error("el cuerpo debe ser un JSON válido", 400)

    payment_key = datos.get("payment_key")
    pedido_id = datos.get("pedido_id")
    monto = datos.get("monto")
    simular = datos.get("simular", "aprobado")

    if not isinstance(payment_key, str) or not payment_key.strip():
        return error("falta payment_key", 400)
    if isinstance(pedido_id, bool) or not isinstance(pedido_id, int):
        return error("falta pedido_id (entero)", 400)
    if isinstance(monto, bool) or not isinstance(monto, (int, float)) or monto <= 0:
        return error("falta monto (número mayor que 0)", 400)
    if simular not in ESTADO_POR_SIMULACION:
        return error("simular debe ser: " + ", ".join(ESTADO_POR_SIMULACION), 400)

    estado = ESTADO_POR_SIMULACION[simular]
    conn = db.get_connection()
    try:
        existente = buscar_pago(conn, payment_key)
        if existente:
            return jsonify(pago_a_dict(existente, nuevo=False)), 200

        try:
            conn.execute(
                "INSERT INTO pagos (payment_key, pedido_id, monto, estado) "
                "VALUES (?, ?, ?, ?)",
                (payment_key, pedido_id, float(monto), estado),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Otra petición con la misma clave se coló entre el SELECT y el INSERT:
            # la restricción UNIQUE evitó la fila duplicada; devolvemos la ya guardada.
            conn.rollback()
            existente = buscar_pago(conn, payment_key)
            return jsonify(pago_a_dict(existente, nuevo=False)), 200

        print(f"[MOCK] cobro {payment_key} registrado como {estado}")
        return jsonify(pago_a_dict(buscar_pago(conn, payment_key), nuevo=True)), 201
    finally:
        conn.close()


@app.get("/payments/<payment_key>")
def consultar_pago(payment_key):
    conn = db.get_connection()
    try:
        fila = buscar_pago(conn, payment_key)
    finally:
        conn.close()
    if not fila:
        return error("pago no encontrado", 404)
    return jsonify(pago_a_dict(fila))


@app.get("/payments")
def listar_pagos():
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM pagos ORDER BY id").fetchall()
    finally:
        conn.close()
    return jsonify([pago_a_dict(f) for f in filas])


@app.post("/admin/reset")
def reset():
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM pagos")
        conn.commit()
    finally:
        conn.close()
    return jsonify(mensaje="pagos eliminados")


# Rutas pendientes (ver docs/contrato-api.md):
#   Modo "simular": "timeout" (guardar el cobro y luego demorar la respuesta) -> issue #3


if __name__ == "__main__":
    # threaded=True: permite consultar un pago mientras otra petición simula el timeout.
    app.run(host="127.0.0.1", port=PORT, threaded=True)
