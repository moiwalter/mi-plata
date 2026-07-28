#!/usr/bin/env python3
"""Genera un dataset SINTÉTICO completo con la forma REAL de la API de Wallbit.

Por qué existe este archivo:

El demo se escribía a mano — se armaba el JSON de salida directamente, sin pasar por el
motor. Eso es una segunda implementación, y las segundas implementaciones se
desincronizan en silencio: el motor real apartaba el colchón antes de repartir la plata
entre los días y el demo no, así que la página pública enseñaba un número diario hasta
50% más alto que el del producto de verdad.

Ahora el demo NO se escribe: se COCINA. Este módulo inventa las respuestas crudas de la
API (`wallbit-snapshot.json`) más la configuración del usuario, y el motor de siempre las
procesa. Si el motor cambia, el demo cambia con él. No puede volver a mentir.

Todo lo de acá es inventado: personas, comercios, montos y direcciones.

Las fechas se anclan a HOY: una demo pública fechada meses atrás parece un proyecto
abandonado. La semilla es fija, así que la historia —comercios, montos, el orden de los
días— es siempre la misma; entre una regeneración y otra sólo se corren las fechas.

  from importlib import import_module
  import_module("demo-fuente").generar("/tmp/loquesea")
"""
import json, os, random
from datetime import date, datetime, timedelta, timezone

# ── anclas ────────────────────────────────────────────────────────────────────
# El demo se ancla a HOY, no a una fecha fija.
#
# Estuvo congelado en marzo para que el archivo no cambiara nunca y el historial de git
# quedara limpio. Eso optimizaba para el repo y no para quien lo mira: una demo con fechas
# de hace meses parece un proyecto abandonado, y encima daba a entender que te estaba
# pidiendo datos viejos. Se prefiere el diff en un archivo generado antes que eso.
#
# La SEMILLA sí es fija, así que los comercios, los montos y la historia son siempre los
# mismos: entre una regeneración y otra sólo se corren las fechas.
_HOY = date.today() - timedelta(days=0)
# El ciclo arranca 11 días antes de hoy: la historia se cuenta a mitad de camino, que es
# donde el tablero tiene algo que decir (ya hay gasto acumulado y todavía queda mes).
# El día de pago se limita a 28 para que exista en cualquier mes, febrero incluido.
_ANCLA = _HOY - timedelta(days=11)
PAYDAY = _ANCLA.day if _ANCLA.day <= 28 else 28
HOY = _HOY.isoformat()      # el motor lo lee por MI_PLATA_HOY
FX = 7.0                    # USD→BOB de este país inventado
SEED = 20260312             # fija: misma historia, sólo cambian las fechas
UTC = timezone.utc
BOL = timezone(timedelta(hours=-4))

# ── gente y comercios inventados ──────────────────────────────────────────────
YO = {"id": 10001, "firstname": "Ana", "lastname": "Rojas", "alias": "ana.rojas"}
OTROS = [
    {"id": 20101, "firstname": "María Elena", "lastname": "Quispe", "alias": "mquispe"},
    {"id": 20102, "firstname": "Juan Carlos", "lastname": "Flores", "alias": "jcflores"},
    {"id": 20103, "firstname": "Rosa", "lastname": "Choque", "alias": "rchoque"},
]
BANCOS = ["Banco Union", "Banco Economico", "Banco Sol", "Banco Ganadero", "YAPE", "Banco Bisa"]

