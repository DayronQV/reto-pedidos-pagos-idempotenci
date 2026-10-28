"""Conexión a SQLite y creación de tablas de la Order API.

Se implementa en el issue #4. Debe:
  - Usar la base order_api/orders.db.
  - Ejecutar PRAGMA foreign_keys = ON en cada conexión.
  - Crear las tablas de schema.sql si no existen y cargar los productos iniciales.
"""
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")
