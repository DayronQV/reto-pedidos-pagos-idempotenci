# Contexto para agentes de código

Este archivo da el contexto del proyecto a cualquier agente de IA (Claude Code, Copilot, Cursor, Codex) que trabaje en el repositorio. Para instalar y ejecutar, ver [README.md](README.md).

## El reto en pocas líneas

Dos servicios Flask, cada uno con **su propia base SQLite**:

- **Order API** (`order_api/`, puerto 5000): crea pedidos, reserva inventario, llama al pago y expone el estado.
- **Payment Mock API** (`payment_mock/`, puerto 5001): simula pagos `aprobado`, `rechazado` y `timeout` (guarda el cobro y luego demora la respuesta).

El objetivo es demostrar que, aunque **el pago se cobra y su respuesta se pierde**, el sistema no duplica pedidos, reservas ni cobros, y averigua el estado consultando en lugar de reintentar a ciegas. Se prueba con una colección de Postman de 5 casos (ver README).

## Documentos de referencia (fuente única de verdad)

- [docs/estados.md](docs/estados.md): estados del pedido, la reserva y el pago, con sus transiciones. Usar **exactamente** esos valores.
- [docs/contrato-api.md](docs/contrato-api.md): endpoints, cuerpos, respuestas, códigos HTTP y variables de entorno. Si algo del código no coincide con el contrato, se corrige el código o se actualiza el contrato en el mismo PR.
- Issues de GitHub: cada tarea tiene su issue con criterios de aceptación. Leerlo con `gh issue view <N>` antes de empezar.

## Reglas que no se pueden romper

Son las que evalúa la rúbrica:

1. **Idempotencia en la base, no solo en memoria.** `pedidos.idempotency_key`, `pedidos.payment_key` y `pagos.payment_key` son `UNIQUE`. Además del `SELECT` previo, capturar `sqlite3.IntegrityError`.
2. **Misma clave = mismo intento.** Repetir una `Idempotency-Key` devuelve el pedido guardado (200, `"idempotente": true`) sin tocar stock, sin reserva nueva y sin llamar al mock. Misma clave con otro cuerpo → 409.
3. **Nunca cobrar a ciegas.** Si la llamada al mock da timeout o error de red, el pedido queda en `PAGO_INCIERTO`. Para salir de ahí se **consulta** `GET /payments/<payment_key>`. Solo si el mock responde 404 se reenvía el cobro, con **la misma** `payment_key`.
4. **La `payment_key` es `"PAY-" + Idempotency-Key`** y nunca se genera otra para un pedido existente.
5. **El mock guarda el cobro y hace `commit` antes de demorar la respuesta** en el modo `timeout`.
6. **El stock nunca queda negativo.** Descontar con `UPDATE productos SET stock = stock - ? WHERE id = ? AND stock >= ?` y revisar `rowcount`; la columna tiene `CHECK (stock >= 0)`.
7. **La reserva se libera una sola vez.** `UPDATE reservas SET estado = 'LIBERADA' WHERE pedido_id = ? AND estado = 'RESERVADA'`, y devolver stock solo si `rowcount == 1`.
8. **Commit antes de llamar al mock.** El pedido y la reserva se guardan antes de la llamada HTTP, para poder recuperarlos si algo falla.
9. **Todo estado vive en SQLite**, nunca en variables globales: debe sobrevivir a un reinicio.

## Convenciones

- Código, comentarios, mensajes de error y commits **en español**. Los nombres de endpoints siguen el contrato (`/orders`, `/payments`, etc.).
- Cada servicio se ejecuta como script (`python order_api/app.py`), así que los módulos se importan entre sí con `import db`, `import payment_client`.
- Configuración solo por variables de entorno con valor por defecto (ver contrato).
- Sin dependencias nuevas salvo que el issue lo pida; si se agrega una, fijar la versión en `requirements.txt`.
- No subir bases `.db` ni `.venv/` (ya están en `.gitignore`).

## Cómo trabajar un issue

1. Leer el issue: `gh issue view <N>`.
2. Crear la rama que sugiere el issue desde `main` actualizado.
3. Tocar solo los archivos de ese issue. Si hace falta cambiar algo de otro issue, avisar en vez de reescribirlo.
4. Probar a mano los criterios de aceptación (Postman o `curl`) y revisar la base SQLite.
5. Abrir un PR hacia `main` con `Closes #<N>`; nunca hacer push directo a `main`.

## Equipo

Jose Ponce Carlos (@Joseepc18), Luis Anchundia Cruz (@LuisAnchundia) y Dayron Quiñonez Valencia (@DayronQV).