# comercio, banco, mínimo Bs, máximo Bs — el "external_address" real llega como
# "COMERCIO - BANCO", así que se arma igual para que el limpiador de nombres trabaje.
COMERCIOS_QR = [
    ("SUPERMERCADO CENTRAL S.A.", "Banco Economico", 45, 190),
    ("MINIMARKET LA ESQUINA",     "Banco Mercantil", 15, 70),
    ("PANADERIA SAN JORGE",       "Banco Union",     10, 45),
    ("TAXI CENTRO",               "",                20, 60),
    ("COMBUSTIBLE SURTIDOR 12",   "Banco Bisa",      80, 180),
    ("FARMACIA BOLIVIA",          "Banco Ganadero",  25, 120),
    ("RESTAURANTE EL PATIO",      "Banco Sol",       55, 165),
    ("CAFE DE LA PLAZA",          "YAPE",            18, 55),
    ("LAVANDERIA EXPRESS",        "Banco Bisa",      25, 60),
]
# gastos fijos: el motor los reconoce por `fijos_match` (INMOBILIARIA, GIMNASIO)
FIJOS_QR = [
    ("INMOBILIARIA ANDINA SRL - Banco Union", 2000.0, 3),   # alquiler, día 3
    ("GIMNASIO OLIMPO - Banco Sol",            400.0, 5),   # gimnasio, día 5
]
# CARD_SPENT liquida en USD (suscripciones)
SUBS = [("APPLE.COM/BILL", 2.99), ("SPOTIFY P4X2N9", 6.49), ("NETFLIX.COM", 8.99),
        ("CANVA* PRO", 12.99), ("GITHUB.COM", 4.00)]

# Direcciones a propósito IMPOSIBLES de confundir con una real: mantienen el formato
# (largo y prefijo) para que la app las trate igual, pero se leen como lo que son. Una
# dirección inventada "bonita" podría coincidir con la billetera de alguien, y esto es
# un archivo público.
DIRECCIONES = {
    "exchange": "0x00000000000000000000000000000000DEM0DEM0",
    "usdt_in":  "TDEM0DEM0DEM0DEM0DEM0DEM0DEM0DEM00",
}


def _en(dias):
    """Una fecha a N días de hoy. Los gastos ya decididos y los hitos tienen que caer
    siempre por delante: un cumpleaños en una fecha pasada no demuestra nada."""
    return (date.fromisoformat(HOY) + timedelta(days=dias)).isoformat()


def inicio_ciclo(hoy):
    """Misma regla que el motor: el ciclo arranca el día de pago más reciente."""
    if hoy.day >= PAYDAY:
        return date(hoy.year, hoy.month, PAYDAY)
    m, y = (12, hoy.year - 1) if hoy.month == 1 else (hoy.month - 1, hoy.year)
    return date(y, m, PAYDAY)


def mes_antes(d):
    m, y = (12, d.year - 1) if d.month == 1 else (d.month - 1, d.year)
    return date(y, m, d.day)


def _iso(d, h, m):
    """Sella en UTC como hace Wallbit. Se elige la hora LOCAL y se convierte, para que
    el demo también ejercite la conversión de zona (una compra de las 21:00 no puede
    aparecer al día siguiente)."""
    return datetime(d.year, d.month, d.day, h, m, tzinfo=BOL).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _cur(c):
    return {"code": c, "alias": c}


def _tx(rng, n, typ, **kw):
    """Esqueleto común a TODA transacción de Wallbit (los 15 tipos lo comparten)."""
    base = {
        "uuid": f"demo-{n:04d}",
        "type": typ,
        "external_address": None,
        "source_currency": _cur("USD"),
        "dest_currency": _cur("USD"),
        "source_amount": 0.0,
        "dest_amount": 0.0,
        "liquidation_order": False,
        "status": "COMPLETED",
        "created_at": "",
        "comment": None,
        "source_user": YO,
    }
    base.update(kw)
    return base


