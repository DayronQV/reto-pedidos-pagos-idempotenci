# Contrato de la API

Endpoints, cuerpos y respuestas de los dos servicios. Es la referencia común para que el código de cada issue encaje con el de los demás. Los estados se explican en [estados.md](estados.md).

| Servicio | URL base | Variable de entorno del puerto |
|---|---|---|
| Order API | `http://127.0.0.1:5000` | `ORDER_API_PORT` |
| Payment Mock API | `http://127.0.0.1:5001` | `PAYMENT_MOCK_PORT` |

Todas las respuestas son JSON. Los errores usan la forma `{"error": "mensaje"}`.

---

## Payment Mock API

### `GET /health`
**200** → `{"status": "ok", "servicio": "payment-mock"}`

### `POST /payments` — registrar un pago *(issues #2 y #3)*

```json
{
  "payment_key": "PAY-caso1-abc123",
  "pedido_id": 1,
  "monto": 25.0,
  "simular": "aprobado"
}
```

`simular` puede ser:

| Valor | Qué hace |
|---|---|
| `aprobado` | Guarda el pago como `APROBADO` y responde enseguida |
| `rechazado` | Guarda el pago como `RECHAZADO` y responde enseguida |
| `timeout` | Guarda el pago como `APROBADO`, hace `commit` y **después** espera `MOCK_TIMEOUT_DELAY_SECONDS` (5 s) antes de responder |

| Código | Cuándo | Cuerpo |
|---|---|---|
| **201** | `payment_key` nueva | El pago con `"nuevo": true` |
| **200** | `payment_key` ya existía (no se inserta otra fila ni se vuelve a esperar) | El pago guardado con `"nuevo": false` |
| **400** | Falta `payment_key`, `pedido_id` o `monto`, o `simular` no es válido | `{"error": "..."}` |

Ejemplo de respuesta **201**:
```json
{
  "payment_key": "PAY-caso1-abc123",
  "pedido_id": 1,
  "monto": 25.0,
  "estado": "APROBADO",
  "nuevo": true,
  "creado_en": "2026-10-28 20:00:00"
}
```

### `GET /payments/<payment_key>` — consultar un pago *(issue #2)*
| Código | Cuándo |
|---|---|
| **200** | Existe: devuelve el pago |
| **404** | `{"error": "pago no encontrado"}` (el cobro nunca se registró) |

### `GET /payments` — listar pagos *(issue #2)*
**200** → lista de pagos (sirve como evidencia).

### `POST /admin/reset` — borrar pagos *(issue #2)*
**200** → `{"mensaje": "pagos eliminados"}`. Solo para repetir las pruebas desde cero.

---

## Order API

### `GET /health`
**200** → `{"status": "ok", "servicio": "order-api"}`

### `GET /products` — inventario *(issue #4)*
**200**:
```json
[
  {"id": 1, "nombre": "Teclado mecánico", "precio": 25.0, "stock": 10},
  {"id": 2, "nombre": "Edición limitada", "precio": 99.0, "stock": 1}
]
```

### `GET /orders` — listar pedidos *(issue #4)*
**200** → lista de pedidos.

### `GET /orders/<id>` — consultar un pedido *(issue #4)*
**200** → el pedido con su reserva (formato abajo). **404** → `{"error": "pedido no encontrado"}`.

### `POST /orders` — crear pedido *(issues #5, #6, #7 y #8)*

Header obligatorio: `Idempotency-Key: caso1-abc123`

```json
{ "producto_id": 1, "cantidad": 1, "simular_pago": "aprobado" }
```

`simular_pago` ∈ `aprobado | rechazado | timeout` (se reenvía al mock como `simular`).

Respuesta (mismo formato en todos los casos que devuelven un pedido):
```json
{
  "id": 1,
  "idempotency_key": "caso1-abc123",
  "producto_id": 1,
  "cantidad": 1,
  "monto": 25.0,
  "payment_key": "PAY-caso1-abc123",
  "estado": "PAGADO",
  "reserva": { "estado": "CONFIRMADA", "cantidad": 1 },
  "idempotente": false
}
```
`reserva` es `null` cuando el pedido quedó en `SIN_STOCK`.

| Código | Cuándo | Estado del pedido |
|---|---|---|
| **201** | Pedido nuevo y pago resuelto | `PAGADO` o `RECHAZADO` |
| **202** | Pedido nuevo pero la respuesta del pago se perdió; incluye `"mensaje": "pago en verificación"` | `PAGO_INCIERTO` |
| **200** | Se repitió la misma `Idempotency-Key` con el mismo cuerpo; incluye `"idempotente": true`. Si el pedido estaba en `PAGO_INCIERTO`, antes de responder se concilia | El guardado (o el resultado de conciliar) |
| **409** | No había stock (primera vez) | `SIN_STOCK` |
| **409** | La misma `Idempotency-Key` llegó con un cuerpo distinto: `{"error": "la Idempotency-Key ya se usó con otra solicitud"}` | — |
| **400** | Falta el header, `cantidad < 1` o `simular_pago` inválido | — |
| **404** | El producto no existe | — |

### `POST /orders/<id>/reconciliar` — recuperar un pago incierto *(issue #7)*

Consulta `GET /payments/<payment_key>` en el mock y decide:

| Respuesta del mock | Acción | Código |
|---|---|---|
| `APROBADO` | Pedido `PAGADO`, reserva `CONFIRMADA` | **200** |
| `RECHAZADO` | Compensación: pedido `RECHAZADO`, reserva `LIBERADA` | **200** |
| **404** (cobro nunca registrado) | Reenvía `POST /payments` con **la misma** `payment_key` y aplica el resultado | **200** |
| Sin respuesta / caído | El pedido sigue en `PAGO_INCIERTO` | **503** |
| *(pedido ya en estado final)* | No hace nada, devuelve el pedido | **200** |

**404** si el pedido no existe.

### `POST /admin/reset` — reiniciar datos *(issue #4)*
**200** → `{"mensaje": "datos reiniciados"}`. Borra pedidos y reservas y devuelve el stock a los valores iniciales. Solo para repetir las pruebas desde cero.

---

## Variables de entorno

| Variable | Servicio | Por defecto | Para qué |
|---|---|---|---|
| `ORDER_API_PORT` | Order API | `5000` | Puerto de la Order API |
| `PAYMENT_API_URL` | Order API | `http://127.0.0.1:5001` | Dónde está el Payment Mock |
| `PAYMENT_TIMEOUT_SECONDS` | Order API | `2` | Cuánto espera la respuesta del mock antes de marcar `PAGO_INCIERTO` |
| `PAYMENT_MOCK_PORT` | Payment Mock | `5001` | Puerto del mock |
| `MOCK_TIMEOUT_DELAY_SECONDS` | Payment Mock | `5` | Cuánto demora la respuesta en el modo `timeout` (debe ser mayor que `PAYMENT_TIMEOUT_SECONDS`) |
