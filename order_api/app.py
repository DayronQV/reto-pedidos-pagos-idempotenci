"""Order API: crea pedidos, reserva inventario, inicia el pago y expone el estado.

Ejecutar:  python order_api/app.py   (puerto 5000 por defecto)
"""
import os

from flask import Flask, jsonify

PORT = int(os.getenv("ORDER_API_PORT", "5000"))

app = Flask(__name__)
app.json.ensure_ascii = False  # respuestas JSON con tildes legibles


@app.get("/health")
def health():
    return jsonify(status="ok", servicio="order-api")


# Rutas pendientes (ver docs/contrato-api.md):
#   GET  /products, GET /orders, GET /orders/<id>, POST /admin/reset  -> issue #4
#   POST /orders (flujo exitoso)                                     -> issue #5
#   Idempotency-Key en POST /orders                                  -> issue #6
#   PAGO_INCIERTO y POST /orders/<id>/reconciliar                    -> issue #7
#   Compensación cuando el pago es rechazado                         -> issue #8


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True)
