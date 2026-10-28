"""Conexión a SQLite y creación de la tabla de pagos del Payment Mock.

Se implementa en el issue #2. Debe:
  - Usar la base payment_mock/payments.db.
  - Crear la tabla de schema.sql si no existe.
"""
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payments.db")
