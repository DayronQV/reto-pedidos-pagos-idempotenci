"""Cliente HTTP de la Order API hacia el Payment Mock.

Se implementa en los issues #5 (crear pago) y #7 (consultar pago).
Toda llamada al mock debe usar timeout=PAYMENT_TIMEOUT_SECONDS.
"""
import os

import requests

PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "http://127.0.0.1:5001")
PAYMENT_TIMEOUT_SECONDS = float(os.getenv("PAYMENT_TIMEOUT_SECONDS", "2"))


def crear_pago(payment_key, pedido_id, monto, simular):
    """Cobra un pedido en el Payment Mock (POST /payments) y devuelve el pago como dict.

    Usa timeout=PAYMENT_TIMEOUT_SECONDS. Si el mock no responde a tiempo, hay un error de
    red o responde un código de error, lanza una excepción de requests; quien llama decide
    qué hacer (el manejo de PAGO_INCIERTO se agrega en el issue #7).
    """
    respuesta = requests.post(
        f"{PAYMENT_API_URL}/payments",
        json={
            "payment_key": payment_key,
            "pedido_id": pedido_id,
            "monto": monto,
            "simular": simular,
        },
        timeout=PAYMENT_TIMEOUT_SECONDS,
    )
    respuesta.raise_for_status()
    return respuesta.json()