def transacciones():
    """Los 15 tipos que la API devuelve de verdad, en proporciones parecidas a las reales:
    el QR domina, el cashback es ruido de fondo, la tarjeta paga las suscripciones."""
    rng = random.Random(SEED)
    hoy = date.fromisoformat(HOY)
    ini = inicio_ciclo(hoy)           # ciclo actual, calculado igual que en el motor
    ini_prev = mes_antes(ini)         # ciclo anterior (alimenta la curva de comparación)
    # Todo lo de abajo se ubica por DÍA DEL CICLO, no por fecha absoluta: así la historia
    # es siempre la misma y sólo se corre en el calendario.
    D = lambda n: ini + timedelta(days=n)          # día n del ciclo actual
    P = lambda n: ini_prev + timedelta(days=n)     # día n del ciclo anterior
    txs, n = [], 0

    def add(typ, **kw):
        nonlocal n
        n += 1
        txs.append(_tx(rng, n, typ, **kw))

    # ── sueldo: un DEPOSIT al inicio de cada ciclo ────────────────────────────
    for d in (ini_prev, ini):
        add("DEPOSIT", external_address="NOMINA MENSUAL",
            source_currency=_cur("USD"), dest_currency=_cur("USD"),
            source_amount=2000.0, dest_amount=2000.0, created_at=_iso(d, 9, 5))

    # ── gasto diario en QR (el grueso) ───────────────────────────────────────
    for arranque, fin in ((ini_prev, ini), (ini, hoy + timedelta(days=1))):
        d = arranque
        while d < fin:
            for _ in range(rng.choice([1, 2, 2, 3])):
                com, banco, lo, hi = rng.choice(COMERCIOS_QR)
                bs = float(rng.randrange(lo, hi, 5))
                add("PAY_QR",
                    external_address=f"{com} - {banco}" if banco else com,
                    comment=f"{com} - {banco}" if banco else com,
                    source_currency=_cur("USD"), dest_currency=_cur("BOB"),
                    source_amount=round(bs / FX, 2), dest_amount=bs,
                    created_at=_iso(d, rng.randrange(8, 23), rng.randrange(0, 59)))
            d += timedelta(days=1)

    # ── gastos fijos: mismos QR, pero el motor los reconoce por fijos_match ──
    for arranque in (ini_prev, ini):
        for etiqueta, bs, dia in FIJOS_QR:
            add("PAY_QR", external_address=etiqueta, comment=etiqueta,
                source_currency=_cur("USD"), dest_currency=_cur("BOB"),
                source_amount=round(bs / FX, 2), dest_amount=bs,
                created_at=_iso(arranque + timedelta(days=dia - 1), 10, 30))

    # ── suscripciones con tarjeta: liquidan en USD, no en moneda local ───────
    for arranque in (ini_prev, ini):
        for etiqueta, usd in SUBS:
            dia = arranque + timedelta(days=rng.randrange(1, 11))
            if dia > hoy:
                continue
            add("CARD_SPENT", external_address=etiqueta,
                source_currency=_cur("USD"), dest_currency=_cur("USD"),
                source_amount=usd, dest_amount=usd,
                created_at=_iso(dia, rng.randrange(3, 22), rng.randrange(0, 59)))

    # ── cashback: el tipo MÁS frecuente de la API y el motor lo ignora a propósito ──
    d = ini_prev
    while d <= hoy:
        add("CASHBACK_ACCUMULATED",
            source_currency=_cur("USD"), dest_currency=_cur("USD"),
            source_amount=round(rng.uniform(0.02, 0.35), 2),
            dest_amount=round(rng.uniform(0.02, 0.35), 2),
            created_at=_iso(d, 23, 55))
        d += timedelta(days=1)

    # ── retiros al banco local: la plata sale de Wallbit y la API pierde el rastro.
    #    Sin etiquetar caen en la cola "Por identificar" — la función principal de la app.
    for dia, usd in ((P(13), 200.0), (D(3), 150.0), (D(11), 300.0)):
        add("WITHDRAWAL_LOCAL",
            source_currency=_cur("USD"), dest_currency=_cur("BOB"),
            source_amount=usd, dest_amount=round(usd * FX, 2),
            fee={"fee_amount": 1.5, "fee_currency": "USD"},
            payment_method={"beneficiary_name": "Ana Rojas", "bank_name": "Banco Union",
                            "last_4": None, "routing_number": None, "iban": None,
                            "account_type": "CHECKING", "country": "BO"},
            created_at=_iso(dia, 19, 42))

    # ── transferencias a otra persona de Wallbit ─────────────────────────────
    for dia, usd, quien in ((P(19), 40.0, OTROS[0]), (D(7), 25.0, OTROS[1])):
        add("USER_TRANSFER", dest_user=quien,
            source_currency=_cur("USD"), dest_currency=_cur("USD"),
            source_amount=usd, dest_amount=usd, created_at=_iso(dia, 15, 10))

    # ── cripto: entrada y salida on-chain ────────────────────────────────────
    add("BLOCKCHAIN_DEPOSIT", external_address=DIRECCIONES["usdt_in"],
        source_currency=_cur("USDT"), dest_currency=_cur("USD"),
        source_amount=300.0, dest_amount=300.0, created_at=_iso(P(5), 11, 0))
    add("BLOCKCHAIN_WITHDRAWAL", external_address=DIRECCIONES["exchange"],
        source_currency=_cur("USD"), dest_currency=_cur("USDT"),
        source_amount=200.0, dest_amount=198.5,
        fee={"fee_amount": 1.5, "fee_currency": "USD"},
        wallet={"address": DIRECCIONES["exchange"], "network": "Tron (TRC20)"},
        created_at=_iso(D(5), 16, 20))

    # ── inversión: entra y sale del índice ───────────────────────────────────
    add("INVESTMENT_DEPOSIT", source_currency=_cur("USD"), dest_currency=_cur("SPY"),
        source_amount=200.0, dest_amount=0.36,
        fee={"fee_amount": 0.0, "fee_currency": "USD"}, created_at=_iso(P(2), 14, 0))
    add("INVESTMENT_WITHDRAWAL", source_currency=_cur("SPY"), dest_currency=_cur("USD"),
        source_amount=0.05, dest_amount=28.0,
        fee={"fee_amount": 0.0, "fee_currency": "USD"}, created_at=_iso(D(8), 14, 0))
    add("CASHBACK_TRADE", source_currency=_cur("USD"), dest_currency=_cur("SPY"),
        trade_info={"direction": "BUY", "symbol": "SPY", "order_type": "MARKET",
                    "share_price": 556.12, "settlement_date": D(9).isoformat()},
        source_amount=1.20, dest_amount=0.002, created_at=_iso(D(9), 14, 30))

    # ── ruido conocido: un hold de tarjeta y un depósito local ───────────────
    add("CARD_HOLD", external_address="HOTEL RESERVA", source_amount=50.0, dest_amount=50.0,
        status="PENDING", created_at=_iso(D(10), 12, 0))
    add("DEPOSIT_LOCAL", external_address="RECARGA DESDE BANCO LOCAL",
        source_currency=_cur("BOB"), dest_currency=_cur("USD"),
        source_amount=700.0, dest_amount=100.0, created_at=_iso(P(23), 10, 0))

    # ── ajuste y rendimiento ─────────────────────────────────────────────────
    add("ADJUSTMENT_IN", external_address="AJUSTE DE SOPORTE",
        source_amount=12.0, dest_amount=12.0, created_at=_iso(P(26), 17, 0))
    add("EARN", external_address="RENDIMIENTO CUENTA",
        source_amount=3.40, dest_amount=3.40, created_at=_iso(D(0), 0, 30))

    # ── estados que no son COMPLETED: el motor los tiene que descartar ───────
    add("PAY_QR", external_address="RESTAURANTE EL PATIO - Banco Sol",
        comment="RESTAURANTE EL PATIO - Banco Sol",
        source_currency=_cur("USD"), dest_currency=_cur("BOB"),
        source_amount=17.14, dest_amount=120.0, status="FAILED",
        created_at=_iso(D(6), 20, 15))
    add("PAY_QR", external_address="TAXI CENTRO", comment="TAXI CENTRO",
        source_currency=_cur("USD"), dest_currency=_cur("BOB"),
        source_amount=5.71, dest_amount=40.0, status="REVERSED",
        created_at=_iso(D(4), 22, 40))

    txs.sort(key=lambda t: t["created_at"])
    for i, t in enumerate(txs, 1):
        t["uuid"] = f"demo-{i:04d}"
    return txs


