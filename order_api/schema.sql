-- Tablas de la Order API: productos, pedidos y reservas.
-- Los valores de "estado" están definidos en docs/estados.md.

CREATE TABLE IF NOT EXISTS productos (
  id     INTEGER PRIMARY KEY,
  nombre TEXT    NOT NULL,
  precio REAL    NOT NULL,
  stock  INTEGER NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS pedidos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT    NOT NULL UNIQUE,
  request_hash    TEXT    NOT NULL,
  producto_id     INTEGER NOT NULL REFERENCES productos(id),
  cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
  monto           REAL    NOT NULL,
  simular_pago    TEXT    NOT NULL,
  payment_key     TEXT    UNIQUE,
  estado          TEXT    NOT NULL CHECK (estado IN
                    ('PENDIENTE_PAGO','PAGO_INCIERTO','PAGADO','RECHAZADO','SIN_STOCK')),
  creado_en       TEXT    NOT NULL DEFAULT (datetime('now')),
  actualizado_en  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reservas (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  pedido_id      INTEGER NOT NULL UNIQUE REFERENCES pedidos(id),
  producto_id    INTEGER NOT NULL REFERENCES productos(id),
  cantidad       INTEGER NOT NULL,
  estado         TEXT    NOT NULL CHECK (estado IN ('RESERVADA','CONFIRMADA','LIBERADA')),
  creado_en      TEXT    NOT NULL DEFAULT (datetime('now')),
  actualizado_en TEXT    NOT NULL DEFAULT (datetime('now'))
);
