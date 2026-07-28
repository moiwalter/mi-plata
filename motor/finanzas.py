#!/usr/bin/env python3
"""Motor determinista de finanzas personales.

Une dos mundos:
  - data.json           (manual: efectivo, cuentas que la API no ve, aportes)
  - wallbit-snapshot.json (live API: checking USD, índice/ETF, tasa, transacciones)
y produce un brief ACCIONABLE: qué hacer, no un tablero para mirar.

La matemática vive AQUÍ, no en la cabeza del agente. Un número calculado en una respuesta
no se puede verificar ni repetir; uno que sale del motor, sí.

Uso:
  python3 finanzas.py             # brief unificado
  python3 finanzas.py --import    # propone gastos desde transacciones Wallbit (no escribe)
  python3 finanzas.py --json      # estado unificado crudo
"""
import json, os, sys, subprocess
from datetime import date, datetime, timedelta, timezone

BOLIVIA = timezone(timedelta(hours=-4))


def fecha_local(t):
    """Fecha de la transacción en tu zona horaria, NO en UTC.

    Wallbit sella todo en UTC. Si vives al oeste de Greenwich y gastas de noche, cualquier
    movimiento posterior a la tarde cae al día siguiente — y lo del último día del ciclo se
    va entero al ciclo que viene, que es el error caro: dos meses mal cortados.

    Convertir SIEMPRE antes de comparar fechas."""
    ca = t.get("created_at") or ""
    try:
        return datetime.fromisoformat(ca.replace("Z", "+00:00")).astimezone(BOLIVIA).date().isoformat()
    except Exception:
        return ca[:10]

