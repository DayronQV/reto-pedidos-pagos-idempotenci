# Reto técnico: pedidos, pagos simulados e idempotencia

API de pedidos que se recupera cuando **un pago se procesa pero su respuesta se pierde**, sin duplicar pedidos, reservas ni cobros.

Asignatura: **Sistemas Distribuidos**, séptimo semestre.

## Integrantes

| Integrante | Usuario de GitHub |
|---|---|
| Jose Ponce Carlos | [@Joseepc18](https://github.com/Joseepc18) |
| Luis Anchundia Cruz | [@LuisAnchundia](https://github.com/LuisAnchundia) |
| Dayron Quiñonez Valencia | [@DayronQV](https://github.com/DayronQV) |

## De qué se trata

Una tienda recibe una solicitud para crear un pedido y reservar inventario. El pedido se registra y el servicio de pago alcanza a **registrar el cobro**, pero **la respuesta del pago se pierde**. El backend no sabe si debe reintentar, consultar el estado o cancelar la reserva; si repite la operación a ciegas podría **cobrar dos veces** o **reservar dos veces**.

Para resolverlo construimos dos servicios Flask, cada uno con su propia base SQLite:

- **Order API**: crea pedidos, controla el inventario, inicia el pago y expone el estado.
- **Payment Mock API**: simula un pago aprobado, uno rechazado y un **timeout después de registrar el cobro**. No procesa tarjetas ni dinero real.

Y aplicamos cuatro ideas:

| Idea | Cómo la aplicamos |
|---|---|
| **Idempotencia** | Cada pedido llega con un header `Idempotency-Key` guardado con restricción `UNIQUE`. Misma clave = mismo intento: se devuelve el resultado conocido sin crear otra reserva ni otro cobro. Clave distinta = otra intención de compra |
| **Recuperación** | Si la respuesta del pago se pierde, el pedido queda en `PAGO_INCIERTO` y se **consulta** el pago en el mock por su `payment_key`. Nunca se vuelve a cobrar a ciegas |
| **Compensación** | Si el pago se rechaza después de reservar, la reserva se **libera una sola vez** y el pedido queda `RECHAZADO` |
| **Persistencia** | Todos los estados viven en SQLite, así que se pueden consultar y recuperar incluso después de reiniciar los servicios |

## Arquitectura

```mermaid
flowchart LR
    P[Postman] -->|HTTP :5000| O[Order API<br/>Flask]
    O -->|HTTP :5001<br/>timeout 2 s| M[Payment Mock API<br/>Flask]
    O --- OD[(orders.db<br/>productos, pedidos,<br/>reservas)]
    M --- MD[(payments.db<br/>pagos)]
```

Postman habla solo con la Order API (y con el mock para consultar evidencia). La Order API llama al mock con un tiempo límite de 2 s. En el modo `timeout`, el mock guarda el cobro y tarda 5 s en responder, así la respuesta "se pierde".

## Herramientas

| Herramienta | Uso |
|---|---|
| Python 3.10 o superior | Lenguaje de ambos servicios |
| Flask 3.1 | Framework web de las dos APIs |
| requests 2.34 | Llamadas HTTP de la Order API al mock, con tiempo límite |
| SQLite (`sqlite3` de Python) | Persistencia de cada servicio; no hay que instalar nada |
| Postman | Colección con los 5 casos de prueba |
| Git y GitHub | Código, issues y pull requests del equipo |

## Estructura del proyecto

```
reto-pedidos-pagos-idempotenci/
├── order_api/
│   ├── app.py              # Rutas Flask de la Order API (puerto 5000)
│   ├── db.py               # Conexión SQLite y creación de tablas
│   ├── schema.sql          # Tablas: productos, pedidos, reservas
│   └── payment_client.py   # Llamadas HTTP al Payment Mock (con timeout)
├── payment_mock/
│   ├── app.py              # Rutas Flask del Payment Mock (puerto 5001)
│   ├── db.py               # Conexión SQLite y creación de la tabla
│   └── schema.sql          # Tabla: pagos
├── postman/                # Colección de Postman exportada
├── scripts/                # Script de evidencia SQLite
├── docs/
│   ├── estados.md          # Estados del pedido, la reserva y el pago
│   └── contrato-api.md     # Endpoints, cuerpos y respuestas
├── AGENTS.md               # Contexto y reglas para agentes de IA
├── CLAUDE.md               # Apunta a AGENTS.md (Claude Code)
├── requirements.txt
└── README.md
```

Las bases `order_api/orders.db` y `payment_mock/payments.db` se crean solas al arrancar cada servicio y no se suben al repositorio.

## Estados

| Pedido | Significado |
|---|---|
| `PENDIENTE_PAGO` | Creado y con stock reservado; esperando el pago |
| `PAGO_INCIERTO` | La respuesta del pago se perdió; hay que consultar al mock |
| `PAGADO` | Pago aprobado, reserva confirmada (final) |
| `RECHAZADO` | Pago rechazado, reserva liberada (final) |
| `SIN_STOCK` | No había inventario; sin reserva ni cobro (final) |

Reservas: `RESERVADA`, `CONFIRMADA`, `LIBERADA`. Pagos: `APROBADO`, `RECHAZADO`.
Detalle y transiciones en [docs/estados.md](docs/estados.md).

## Instalación

Clonar el repositorio y crear un entorno virtual:

```bash
git clone https://github.com/DayronQV/reto-pedidos-pagos-idempotenci.git
cd reto-pedidos-pagos-idempotenci
python -m venv .venv
```

Instalar las dependencias.

Windows (PowerShell):
```powershell
.venv\Scripts\python -m pip install -r requirements.txt
```

Linux / macOS:
```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Ejecución

Cada servicio se levanta en **su propia terminal**, desde la raíz del repositorio.

**Terminal 1: Payment Mock API** (puerto 5001)

Windows:
```powershell
.venv\Scripts\python payment_mock\app.py
```

Linux / macOS:
```bash
.venv/bin/python payment_mock/app.py
```

**Terminal 2: Order API** (puerto 5000)

Windows:
```powershell
.venv\Scripts\python order_api\app.py
```

Linux / macOS:
```bash
.venv/bin/python order_api/app.py
```

**Comprobar que ambos responden:**

```bash
curl http://127.0.0.1:5001/health
```

```bash
curl http://127.0.0.1:5000/health
```

Cada uno debe responder `{"status": "ok", ...}`.

### Variables de entorno (opcionales)

| Variable | Por defecto | Para qué |
|---|---|---|
| `ORDER_API_PORT` | `5000` | Puerto de la Order API |
| `PAYMENT_API_URL` | `http://127.0.0.1:5001` | Dónde encuentra la Order API al mock |
| `PAYMENT_TIMEOUT_SECONDS` | `2` | Cuánto espera la Order API la respuesta del pago |
| `PAYMENT_MOCK_PORT` | `5001` | Puerto del Payment Mock |
| `MOCK_TIMEOUT_DELAY_SECONDS` | `5` | Cuánto tarda el mock en responder en el modo `timeout` |

Ejemplo en PowerShell: `$env:ORDER_API_PORT = "5050"` antes de arrancar el servicio. En macOS el puerto 5000 puede estar ocupado por AirPlay; en ese caso usar otro puerto.

## Endpoints

| Servicio | Método y ruta | Para qué |
|---|---|---|
| Ambos | `GET /health` | Comprobar que el servicio está arriba |
| Order API | `GET /products` | Ver inventario |
| Order API | `POST /orders` | Crear pedido (header `Idempotency-Key`) |
| Order API | `GET /orders`, `GET /orders/<id>` | Consultar pedidos |
| Order API | `POST /orders/<id>/reconciliar` | Recuperar un pedido con pago incierto |
| Order API | `POST /admin/reset` | Reiniciar datos de prueba |
| Payment Mock | `POST /payments` | Registrar pago (`aprobado`, `rechazado` o `timeout`) |
| Payment Mock | `GET /payments`, `GET /payments/<payment_key>` | Consultar pagos |
| Payment Mock | `POST /admin/reset` | Borrar pagos de prueba |

Cuerpos, respuestas y códigos HTTP en [docs/contrato-api.md](docs/contrato-api.md).

## Casos de prueba (Postman)

| Caso | Qué se hace | Qué se demuestra |
|---|---|---|
| 1. Flujo exitoso | Pedido con pago aprobado | 1 pedido, 1 reserva, 1 cobro y estado `PAGADO` |
| 2. Repetición de la misma solicitud | Reenviar con la misma `Idempotency-Key` | No se duplica pedido, reserva ni cobro |
| 3. Respuesta perdida después del cobro | El mock registra el cobro y simula timeout; se reintenta con la misma clave | Se resuelve consultando el pago, sin cobrar otra vez |
| 4. Pago rechazado | Forzar el rechazo | Pedido `RECHAZADO` y reserva liberada una sola vez |
| 5. Otra intención de compra | Otra clave cuando queda una unidad | Se trata como operación distinta y el stock nunca queda negativo |

La colección exportada estará en `postman/`.
