"""Conexión a SQLite y creación de tablas de la Order API.

  - Usa la base order_api/orders.db.
  - Ejecuta PRAGMA foreign_keys = ON en cada conexión.
  - Crea las tablas de schema.sql si no existen y carga los productos iniciales.
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "orders.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

# (id, nombre, precio, stock). Producto 1: casos 1 a 4. Producto 2: caso 5 (stock 1).
PRODUCTOS_INICIALES = [
    (1, "Teclado mecánico", 25.00, 10),
    (2, "Edición limitada", 99.00, 1),
]


def get_connection():
    """Abre una conexión nueva con claves foráneas activas y filas tipo diccionario."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _cargar_productos(conn):
    """Inserta los productos iniciales solo si la tabla está vacía."""
    total = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    if total == 0:
        conn.executemany(
            "INSERT INTO productos (id, nombre, precio, stock) VALUES (?, ?, ?, ?)",
            PRODUCTOS_INICIALES,
        )


def init_db():
    """Crea las tablas si no existen y carga los datos iniciales."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    conn = get_connection()
    try:
        conn.executescript(schema)
        _cargar_productos(conn)
        conn.commit()
    finally:
        conn.close()


def reset_db():
    """Borra pedidos y reservas y devuelve el stock a los valores iniciales."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM reservas")
        conn.execute("DELETE FROM pedidos")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('pedidos', 'reservas')")
        for id_, _nombre, _precio, stock in PRODUCTOS_INICIALES:
            conn.execute("UPDATE productos SET stock = ? WHERE id = ?", (stock, id_))
        conn.commit()
    finally:
        conn.close()
