"""Order API: crea pedidos, reserva inventario, inicia el pago y expone el estado.

Ejecutar:  python order_api/app.py   (puerto 5000 por defecto)
"""
import os

from flask import Flask, jsonify

import db

PORT = int(os.getenv("ORDER_API_PORT", "5000"))

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


@app.post("/admin/reset")
def reiniciar_datos():
    db.reset_db()
    return jsonify(mensaje="datos reiniciados")


# Rutas pendientes (ver docs/contrato-api.md):
#   POST /orders (flujo exitoso)                                     -> issue #5
#   Idempotency-Key en POST /orders                                  -> issue #6
#   PAGO_INCIERTO y POST /orders/<id>/reconciliar                    -> issue #7
#   Compensación cuando el pago es rechazado                         -> issue #8


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True)
