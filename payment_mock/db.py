"""Conexión a SQLite y creación de la tabla de pagos del Payment Mock.

Usa la base payment_mock/payments.db y crea la tabla de schema.sql si no existe.
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "payments.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def get_connection():
    """Abre una conexión nueva; cada petición usa la suya (Flask corre con threads)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crea la tabla de pagos si no existe. Los datos existentes se conservan."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    conn = get_connection()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
