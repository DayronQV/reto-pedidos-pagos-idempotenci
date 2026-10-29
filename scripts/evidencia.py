"""Evidencia SQLite: muestra qué quedó guardado en las dos bases después de las pruebas.

Solo usa sqlite3 de Python (no hay que instalar nada) y abre las bases en modo lectura,
así que se puede ejecutar con los servicios encendidos o apagados.

Ejecutar desde la raíz del repositorio:  python scripts/evidencia.py
Termina con código 0 si la evidencia es correcta y con 1 si encuentra algo que revisar.
"""
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERS_DB = os.path.join(RAIZ, "order_api", "orders.db")
PAYMENTS_DB = os.path.join(RAIZ, "payment_mock", "payments.db")

# Cada ítem que falle se agrega aquí y define el código de salida.
problemas = []


def abrir(ruta):
    """Abre una base existente solo en lectura; si no existe, avisa y sale."""
    if not os.path.exists(ruta):
        print(f"No existe {os.path.relpath(ruta, RAIZ)}: arranca el servicio al menos una vez.")
        sys.exit(1)
    conn = sqlite3.connect("file:" + ruta.replace("\\", "/") + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def titulo(texto):
    print(f"\n== {texto} ==")


def tabla(filas, columnas):
    """Imprime filas (lista de tuplas) con encabezados alineados."""
    filas = [tuple(str(v) for v in f) for f in filas]
    anchos = [max(len(c), *(len(f[i]) for f in filas)) if filas else len(c)
              for i, c in enumerate(columnas)]
    print("  " + "  ".join(c.ljust(a) for c, a in zip(columnas, anchos)))
    for f in filas:
        print("  " + "  ".join(v.ljust(a) for v, a in zip(f, anchos)))


def conteo_por_estado(conn, tabla_sql):
    return [(f["estado"], f["total"]) for f in conn.execute(
        f"SELECT estado, COUNT(*) AS total FROM {tabla_sql} GROUP BY estado ORDER BY estado")]


def verificar(descripcion, filas):
    """Una consulta de duplicados o inconsistencias: debe devolver 0 filas."""
    if filas:
        problemas.append(descripcion)
        print(f"  [X] {descripcion}: {len(filas)} caso(s)")
        for f in filas:
            print("    ", tuple(f))
    else:
        print(f"  [OK] {descripcion}: ninguna (correcto)")


def main():
    orders = abrir(ORDERS_DB)
    payments = abrir(PAYMENTS_DB)

    titulo("Totales")
    total_pedidos = orders.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
    total_reservas = orders.execute("SELECT COUNT(*) FROM reservas").fetchone()[0]
    total_pagos = payments.execute("SELECT COUNT(*) FROM pagos").fetchone()[0]
    tabla([("pedidos", total_pedidos), ("reservas", total_reservas), ("pagos", total_pagos)],
          ("tabla", "total"))

    titulo("Pedidos por estado")
    tabla(conteo_por_estado(orders, "pedidos"), ("estado", "total"))
    titulo("Reservas por estado")
    tabla(conteo_por_estado(orders, "reservas"), ("estado", "total"))
    titulo("Pagos por estado (Payment Mock)")
    tabla(conteo_por_estado(payments, "pagos"), ("estado", "total"))

    titulo("Stock actual")
    tabla([(f["id"], f["nombre"], f["stock"]) for f in orders.execute(
        "SELECT id, nombre, stock FROM productos ORDER BY id")], ("id", "producto", "stock"))
    negativos = orders.execute("SELECT id, stock FROM productos WHERE stock < 0").fetchall()
    verificar("productos con stock negativo", negativos)

    titulo("Claves repetidas (debe salir vacío)")
    verificar("Idempotency-Key repetidas en pedidos", orders.execute(
        "SELECT idempotency_key, COUNT(*) AS veces FROM pedidos "
        "GROUP BY idempotency_key HAVING COUNT(*) > 1").fetchall())
    verificar("payment_key repetidas en pedidos", orders.execute(
        "SELECT payment_key, COUNT(*) AS veces FROM pedidos WHERE payment_key IS NOT NULL "
        "GROUP BY payment_key HAVING COUNT(*) > 1").fetchall())
    verificar("payment_key repetidas en pagos", payments.execute(
        "SELECT payment_key, COUNT(*) AS veces FROM pagos "
        "GROUP BY payment_key HAVING COUNT(*) > 1").fetchall())

    titulo("Cruce pedido - pago por payment_key")
    cobros = {f["payment_key"]: f["veces"] for f in payments.execute(
        "SELECT payment_key, COUNT(*) AS veces FROM pagos GROUP BY payment_key")}
    pedidos = orders.execute(
        "SELECT id, idempotency_key, payment_key, estado FROM pedidos ORDER BY id").fetchall()
    cruce = [(p["id"], p["estado"], p["payment_key"] or "-",
              cobros.get(p["payment_key"], 0) if p["payment_key"] else "-") for p in pedidos]
    tabla(cruce, ("pedido", "estado", "payment_key", "pagos"))
    print()
    # Un pedido con cobro tiene exactamente 1 pago. Sin cobro solo puede estar en
    # SIN_STOCK (nunca llegó al mock) o en un estado sin resolver (PENDIENTE_PAGO).
    verificar("pedidos con más de un pago", [
        (p["id"], p["payment_key"], cobros[p["payment_key"]]) for p in pedidos
        if p["payment_key"] and cobros.get(p["payment_key"], 0) > 1])
    verificar("pedidos PAGADO o RECHAZADO sin pago en el mock", [
        (p["id"], p["estado"], p["payment_key"]) for p in pedidos
        if p["estado"] in ("PAGADO", "RECHAZADO") and cobros.get(p["payment_key"], 0) == 0])
    claves_pedidos = {p["payment_key"] for p in pedidos if p["payment_key"]}
    verificar("pagos sin pedido (huérfanos)", [
        (clave,) for clave in cobros if clave not in claves_pedidos])
    verificar("pedidos sin resolver (PENDIENTE_PAGO o PAGO_INCIERTO)", [
        (p["id"], p["estado"], p["payment_key"]) for p in pedidos
        if p["estado"] in ("PENDIENTE_PAGO", "PAGO_INCIERTO")])

    titulo("Coherencia pedido - reserva")
    verificar("pedidos cuyo estado no coincide con su reserva", orders.execute(
        "SELECT p.id, p.estado, r.estado AS reserva FROM pedidos p "
        "LEFT JOIN reservas r ON r.pedido_id = p.id "
        "WHERE NOT ((p.estado = 'PAGADO' AND r.estado = 'CONFIRMADA') "
        "OR (p.estado = 'RECHAZADO' AND r.estado = 'LIBERADA') "
        "OR (p.estado = 'SIN_STOCK' AND r.id IS NULL) "
        "OR (p.estado IN ('PENDIENTE_PAGO', 'PAGO_INCIERTO') AND r.estado = 'RESERVADA'))"
    ).fetchall())

    print()
    if problemas:
        print(f"RESULTADO: revisar ({len(problemas)} punto(s) con problemas)")
        return 1
    print("RESULTADO: correcto. Cada clave produjo como máximo un pedido, una reserva y un pago.")
    return 0


if __name__ == "__main__":
    # En una consola con otra codificación, un carácter raro no debe romper el informe.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
