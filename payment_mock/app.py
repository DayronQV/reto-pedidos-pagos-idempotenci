"""Payment Mock API: simula un proveedor de pagos (aprobado, rechazado o timeout).

No procesa tarjetas ni dinero real.
Ejecutar:  python payment_mock/app.py   (puerto 5001 por defecto)
"""
import os

from flask import Flask, jsonify

PORT = int(os.getenv("PAYMENT_MOCK_PORT", "5001"))
# Cuánto tarda en responder cuando simula la respuesta perdida (issue #3).
# Debe ser mayor que PAYMENT_TIMEOUT_SECONDS de la Order API.
MOCK_TIMEOUT_DELAY_SECONDS = float(os.getenv("MOCK_TIMEOUT_DELAY_SECONDS", "5"))

app = Flask(__name__)
app.json.ensure_ascii = False  # respuestas JSON con tildes legibles


@app.get("/health")
def health():
    return jsonify(status="ok", servicio="payment-mock")


# Rutas pendientes (ver docs/contrato-api.md):
#   POST /payments, GET /payments/<payment_key>, GET /payments, POST /admin/reset -> issue #2
#   Modo "simular": "timeout" (guardar el cobro y luego demorar la respuesta)   -> issue #3


if __name__ == "__main__":
    # threaded=True: permite consultar un pago mientras otra petición simula el timeout.
    app.run(host="127.0.0.1", port=PORT, threaded=True)
