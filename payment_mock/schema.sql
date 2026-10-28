-- Tabla de pagos del Payment Mock (payment_key única).
-- Valores de "estado" según docs/estados.md.
CREATE TABLE IF NOT EXISTS pagos (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_key TEXT    NOT NULL UNIQUE,
  pedido_id   INTEGER NOT NULL,
  monto       REAL    NOT NULL,
  estado      TEXT    NOT NULL CHECK (estado IN ('APROBADO', 'RECHAZADO')),
  creado_en   TEXT    NOT NULL DEFAULT (datetime('now'))
);
