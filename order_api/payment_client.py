"""Cliente HTTP de la Order API hacia el Payment Mock.

Se implementa en los issues #5 (crear pago) y #7 (consultar pago).
Toda llamada al mock debe usar timeout=PAYMENT_TIMEOUT_SECONDS.
"""
import os

PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "http://127.0.0.1:5001")
PAYMENT_TIMEOUT_SECONDS = float(os.getenv("PAYMENT_TIMEOUT_SECONDS", "2"))