def snapshot():
    txs = transacciones()
    return {
        "synced_at": f"{HOY}T13:00:00+00:00",
        "errors": [],
        "checking": [{"currency": "USD", "balance": 2200.0}],
        "usd_liquid": 2200.0,
        "stocks": [{"symbol": "SPY", "shares": 1.618, "price": 556.12, "value_usd": 900.0}],
        "stocks_value_usd": 900.0,
        "fx_usd_bob": FX,
        "fx_updated_at": f"{HOY}T12:40:00+00:00",
        "transactions": txs,
        "tx_count": len(txs),
        "tx_window": {"from": (date.fromisoformat(HOY) - timedelta(days=40)).isoformat(), "to": HOY},
    }


def plan():
    return {
        "_meta": "Plan de ejemplo — persona inventada.",
        "updated": HOY, "income_monthly_usd": 2000, "payday": PAYDAY,
        "debt": {"total_original_usd": 1500, "interest": "0%", "creditors": [
            {"name": "Préstamo familiar", "amount": 1000, "paid": False},
            {"name": "Tarjeta", "amount": 500, "paid": True}]},
        "colchon": {"meta_usd": 6000, "rail": "Cuenta de ahorro en USD"},
        "dca": {"split": {"btc": 0.5, "index": 0.5}, "btc_rail": "Exchange",
                "index_rail": "Wallbit (SPY)"},
        "plan_by_payday": [{"month": _en(31)[:7], "colchon": 400, "deuda": 300, "dca": 200}],
        "milestones": {"debt_zero": _en(90), "colchon_done": _en(240),
                       "dca_full": _en(300)},
        "budget": {
            "_note": "DOS BALDES: los fijos caen en bloque y no cuentan al ritmo diario.",
            "techo_total_bs": 8000, "techo_diario_bs": 133,
            "fijos_total_bs": 4000, "variables_total_bs": 4000,
            "fijos_bs": {"Alquiler": 2000, "Servicios": 600, "Internet": 400,
                         "Suscripciones": 600, "Gimnasio": 400},
            "fijos_match": {"INMOBILIARIA": "Alquiler", "GIMNASIO": "Gimnasio"},
            "variables_bs": {"Comida": 2200, "Transporte": 800, "Salidas": 600, "Otros": 400},
            "gasto_real_medido_bs_mes": 9200,
            "gasto_real_neto_onetimes_bs_mes": 8600,
            # TERCER BALDE: lo ya decidido se aparta antes de repartir el resto entre los días.
            "excepcionales": {
                "_note": "Gastos con fecha y monto que NO cuentan contra el número diario.",
                "items": [
                    {"nombre": "Cumpleaños", "fecha": _en(6), "usd": 80,
                     "nota": "Cena con amigos. Monto decidido de antemano."},
                    {"nombre": "Viaje de fin de mes", "fecha": _en(15), "usd": 250,
                     "dias_fuera": 4, "nota": "Pasaje + alojamiento, 4 días fuera."}],
                "total_usd": 330},
            "restriccion_real": {"fijos_pendientes_bs": 0}},
    }