# Los datos y la configuración viven en la RAÍZ del repo; el código, en motor/.
# MI_PLATA_DIR redirige esa raíz: así el generador del demo puede correr ESTE MISMO motor
# contra datos sintéticos en una carpeta temporal, en vez de mantener una segunda
# implementación a mano que se desincroniza en silencio (fue justo lo que pasó con el colchón).
DIR = os.environ.get("MI_PLATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))


def hoy():
    """El "hoy" del motor. MI_PLATA_HOY lo congela — sólo lo usa el generador del demo,
    para que demo.json salga idéntico cada vez en vez de cambiar todos los días y
    ensuciar el historial de git. En uso normal la variable no existe y manda el reloj.
    TIENE que usarse en todos lados: si el selftest mira el reloj real mientras el resto
    mira la fecha congelada, inventa fallos ("snapshot viejo", "balances sin actualizar")
    que no existen."""
    v = os.environ.get("MI_PLATA_HOY")
    return date.fromisoformat(v) if v else date.today()


def ahora():
    """Igual que hoy(), pero con hora — para medir antigüedad del snapshot."""
    v = os.environ.get("MI_PLATA_HOY")
    return datetime.fromisoformat(v + "T13:00:00+00:00") if v else None


def sync():
    """Refresca el snapshot de Wallbit (cubre el ciclo completo: 35 días)."""
    try:
        subprocess.run([sys.executable, os.path.join(AQUI, "wallbit-sync.py"), "--days", "35"],
                       check=True, cwd=DIR)
    except Exception as e:
        print(f"  ⚠ sync falló ({e}); uso el snapshot existente.\n")


def load(name, default):
    p = os.path.join(DIR, name)
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def cycle_start(today, payday):
    """Inicio del ciclo actual anclado al día de pago."""
    if today.day >= payday:
        return date(today.year, today.month, payday)
    m, y = today.month - 1, today.year
    if m == 0:
        m, y = 12, y - 1
    return date(y, m, payday)


def cur(x):
    return x.get("code") if isinstance(x, dict) else x


# --- clasificación de transacciones Wallbit ---
EXPENSE_TYPES = {"PAY_QR", "CARD_SPENT"}
SKIP_TYPES = {"CASHBACK_ACCUMULATED"}
# Ingreso REAL (plata nueva que entra): sueldo, pagos Wallbit, transferencias entrantes, yield.
INCOME_TYPES = {"DEPOSIT", "ADJUSTMENT_IN", "EARN"}
# Movimientos internos que NO son ingreso (mover plata propia): a inversión, cripto, top-up local.
INTERNAL_TYPES = {"INVESTMENT_DEPOSIT", "BLOCKCHAIN_DEPOSIT", "DEPOSIT_LOCAL"}
# Salidas que NO son consumo por sí solas: se resuelven por libreta de direcciones / dirección del transfer.
ROUTED_TYPES = {"BLOCKCHAIN_WITHDRAWAL", "USER_TRANSFER", "WITHDRAWAL_LOCAL"}
# Ruido conocido e inocuo (no mueve saldo o ya está cubierto por otro registro).
NOISE_TYPES = {"CASHBACK_TRADE", "CARD_HOLD", "INVESTMENT_WITHDRAWAL", "LIQUIDATION"}
# TODO tipo que Wallbit pueda devolver tiene que estar en alguno de estos conjuntos.
# Si aparece uno nuevo, el selftest FALLA y avisa. Así se descubrieron transfers salientes
# y envíos on-chain que llevaban semanas sin contarse: plata que salía sin dejar rastro.
KNOWN_TYPES = (EXPENSE_TYPES | SKIP_TYPES | INCOME_TYPES | INTERNAL_TYPES
               | ROUTED_TYPES | NOISE_TYPES)


def owner_id(txs):
    """El dueño de la cuenta = quien más aparece como source_user en los gastos (PAY_QR/CARD)."""
    from collections import Counter
    c = Counter()
    for t in txs:
        if t.get("type") in EXPENSE_TYPES:
            uid = (t.get("source_user") or {}).get("id")
            if uid is not None:
                c[uid] += 1
    return c.most_common(1)[0][0] if c else None


def classify(txs, since, fijos_match=None, fx=None, addresses=None):
    """Devuelve (gastos_propuestos_bs, conversiones_usd_a_bs, ingresos).
    fijos_match: {patrón_en_comment: categoría_fija} → marca el gasto como fijo (ej. alquiler cowork).
    Ingreso = plata NUEVA (sueldo, pagos Wallbit, transfers entrantes, yield); los movimientos
    internos (a inversión, cripto, top-up) se excluyen para no inflar el ingreso del ciclo."""
    me = owner_id(txs)
    gastos, conv, ingresos = [], [], []
    desconocidos = []          # tipos que el motor NO sabe clasificar -> los grita el selftest
    entradas_sin_libreta = []  # depósitos on-chain de direcciones no identificadas
    for t in txs:
        if t.get("status") != "COMPLETED":
            continue
        ca = fecha_local(t)
        if ca and ca < since:
            continue
        typ = t.get("type")
        if typ in EXPENSE_TYPES:
            dc = cur(t.get("dest_currency"))
            # CARD_SPENT liquida en USD: es como llegan casi todas las suscripciones. Antes se guardaba
            # el monto USD como si fueran moneda local → una suscripción de $80 entraba
            # como 80 en vez de ~920. El error escala con el tipo de cambio.
            amt = (float(t.get("dest_amount") or 0) if dc == "BOB"
                   else float(t.get("source_amount") or 0) * (fx or 11.5))
            nota = (t.get("external_address") or t.get("comment") or typ)
            fijo = next((cat for pat, cat in (fijos_match or {}).items()
                         if pat.upper() in (nota or "").upper()), None)
            gastos.append({
                "fecha": ca, "monto_bs": round(amt, 2),
                "nota": nota, "fijo": fijo,
                "type": typ, "uuid": t.get("uuid"),
            })
        elif typ == "WITHDRAWAL_LOCAL":
            conv.append({"fecha": ca, "usd": float(t.get("source_amount") or 0),
                         "bs": float(t.get("dest_amount") or 0), "uuid": t.get("uuid")})
        elif typ == "BLOCKCHAIN_DEPOSIT":
            # Entrada on-chain: no es gasto, pero SÍ tiene que estar identificada.
            # Antes sólo se vigilaban las direcciones salientes.
            if not (addresses or {}).get(t.get("external_address") or ""):
                entradas_sin_libreta.append({"fecha": ca, "usd": float(t.get("dest_amount") or 0),
                                             "addr": t.get("external_address") or "?"})
            continue
        elif typ in SKIP_TYPES or typ in INTERNAL_TYPES:
            continue
        elif typ in INCOME_TYPES:
            src = t.get("external_address") or (
                ((t.get("source_user") or {}).get("firstname", "") + " " +
                 (t.get("source_user") or {}).get("lastname", "")).strip()) or typ
            ingresos.append({"fecha": ca, "type": typ, "fuente": src,
                             "monto": round(float(t.get("dest_amount") or 0), 2),
                             "cur": cur(t.get("dest_currency")), "uuid": t.get("uuid")})
        elif typ == "BLOCKCHAIN_WITHDRAWAL":
            # Envío on-chain. NO todos son iguales: a tu exchange = inversión (no gasto);
            # a otro lado puede ser consumo real. La libreta vive en tx-labels.json.
            addr = t.get("external_address") or ""
            info = (addresses or {}).get(addr) or {}
            kind = info.get("kind", "desconocido")
            if kind == "inversion":
                continue
            usd_amt = float(t.get("source_amount") or 0)
            gastos.append({
                "fecha": ca, "monto_bs": round(usd_amt * (fx or 11.5), 2),
                "nota": f"on-chain → {info.get('name') or addr[:16]}",
                "fijo": None, "type": typ, "uuid": t.get("uuid"),
                # La categoría la declara la libreta, no el motor. Antes acá había un
                # nombre fijo que salía de la instalación de una persona concreta: a
                # cualquier otra le asignaba una categoría que no existe en su taxonomía.
                "cat": info.get("cat"),
                "addr_desconocida": kind == "desconocido",
                "alerta": bool(info.get("alerta_si_sale")),
            })
        elif typ == "USER_TRANSFER":
            # SALIENTE = gasto real. El motor lo ignoraba, así que mandarle plata a alguien
            # por Wallbit no aparecía en el gasto del ciclo: salía y no la contaba nadie.
            if me is not None and (t.get("source_user") or {}).get("id") == me:
                du = t.get("dest_user") or {}
                quien = (du.get("firstname", "") + " " + du.get("lastname", "")).strip() or "usuario Wallbit"
                usd_amt = float(t.get("source_amount") or 0)
                gastos.append({
                    "fecha": ca, "monto_bs": round(usd_amt * (fx or 11.5), 2),
                    "nota": f"transfer → {quien}", "fijo": None,
                    "type": typ, "uuid": t.get("uuid"),
                })
            elif me is not None and (t.get("dest_user") or {}).get("id") == me:
                src = ((t.get("source_user") or {}).get("firstname", "") + " " +
                       (t.get("source_user") or {}).get("lastname", "")).strip() or "transfer"
                ingresos.append({"fecha": ca, "type": typ, "fuente": "de " + src,
                                 "monto": round(float(t.get("dest_amount") or 0), 2),
                                 "cur": cur(t.get("dest_currency")), "uuid": t.get("uuid")})
        elif typ not in KNOWN_TYPES:
            desconocidos.append({"fecha": ca, "type": typ, "uuid": t.get("uuid"),
                                 "usd": float(t.get("source_amount") or 0)})
    return gastos, conv, ingresos, desconocidos, entradas_sin_libreta


def compute():
    plan = load("plan.json", {})
    # data.json es el libro de aportes (pagos de deuda, colchón, DCA). Si no existe
    # todavía —instalación recién hecha— es un libro vacío, no un error: nadie debería
    # chocar contra una verificación fallida por no haber registrado aún ningún aporte.
    data = load("data.json", {"expenses": [], "aportes": [], "ingresos": [], "checks": {}})
    snap = load("wallbit-snapshot.json", {})
    # MI_PLATA_HOY congela "hoy" — sólo lo usa el generador del demo, para que demo.json
    # salga idéntico cada vez que se regenera en vez de cambiar todos los días y ensuciar
    # el historial de git. En uso normal la variable no existe y manda el reloj.
    today = hoy()
    payday = plan.get("payday", 24)
    cs = cycle_start(today, payday)
    # TASA. La API (/rates) devuelve la tasa de RETIRO — es la que se aplica al sacar
    # dólares a banco local. Pero quien lo usa casi todo lo gasta por QR, y el QR liquida a una
    # tasa MEJOR (~1,5% arriba). Usar la de la API subestima su poder de compra en Bs.
    # Se mide la tasa efectiva de sus propios PAY_QR de los últimos 7 días.
    fx_api = snap.get("fx_usd_bob") or data.get("fx") or 9.93
    def _qr_rates(days):
        return [float(t["dest_amount"]) / float(t["source_amount"])
                for t in snap.get("transactions", [])
                if t.get("type") == "PAY_QR" and cur(t.get("dest_currency")) == "BOB"
                and float(t.get("source_amount") or 0) > 0
                and fecha_local(t) >= (today - timedelta(days=days)).isoformat()]
    # En un mercado paralelo la tasa se mueve rápido —se han visto ~9% en cinco días—: un
    # promedio largo queda
    # viejo en mercado móvil. Se prefieren los últimos 3 días; si no hay, se abre a 7.
    _r = _qr_rates(3) or _qr_rates(7)
    fx_qr = round(sum(_r) / len(_r), 3) if _r else None
    fx = fx_qr or fx_api

    # --- deuda + colchón: del registro de pagos (aportes en data.json), no de flags estáticos ---
    creditors = plan.get("debt", {}).get("creditors", [])
    debt_total = plan.get("debt", {}).get("total_original_usd", 0)
    deuda_paid = sum(float(a.get("deuda", 0) or 0) for a in data.get("aportes", []))
    debt_left = max(debt_total - deuda_paid, 0)
    colchon_current = sum(float(a.get("colchon", 0) or 0) for a in data.get("aportes", []))
    colchon_meta = plan.get("colchon", {}).get("meta_usd", 3000)
    # distribución por acreedor: lo ya pagado cubre a los primeros en orden
    paid_pool = deuda_paid
    debt_dist = []
    for c in creditors:
        covered = min(paid_pool, c["amount"])
        paid_pool -= covered
        left = c["amount"] - covered
        debt_dist.append({"name": c["name"], "amount": c["amount"], "left": left, "paid": left <= 0})

    # --- activos ---
    checking = snap.get("usd_liquid", 0) or 0
    # cuenta de inversión: USD sin invertir + valor de ETFs
    inv_cash = sum(float(s.get("shares", 0)) for s in snap.get("stocks", []) if s.get("symbol") == "USD")
    etf_val = snap.get("stocks_value_usd") or 0
    wallbit_total = checking + inv_cash + etf_val

    # Cuentas manuales que la API no ve (banco local, exchange, efectivo) → manual-balances.json
    mb = load("manual-balances.json", {})
    manual_accounts = []
    manual_usd = 0.0
    for a in mb.get("accounts", []):
        amt = float(a.get("amount", 0) or 0)
        in_usd = amt if a.get("currency") == "USD" else amt / fx
        manual_usd += in_usd
        manual_accounts.append({"name": a.get("name"), "amount": amt,
                                "currency": a.get("currency"), "usd": in_usd, "kind": a.get("kind")})

    assets = wallbit_total + manual_usd
    net = assets - debt_left

    # --- gasto del ciclo (Wallbit auto + manual) ---
    since = cs.isoformat()
    budget = plan.get("budget", {})
    _addrbook = load("tx-labels.json", {}).get("addresses", {})
    gastos_wb, conv, ingresos, desconocidos, entradas_sl = classify(
        snap.get("transactions", []), since,
        budget.get("fijos_match"), fx=fx, addresses=_addrbook)
    addr_sin_libreta = [g for g in gastos_wb if g.get("addr_desconocida")]
    # Direcciones marcadas `alerta_si_sale` en la libreta: destinos a los que se decidió
    # no volver a mandar plata. Aparecen el mismo día, no en el recap de fin de mes —
    # una decisión sólo aguanta si algo avisa cuando se rompe, y avisar tarde no sirve.
    envios_vigilados = [g for g in gastos_wb if g.get("alerta")]
    wb_spend_bs = sum(g["monto_bs"] for g in gastos_wb)
    fijos_items = [g for g in gastos_wb if g.get("fijo")]
    fijos_pagados_bs = sum(g["monto_bs"] for g in fijos_items)
    var_bs = wb_spend_bs - fijos_pagados_bs
    manual = [e for e in data.get("expenses", []) if e.get("fecha", "") >= since]
    manual_bs = sum(float(e.get("monto", 0)) for e in manual)

    # --- etiquetas persistentes por uuid (tx-labels.json): categorización DETERMINÍSTICA ---
    # La API re-baja las txs cada sync sin memoria; la verdad de "qué fue cada gasto" vive aquí.
    tl = load("tx-labels.json", {})
    labels = tl.get("labels", {})
    mrules = tl.get("merchant_rules", [])
    # Regla de default, configurable en tx-labels.json: QR chico a nombre suelto = mercado.
    # Evita re-preguntar por decenas de pagos de 15-60 Bs a caseros. Solo si no hay label ni regla.
    qr = tl.get("default_qr_rule", {"enabled": True, "max_bs": 200, "types": ["PAY_QR"], "cat": "Comida/Super"})
    for g in gastos_wb:
        lab = labels.get(g.get("uuid"))
        if lab:  # el label por uuid SIEMPRE gana
            g["label"] = lab.get("label")
            g["cat"] = lab.get("cat")
        else:  # si no, aplicar reglas por comercio (permanentes, futuros ciclos)
            nota = (g.get("nota") or "").upper()
            for r in mrules:
                if any(k.upper() in nota for k in r.get("keys", [])):
                    g["cat"] = r.get("cat")
                    break
            # fallback: QR chico sin identificar -> mercado por defecto (marcado como auto)
            if not g.get("cat") and qr.get("enabled") \
               and g.get("type") in qr.get("types", []) \
               and g["monto_bs"] < qr.get("max_bs", 200):
                g["cat"] = qr.get("cat", "Comida/Super")
                g["auto_default"] = True
    # Categorías que NO son consumo (pagos de deuda, transferencias a colchón/DCA):
    # se muestran aparte y NO cuentan contra el techo — si no, un pago de $2.000 a Acreedor B
    # dispara el techo del mes y el número deja de significar nada.
    no_consumo_cats = set(tl.get("exclude_from_techo", ["Deuda"]))
    cat_bd, sin_etiqueta_bs, sin_etiqueta_n, no_consumo_bs = {}, 0.0, 0, 0.0
    for g in gastos_wb:
        if g.get("fijo"):
            continue
        c = g.get("cat")
        if not c:
            sin_etiqueta_bs += g["monto_bs"]; sin_etiqueta_n += 1
            c = "Sin etiquetar"
        if c in no_consumo_cats:
            no_consumo_bs += g["monto_bs"]
            continue
        cat_bd[c] = cat_bd.get(c, 0) + g["monto_bs"]
    for e in manual:
        c = e.get("cat") or "Sin etiquetar"
        if c in no_consumo_cats:
            no_consumo_bs += float(e.get("monto", 0))
            continue
        cat_bd[c] = cat_bd.get(c, 0) + float(e.get("monto", 0))
    var_bs -= no_consumo_bs
    # techo de presupuesto + pro-rateo por día del ciclo.
    # Los fijos identificados (ej. alquiler cowork) NO se prorratean — caen una vez;
    # el ritmo se mide sobre el gasto restante contra el techo menos esos fijos.
    techo = budget.get("techo_total_bs", 0)
    day_in_cycle = max((today - cs).days + 1, 1)
    fijos_presup = sum(budget.get("fijos_bs", {}).get(g["fijo"], 0) for g in {g["fijo"]: g for g in fijos_items}.values())
    techo_var = max(techo - fijos_presup, 0)
    # Largo REAL del ciclo (24→24: 28 a 31 días). Antes estaba fijo en 30 y el ritmo
    # salía optimista: repartía entre un día de más, y ese día lo pagaba el final del mes.
    _nm, _ny = (cs.month + 1, cs.year) if cs.month < 12 else (1, cs.year + 1)
    cycle_len = (date(_ny, _nm, min(payday, 28)) - cs).days or 30
    techo_prorate = round(techo_var * day_in_cycle / cycle_len) if techo else 0

    # --- próximo pago: primer día-24 (de este ciclo en adelante) SIN aporte registrado ---
    aporte_dates = {a.get("fecha") for a in data.get("aportes", [])}
    y, m = today.year, today.month
    if today.day > payday:
        m += 1
    next_pay = date(y, m if m <= 12 else m - 12, payday)
    for i in range(24):
        mm = m + i
        yy = y + (mm - 1) // 12
        mmm = (mm - 1) % 12 + 1
        pd = date(yy, mmm, payday)
        if pd.isoformat() not in aporte_dates:
            next_pay = pd
            break
    days_to = (next_pay - today).days
    pm = f"{next_pay.year}-{next_pay.month:02d}"
    plan_row = next((p for p in plan.get("plan_by_payday", []) if p["month"] == pm), None)

    return {
        "today": today.isoformat(), "synced_at": snap.get("synced_at"),
        "fx": fx, "fx_api": fx_api, "fx_qr": fx_qr,
        "fx_src": ("efectiva QR 3d" if fx_qr else ("API /rates" if snap.get("fx_usd_bob") else "stored")),
        "cycle_start": since, "days_to_payday": days_to, "next_pay": next_pay.isoformat(),
        "wallbit": {"checking": checking, "inv_cash": inv_cash, "etf": etf_val, "total": wallbit_total},
        "manual_accounts": manual_accounts, "manual_usd": manual_usd,
        "assets": assets, "debt_left": debt_left, "debt_total": debt_total, "net": net,
        "debt_dist": debt_dist, "colchon_current": colchon_current, "colchon_meta": colchon_meta,
        "creditors": creditors, "dca_split": plan.get("dca", {}).get("split", {"btc": 0.8, "index": 0.2}),
        "spend": {"wallbit_bs": wb_spend_bs, "manual_bs": manual_bs, "total_bs": wb_spend_bs + manual_bs,
                  "wallbit_items": gastos_wb, "conversions": conv, "ingresos": ingresos,
                  "fijos_items": fijos_items, "fijos_pagados_bs": fijos_pagados_bs,
                  "var_bs": var_bs + manual_bs, "techo_var": techo_var, "no_consumo_bs": no_consumo_bs,
                  "techo": techo, "techo_prorate": techo_prorate, "day_in_cycle": day_in_cycle,
                  "cycle_len": cycle_len,
                  "cat_breakdown": cat_bd, "sin_etiqueta_bs": sin_etiqueta_bs,
                  "sin_etiqueta_n": sin_etiqueta_n, "labels_count": len(labels),
                  "tipos_desconocidos": desconocidos, "addr_sin_libreta": addr_sin_libreta,
                  "entradas_sin_libreta": entradas_sl, "envios_vigilados": envios_vigilados},
        "next_plan": plan_row, "milestones": plan.get("milestones", {}),
    }


def usd(n):
    return f"${n:,.0f}"


def brief():
    s = compute()
    print(f"\n  FINANZAS — {s['today']}  ·  TC {s['fx']} ({s['fx_src']})"
          + (f"   [API /rates: {s['fx_api']} = tasa de RETIRO a banco]" if s.get('fx_qr') else "") + "\n")
    print(f"  Patrimonio neto:  {usd(s['net'])}   (activos {usd(s['assets'])} − deuda {usd(s['debt_left'])})")
    w = s["wallbit"]
    print(f"    Wallbit (API):  {usd(w['total'])}  (líquido {usd(w['checking'])} · sin invertir {usd(w['inv_cash'])} · SPY {usd(w['etf'])})")
    for a in s["manual_accounts"]:
        extra = f"{a['amount']:,.0f} {a['currency']} ≈ " if a["currency"] != "USD" else ""
        print(f"    {a['name']+':':<15} {extra}{usd(a['usd'])}")
    print(f"    Deuda 0%:       −{usd(s['debt_left'])} de {usd(s['debt_total'])}")
    sp = s["spend"]
    ing = sp.get("ingresos", [])
    if ing:
        ing_tot = sum(i["monto"] for i in ing if i.get("cur") == "USD")
        print(f"\n  Ingresos este ciclo (Wallbit auto):  {usd(ing_tot)}")
        for i in sorted(ing, key=lambda x: -x["monto"]):
            if i["monto"] < 1:
                continue
            print(f"    · {i['fecha']}  {usd(i['monto']):>8}  {i.get('fuente','')[:34]}")
    print(f"\n  Gasto este ciclo (desde {s['cycle_start']}):  {sp['total_bs']:,.0f} Bs  ·  techo {sp['techo']:,.0f} Bs" if sp.get("techo")
          else f"\n  Gasto este ciclo (desde {s['cycle_start']}):  {sp['total_bs']:,.0f} Bs")
    for g in sp.get("fijos_items", []):
        print(f"    · Fijo {g['fijo']} ({g['fecha']}):     {g['monto_bs']:,.0f} Bs  (presupuestado, no cuenta al ritmo)")
    if sp.get("techo"):
        print(f"    · Variable: {sp['var_bs']:,.0f} Bs  ·  techo variable {sp['techo_var']:,.0f} Bs (proyectado al día {sp['day_in_cycle']}: {sp['techo_prorate']:,.0f})")
    print(f"    · Wallbit (QR/tarjeta auto): {sp['wallbit_bs']:,.0f} Bs ({len(sp['wallbit_items'])} mov)")
    print(f"    · Manual (data.json):        {sp['manual_bs']:,.0f} Bs")
    if sp.get("no_consumo_bs"):
        print(f"    · Deuda/aportes (NO consumo, fuera del techo): {sp['no_consumo_bs']:,.0f} Bs")
    if sp["conversions"]:
        tot = sum(c["bs"] for c in sp["conversions"])
        print(f"    · USD→Bs sacado a local:     {tot:,.0f} Bs (a tu banco o a gasto — Wallbit no ve en qué termina)")
    cb = sp.get("cat_breakdown") or {}
    if cb:
        print(f"\n  Desglose por categoría (variable, {sp.get('labels_count',0)} tx etiquetadas en tx-labels.json):")
        for c, v in sorted(cb.items(), key=lambda x: -x[1]):
            print(f"    · {c:<28} {v:>7,.0f} Bs")
        if sp.get("sin_etiqueta_n"):
            print(f"    ⚠ {sp['sin_etiqueta_n']} tx SIN etiquetar ({sp['sin_etiqueta_bs']:,.0f} Bs) — pedir a quien lo usa y guardar en tx-labels.json")
    np = s["next_plan"]
    print(f"\n  Próximo pago: 24 en {s['days_to_payday']}d ({s['next_pay']})")
    if np:
        acts = []
        if np.get("colchon"): acts.append(f"colchón {usd(np['colchon'])}")
        if np.get("deuda"): acts.append(f"deuda {usd(np['deuda'])}")
        if np.get("dca"):
            b = round(np["dca"] * 0.8); i = np["dca"] - b
            acts.append(f"DCA {usd(np['dca'])} ({usd(b)} cripto · {usd(i)} índice)")
        print("    → " + "  ·  ".join(acts))
    print()


def propose_import():
    s = compute()
    items = s["spend"]["wallbit_items"]
    if not items:
        print("Sin transacciones Wallbit nuevas en el ciclo.")
        return
    # Ya-identificadas = tienen label por uuid O cat por regla de comercio.
    # Sin identificar = ni label ni cat -> ESTAS son las únicas que se le preguntan a quien lo usa.
    conocidas = [g for g in items if g.get("label") or g.get("cat")]
    nuevas = [g for g in items if not (g.get("label") or g.get("cat"))]
    print(f"\n  PROPUESTA DE IMPORT — {len(items)} gastos Wallbit del ciclo (NO escritos aún):")
    print(f"    {len(conocidas)} ya identificadas (no re-preguntar) · {len(nuevas)} SIN identificar\n")
    print("  ── YA IDENTIFICADAS (label vive en tx-labels.json — NO volver a preguntar) ──")
    for g in sorted(conocidas, key=lambda x: x["fecha"]):
        etiqueta = g.get("label") or f"[regla: {g.get('cat')}]"
        cat = g.get("cat", "?")
        print(f"    {g['fecha']}  {g['monto_bs']:>7,.2f} Bs  {cat:<20} {etiqueta[:40]}")
    if nuevas:
        print("\n  ── ⚠ SIN IDENTIFICAR (SOLO estas se le preguntan a quien lo usa) ──")
        for g in sorted(nuevas, key=lambda x: x["fecha"]):
            print(f"    {g['fecha']}  {g['monto_bs']:>7,.2f} Bs  {g['type']:<11} {g['nota'][:40]}  ·  uuid={g.get('uuid')}")
        print(f"\n    Sin identificar: {sum(g['monto_bs'] for g in nuevas):,.0f} Bs en {len(nuevas)} tx")
    else:
        print("\n  ✓ Nada sin identificar. Todo el ciclo ya está etiquetado.")
    print(f"\n    Total ciclo: {sum(g['monto_bs'] for g in items):,.0f} Bs")
    print("    Aprueba y los agrego a data.json (con uuid para no duplicar).\n")


def selftest():
    """Auto-verificación del motor. Nació después de que una revisión completa destapara
    cuatro bugs que llevaban semanas mintiendo, todos en la misma dirección —hacer parecer
    que se gastaba menos—: transfers salientes ignoradas, envíos on-chain sin clasificar,
    gasto de tarjeta liquidado en dólares y contado como si fueran moneda local, y la tasa
    de retiro usada para valuar gasto en QR.

    Ninguno era visible mirando el resumen: los números se veían razonables. De ahí la
    regla: la plata tiene que CUADRAR, no parecer bien.

    Sale con código 1 si algo falla, así se puede colgar de un cron. Silencio = todo bien."""
    fails, warns = [], []

    def chk(cond, msg):
        if not cond:
            fails.append(msg)

    plan = load("plan.json", {})
    labels_f = load("tx-labels.json", {})
    snap = load("wallbit-snapshot.json", {})
    # data.json es el libro de aportes (pagos de deuda, colchón, DCA). Si no existe
    # todavía —instalación recién hecha— es un libro vacío, no un error: nadie debería
    # chocar contra una verificación fallida por no haber registrado aún ningún aporte.
    data = load("data.json", {"expenses": [], "aportes": [], "ingresos": [], "checks": {}})

    # --- 1-4: archivos presentes y con forma ---
    chk(bool(plan), "plan.json vacío o ilegible")
    chk(bool(snap), "wallbit-snapshot.json vacío o ilegible")
    chk(isinstance(labels_f.get("labels"), dict), "tx-labels.json sin dict 'labels'")
    chk(isinstance(data.get("aportes"), list), "data.json sin lista 'aportes'")

    # --- 5: frescura del snapshot (un brief sobre datos viejos es peor que no tenerlo) ---
    try:
        ref = ahora() or datetime.now(datetime.fromisoformat(snap["synced_at"]).tzinfo)
        age_h = (ref - datetime.fromisoformat(snap["synced_at"])).total_seconds() / 3600
        chk(age_h < 48, f"snapshot viejo: {age_h:.0f}h sin sincronizar (corre --sync)")
    except Exception as e:
        fails.append(f"synced_at ilegible en el snapshot ({e})")

    s = compute()
    sp = s["spend"]

    # --- 6-7: NADA puede pasar sin clasificar (de acá salieron los peores bugs) ---
    dsc = sp.get("tipos_desconocidos") or []
    chk(not dsc, "TIPO DE MOVIMIENTO DESCONOCIDO: " +
        ", ".join(sorted({d['type'] for d in dsc})) + " — plata moviéndose sin clasificar")
    addr = sp.get("addr_sin_libreta") or []
    chk(not addr, f"{len(addr)} envío(s) on-chain a dirección SIN libreta — no sé si es ahorro o gasto")
    vig = sp.get("envios_vigilados") or []
    chk(not vig, "ENVÍO A DIRECCIÓN VIGILADA: " +
        "; ".join(f"{v['fecha']} {v['monto_bs']:,.0f} Bs → {v['nota']}" for v in vig))
    ent = sp.get("entradas_sin_libreta") or []
    chk(not ent, f"{len(ent)} depósito(s) on-chain de dirección SIN identificar "
        f"(${sum(e['usd'] for e in ent):,.0f}) — plata entrando sin explicación")

    # --- 8-10: la tasa tiene que ser creíble ---
    fx, fx_api = s.get("fx"), s.get("fx_api")
    chk(isinstance(fx, (int, float)) and 5 < fx < 25, f"tasa fuera de rango creíble: {fx}")
    chk(fx_api is None or abs(fx - fx_api) / fx_api < 0.12,
        f"tasa QR ({fx}) diverge >12% de la de la API ({fx_api}) — una de las dos está mal")
    chk(s.get("fx_src") != "stored", "usando tasa guardada, no en vivo — el sync no trajo /rates")

    # --- 11-14: el plan tiene que ser internamente coherente ---
    b = plan.get("budget", {})
    techo, fj, vr = b.get("techo_total_bs"), b.get("fijos_total_bs"), b.get("variables_total_bs")
    chk(techo and fj and vr, "budget incompleto en plan.json")
    if techo and fj and vr:
        chk(abs((fj + vr) - techo) < 1, f"techo {techo} ≠ fijos {fj} + variables {vr}")
        chk(abs(sum(b.get("fijos_bs", {}).values()) - fj) < 1,
            f"fijos_bs suma {sum(b.get('fijos_bs', {}).values())} pero fijos_total dice {fj}")
        d = b.get("techo_diario_bs")
        # El ciclo va del 24 al 24: entre 28 y 31 días. Un divisor fijo de 30 daba
        # falsos positivos y, peor, un número diario optimista en meses de 31.
        chk(d and vr / 31 - 1 <= d <= vr / 28 + 1,
            f"techo_diario {d} fuera del rango del ciclo ({vr/31:.0f}–{vr/28:.0f})")

    # --- 15-17: la deuda tiene que cerrar ---
    cred = plan.get("debt", {}).get("creditors", [])
    tot_orig = plan.get("debt", {}).get("total_original_usd", 0)
    chk(abs(sum(c["amount"] for c in cred) - tot_orig) < 1,
        f"acreedores suman {sum(c['amount'] for c in cred)} ≠ deuda original {tot_orig}")
    pagado = sum(float(a.get("deuda", 0) or 0) for a in data.get("aportes", []))
    marcado = sum(c["amount"] for c in cred if c.get("paid"))
    # Un PAGO PARCIAL (ej. $1.000 de una deuda de $2.000) es normal: el acreedor sigue
    # sin estar saldado. Lo que nunca puede pasar es marcar a alguien como pagado sin
    # tener aportes que lo cubran — eso sí sería deuda desaparecida por arte de magia.
    # Exigir igualdad exacta hacía fallar el selftest en falso a cualquiera que fuera
    # pagando de a poco, que es justamente el caso normal.
    chk(pagado >= marcado - 1,
        f"hay ${marcado:.0f} en acreedores marcados como pagados pero sólo "
        f"${pagado:.0f} en aportes que los respalden")
    chk(s["debt_left"] >= 0, f"deuda restante negativa: {s['debt_left']}")

    # --- 18-20: los números del gasto tienen que sumar ---
    chk(sp["var_bs"] >= -1, f"gasto variable negativo: {sp['var_bs']}")
    cb_sum = sum((sp.get("cat_breakdown") or {}).values())
    chk(abs(cb_sum - sp["var_bs"]) < 5,
        f"desglose por categoría suma {cb_sum:.0f} pero el variable dice {sp['var_bs']:.0f}")
    chk(all(g.get("uuid") for g in sp["wallbit_items"]), "hay gastos Wallbit sin uuid (se duplicarían)")

    # --- 21-22: cuentas manuales vivas ---
    mb = load("manual-balances.json", {})
    chk(isinstance(mb.get("accounts"), list) and mb["accounts"], "manual-balances.json sin cuentas")
    try:
        stale = (hoy() - date.fromisoformat(mb.get("updated", "1970-01-01"))).days
        chk(stale <= 45, f"balances manuales sin actualizar hace {stale} días")
    except Exception:
        fails.append("manual-balances.json sin campo 'updated' legible")

    # Un retiro a banco mueve plata a una cuenta que la API NO ve. Si el saldo manual
    # no se tocó desde entonces, el patrimonio queda mal y el "disponible" sale negativo.
    # (Si retiras $1.000 al banco y no actualizas ese saldo, el motor cree que ese dinero
    # se evaporó: tu patrimonio queda mal y el disponible también.)
    try:
        upd = mb.get("updated", "1970-01-01")
        tardios = [t for t in snap.get("transactions", [])
                   if t.get("type") == "WITHDRAWAL_LOCAL" and t.get("status") == "COMPLETED"
                   and fecha_local(t) > upd]
        chk(not tardios,
            f"{len(tardios)} retiro(s) a banco por {sum(float(t.get('dest_amount') or 0) for t in tardios):,.0f} Bs "
            f"posteriores a la última actualización de manual-balances.json ({upd}) — el saldo del banco está viejo")
    except Exception as e:
        fails.append(f"no pude verificar retiros vs balances manuales ({e})")

    # Un retiro a banco sin etiqueta es plata cuyo destino no sabemos: puede ser gasto
    # (y entonces el presupuesto miente) o una transferencia (y entonces no lo es).
    sin_lab = [g for g in (sp.get("conversions") or [])
               if g.get("fecha", "") >= s["cycle_start"] and not labels_f.get("labels", {}).get(g.get("uuid", ""))]
    if sin_lab:
        warns.append(f"{len(sin_lab)} retiro(s) a banco sin etiquetar "
                     f"({sum(x['bs'] for x in sin_lab):,.0f} Bs) — destino desconocido")

    print(f"\n  SELFTEST FINANZAS — {hoy()}")
    for w in warns:
        print(f"  ⚠ {w}")
    if fails:
        print(f"  ✗ {len(fails)} FALLO(S):")
        for f in fails:
            print(f"      · {f}")
        print()
        return 1
    print("  ✓ 22 invariantes OK — la plata cuadra.\n")
    return 0


def alerta():
    """Chequeo de ritmo para el job nocturno. Imprime UNA línea sólo si quien lo usa va
    fuera de presupuesto; si va bien no imprime nada (silencio = vas bien).
    Modelo de dos baldes: los fijos no cuentan al ritmo diario, sólo el balde diario."""
    s = compute()
    sp, b = s["spend"], load("plan.json", {}).get("budget", {})
    diario_budget = b.get("variables_total_bs", 0)
    if not diario_budget:
        return 0
    dia, largo = sp["day_in_cycle"], sp.get("cycle_len", 30)
    gastado = sp["var_bs"]
    esperado = diario_budget * dia / largo
    restante = max(diario_budget - gastado, 0)
    dias_restantes = max(largo - dia, 1)
    por_dia = restante / dias_restantes
    if gastado > esperado * 1.10:
        print(f"Día {dia}/{largo} · llevas {gastado:,.0f} Bs de diario, iban {esperado:,.0f}. "
              f"Te quedan {restante:,.0f} Bs para {dias_restantes} días = "
              f"{por_dia:,.0f} Bs/día (el plan decía {diario_budget/largo:,.0f}).")
        return 1
    return 0


if __name__ == "__main__":
    if "--sync" in sys.argv:
        sync()
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    elif "--alerta" in sys.argv:
        sys.exit(alerta())
    elif "--json" in sys.argv:
        print(json.dumps(compute(), indent=2, ensure_ascii=False, default=str))
    elif "--import" in sys.argv:
        propose_import()
    else:
        brief()