def tx_labels():
    return {
        "_meta": "Etiquetas de ejemplo — se guardan por uuid y no se vuelven a preguntar.",
        "updated": HOY,
        # Los botones de la cola salen de acá. Sin esto el demo enseñaba la cola VACÍA de
        # opciones, o sea escondía justo la función principal de la app. Es la misma
        # semilla que trae `ejemplos/tx-labels.example.json`: lo que ve en el demo es lo
        # que va a tener el día uno.
        "_categories": {
            "_note": "Semilla para arrancar. Bórrala, renómbrala y agrégale lo tuyo.",
            "Comida": {"fijo": False, "desc": "Super, mercado, restaurantes, delivery"},
            "Transporte": {"fijo": False, "desc": "Taxi, combustible, pasajes"},
            "Salidas": {"fijo": False, "desc": "Bar, cine, salida nocturna"},
            "Salud": {"fijo": False, "desc": "Farmacia, consultas, gimnasio"},
            "Hogar": {"fijo": False, "desc": "Cosas de casa, limpieza, reparaciones"},
            "Ropa/Shopping": {"fijo": False, "desc": "Ropa y objetos personales"},
            "Servicios": {"fijo": True, "desc": "Luz, agua, internet — caen en bloque"},
            "Suscripciones": {"fijo": True, "desc": "Apps y servicios mensuales"},
            "Alquiler": {"fijo": True, "desc": "Renta de vivienda o espacio de trabajo"},
            "Otros": {"fijo": False, "desc": "Lo que no entra en ninguna"},
            "Deuda": {"fijo": False, "desc": "Pago de deuda — no es consumo"},
            "Colchón": {"fijo": False, "desc": "Aporte al fondo de emergencia"},
            "DCA": {"fijo": False, "desc": "Lo que inviertes"},
        },
        "exclude_from_techo": ["Deuda", "Colchón", "DCA"],
        "merchant_rules": [
            {"cat": "Comida", "keys": ["SUPERMERCADO", "MINIMARKET", "PANADERIA", "CAFE"]},
            {"cat": "Transporte", "keys": ["TAXI", "COMBUSTIBLE"]},
            {"cat": "Salidas", "keys": ["RESTAURANTE"]},
            {"cat": "Salud", "keys": ["FARMACIA", "GIMNASIO"]},
            {"cat": "Suscripciones", "keys": ["APPLE.COM", "SPOTIFY", "NETFLIX", "CANVA", "GITHUB"]},
            {"cat": "Otros", "keys": ["LAVANDERIA"]},
        ],
        "default_qr_rule": {"enabled": True, "max_bs": 200, "types": ["PAY_QR"], "cat": "Comida"},
        "labels": {},
        # La libreta de direcciones: sin esto, un envío on-chain no se sabe si es
        # inversión o consumo, y una entrada no se sabe de quién viene.
        # Las claves son EXACTAS: `name` y `kind` (inversion | consumo | entrante).
        "addresses": {
            DIRECCIONES["exchange"]: {"name": "Mi exchange", "kind": "inversion"},
            DIRECCIONES["usdt_in"]: {"name": "Cliente del exterior", "kind": "entrante"},
        },
    }


def data():
    """El libro de aportes: de acá salen la deuda restante y el colchón acumulado."""
    return {
        "expenses": [], "ingresos": [], "checks": {},
        "aportes": [
            {"fecha": _en(-41), "deuda": 250, "colchon": 400, "dca": 200},
            {"fecha": _en(-11), "deuda": 250, "colchon": 400, "dca": 200},
        ],
    }


def manual_balances():
    return {
        "_meta": "Cuentas que la API de Wallbit no ve.",
        "updated": HOY,
        "accounts": [
            {"name": "Banco local", "amount": 3150.0, "currency": "BOB", "kind": "liquido",
             "note": "Lo que se retiró de Wallbit."},
            {"name": "Exchange (cripto)", "amount": 1500.0, "currency": "USD", "kind": "invertido",
             "note": "Costo, no precio vivo."},
        ],
    }


def generar(destino):
    """Escribe el dataset sintético completo en `destino`, listo para que lo coma el motor."""
    os.makedirs(destino, exist_ok=True)
    for nombre, contenido in (("wallbit-snapshot.json", snapshot()),
                              ("plan.json", plan()),
                              ("tx-labels.json", tx_labels()),
                              ("data.json", data()),
                              ("manual-balances.json", manual_balances())):
        with open(os.path.join(destino, nombre), "w", encoding="utf-8") as f:
            json.dump(contenido, f, ensure_ascii=False, indent=1)
    return destino


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mi-plata-demo"
    generar(d)
    s = snapshot()
    from collections import Counter
    c = Counter(t["type"] for t in s["transactions"])
    print(f"{d}  ·  {len(s['transactions'])} transacciones sintéticas, {len(c)} tipos")
    for k, v in c.most_common():
        print(f"    {k:24} {v}")
