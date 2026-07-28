#!/usr/bin/env python3
"""Exporta el dataset que consume el visor (state.json) — incluye SERIES POR DÍA.

El brief de finanzas.py da totales; una app necesita curvas: cuánto se gastó cada día,
cómo va el saldo del presupuesto contra el plan, y cómo se compara con el ciclo anterior.
Eso no se puede reconstruir desde un total, así que se calcula acá.

  python3 visor-data.py            -> state.json (datos reales tuyos, NO va a git)
  python3 visor-data.py --demo     -> demo.json  (mismas formas, cifras inventadas, SÍ va a git)

La app es la misma en los dos casos; sólo cambia el archivo que lee. Así el repo público
enseña el producto sin publicar el patrimonio, la deuda ni los movimientos tuyos.
"""
import json, os, re, sys, subprocess
from datetime import date, datetime, timedelta, timezone

# Los datos y la configuración viven en la RAÍZ del repo; el código, en motor/.
# MI_PLATA_DIR redirige esa raíz: así el generador del demo puede correr ESTE MISMO motor
# contra datos sintéticos en una carpeta temporal, en vez de mantener una segunda
# implementación a mano que se desincroniza en silencio (fue justo lo que pasó con el colchón).
DIR = os.environ.get("MI_PLATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
BOL = timezone(timedelta(hours=-4))          # Bolivia, UTC-4


def load(n, d=None):
    try:
        return json.load(open(os.path.join(DIR, n), encoding="utf-8"))
    except Exception:
        return d


def _dt_local(t):
    return datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).astimezone(BOL)


def dia_local(t):
    return _dt_local(t).date()


def hora_local(t):
    """La hora en que PASÓ, en tu zona horaria. La API sella en UTC: sin convertir, un
    pago de las 21:00 aparece a las 01:00 del día siguiente y no lo reconoces.
    La hora es la mitad de la memoria de un gasto ('el almuerzo', 'la salida')."""
    try:
        return _dt_local(t).strftime("%H:%M")
    except Exception:
        return ""


METODO = {"PAY_QR": "QR", "CARD_SPENT": "Tarjeta", "WITHDRAWAL_LOCAL": "Retiro",
          "USER_TRANSFER": "Transferencia", "BLOCKCHAIN_WITHDRAWAL": "Cripto"}



# Bancos y billeteras reales de Bolivia. ANTES la regla era ".*S.A." y se comía cualquier
# razón social: cualquier "COMERCIO S.A." salía clasificado como banco. Lista explícita.
BANCOS = re.compile(
    r"^(yape|tigo\s*money|simple|banco\b|bco\b|bnb\b|bcp\b|bisa\b|ganadero\b|"
    r"econom[ií]co\b|mercantil\b|uni[oó]n\b|banco\s*sol\b|sol\s*s\.?a|fassil\b|"
    r"fie\b|prodem\b|coop\w*\b|interbank\b|administradora\b)", re.I)
HASH = re.compile(r"^[A-Za-z0-9+/]{20,}={0,2}$")
SUFIJO = re.compile(r"[\s,]*(s\.?\s?a\.?|s\.?r\.?l\.?|ltda\.?|sociedad.*)$", re.I)
SIGLAS = {"sa", "srl", "ltda", "yape"}   # agrega las siglas de tu país


def _cap(txt):
    """Capitaliza sin destrozar siglas ni dejar TODO EN MAYÚSCULAS."""
    out = []
    for w in txt.split():
        low = w.lower().strip(".")
        if low in SIGLAS:
            out.append(w.upper())                       # siglas reales: SRL, SA
        elif low in {"la", "el", "de", "del", "y", "los", "las"} and out:
            out.append(low)                             # conectores en minúscula
        else:
            out.append(w.capitalize() if w.isupper() or w.islower() else w)
    t = " ".join(out)
    return t[:1].upper() + t[1:] if t else t


def nombre_comercio(nota):
    """La API entrega el detalle sucio: 'NOMBRE - BANCO', 'descripción - NOMBRE', o un
    hash del QR pegado adelante. Se queda con la parte que un humano leería, sin la
    razón social ni el banco."""
    partes = [x.strip() for x in str(nota or "").split(" - ") if x.strip()]
    utiles = [x for x in partes if not BANCOS.match(x) and not HASH.match(x)]
    txt = (utiles or partes or ["Movimiento"])[0]
    txt = SUFIJO.sub("", txt).strip() or txt
    return _cap(txt)[:40]


def banco_de(nota):
    """La billetera o banco con el que se liquidó el QR."""
    for x in [p.strip() for p in str(nota or "").split(" - ")]:
        if BANCOS.match(x):
            return _cap(SUFIJO.sub("", x).strip())[:22]
    return ""


def construir():
    plan = load("plan.json", {})
    snap = load("wallbit-snapshot.json", {})
    labels = load("tx-labels.json", {})
    out = subprocess.run([sys.executable, os.path.join(AQUI, "finanzas.py"), "--json"],
                         capture_output=True, text=True, cwd=DIR)
    if "{" not in out.stdout:
        detalle = (out.stderr or out.stdout or "sin salida").strip().splitlines()
        sys.exit("\n  No pude leer tu estado financiero.\n"
                 "  El motor (finanzas.py) no devolvió datos:\n"
                 + "\n".join("    " + l for l in detalle[-4:])
                 + "\n\n  Diagnostica con:  python3 motor/setup.py --doctor\n")
    est = json.loads(out.stdout[out.stdout.index("{"):])

    b = plan.get("budget", {})
    fx = est["fx"]
    sp = est["spend"]
    cs = date.fromisoformat(est["cycle_start"])
    largo = sp["cycle_len"]
    hoy = date.fromisoformat(est["today"])

    # --- gasto por día del ciclo actual (sólo balde diario: sin fijos ni deuda) ---
    fijo_uuids = {g["uuid"] for g in sp.get("fijos_items", [])}
    excl = set(labels.get("exclude_from_techo", ["Deuda"]))
    por_dia = {}
    for g in sp["wallbit_items"]:
        if g["uuid"] in fijo_uuids or g.get("cat") in excl:
            continue
        por_dia[g["fecha"]] = por_dia.get(g["fecha"], 0) + g["monto_bs"]

    diario_total = b.get("variables_total_bs", 0)
    serie, acum = [], 0.0
    for i in range(largo):
        d = cs + timedelta(days=i)
        gasto = round(por_dia.get(d.isoformat(), 0), 2)
        futuro = d > hoy
        if not futuro:
            acum += gasto
        serie.append({
            "fecha": d.isoformat(), "dia": i + 1,
            "gasto": None if futuro else gasto,
            "acum": None if futuro else round(acum, 2),
            "plan": round(diario_total * (i + 1) / largo, 2),
            "futuro": futuro,
        })

    # --- ciclo anterior, para comparar (mismo cálculo, ventana previa) ---
    ini_prev = date(cs.year - (cs.month == 1), cs.month - 1 or 12, cs.day)
    prev, pacum = [], 0.0
    SPEND = {"PAY_QR", "CARD_SPENT"}
    pd = {}
    for t in snap.get("transactions", []):
        if t.get("status") != "COMPLETED" or t.get("type") not in SPEND:
            continue
        d = dia_local(t)
        if not (ini_prev <= d < cs):
            continue
        dc = t["dest_currency"]["code"]
        amt = t["dest_amount"] if dc == "BOB" else t["source_amount"] * fx
        pd[d.isoformat()] = pd.get(d.isoformat(), 0) + amt
    for i in range((cs - ini_prev).days):
        d = ini_prev + timedelta(days=i)
        pacum += pd.get(d.isoformat(), 0)
        prev.append({"dia": i + 1, "acum": round(pacum, 2)})

    # --- restricción real: la caja, no el techo ---
    # ── gasto que NO pasó por Wallbit ────────────────────────────────────────
    # Un retiro al banco etiquetado como pago (ej. servicios) ES gasto aunque la API
    # no lo vea. Antes quedaba fuera de "gastado este mes" pero SÍ se descontaba de
    # "fijos pendientes": el presupuesto los daba por pagados y el gasto no los mostraba.
    excl_cat = set(labels.get("exclude_from_techo", ["Deuda"]))
    lab = labels.get("labels", {})
    txm = {t.get("uuid"): t for t in snap.get("transactions", [])}
    fuera, sin_id, pend = 0.0, [], []
    for t in snap.get("transactions", []):
        if t.get("type") != "WITHDRAWAL_LOCAL" or t.get("status") != "COMPLETED":
            continue
        if dia_local(t) < cs:
            continue
        L = lab.get(t.get("uuid"))
        monto = float(t.get("dest_amount") or 0)
        if L and L.get("cat") not in excl_cat:
            fuera += monto
        elif not L:
            pm = t.get("payment_method") or {}
            su = t.get("source_user") or {}
            propio = (su.get("firstname", "") + " " + su.get("lastname", "")).strip().lower()
            benef = str(pm.get("beneficiary_name") or "").strip()
            # Un retiro a tu propia cuenta no se identifica por el beneficiario: eres tú.
            # Tu nombre ahí no ayuda a recordar nada; "a tu banco" sí ubica el movimiento.
            titulo = ("Retiro a tu banco" if (not benef or benef.lower() == propio)
                      else _cap(benef)[:40])
            sin_id.append({"fecha": dia_local(t).isoformat(), "bs": round(monto, 2),
                           "usd": round(float(t.get("source_amount") or 0), 2)})
            pend.append({
                "uuid": t.get("uuid"), "fecha": dia_local(t).isoformat(), "hora": hora_local(t),
                "nombre": titulo, "banco": _cap(pm.get("bank_name") or "")[:22],
                "metodo": "Retiro", "tipo": "WITHDRAWAL_LOCAL",
                "bs": round(monto, 2), "usd": round(float(t.get("source_amount") or 0), 2),
                "detalle": "Sacaste dólares a tu banco. Wallbit ve que salieron, no en qué terminaron.",
            })

    # Gasto capturado por Wallbit que quedó sin categoría: ni etiqueta por uuid, ni regla de
    # comercio, ni el default de QR chico. Va a la MISMA cola que los retiros — para quien
    # lo usa es el mismo trabajo ("¿qué fue esto?"), aunque el motor los trate distinto.
    for g in sp["wallbit_items"]:
        if g.get("cat") or g.get("fijo") or lab.get(g.get("uuid")):
            continue
        t = txm.get(g.get("uuid")) or {}
        pend.append({
            "uuid": g.get("uuid"), "fecha": g["fecha"], "hora": hora_local(t) if t else "",
            "nombre": nombre_comercio(g.get("nota")), "banco": banco_de(g.get("nota")),
            "metodo": METODO.get(g.get("type"), "Pago"), "tipo": g.get("type"),
            "bs": round(g["monto_bs"], 2),
            "usd": round(g["monto_bs"] / fx, 2) if fx else None,
            "detalle": str(g.get("nota") or "")[:90],
        })
    # Descripciones ya escritas: el movimiento sigue en la cola, pero con lo que su dueño
    # recordó de él. Describir y clasificar son dos trabajos distintos — el primero sólo lo
    # puede hacer quien gastó, el segundo es mecánico. Separarlos evita que la nota se
    # pierda por no haber elegido categoría en ese momento.
    desc = labels.get("descripciones", {}) or {}
    for x in pend:
        d = desc.get(x.get("uuid"))
        if d:
            x["descripcion"] = d.get("texto", "")

    # Pagos ya hechos de un excepcional: cada etiqueta puede decir a qué gasto decidido
    # pertenece. Se agrupan por excepcional para que la reserva sólo aparte lo que FALTA.
    # El gasto igual cuenta en la curva del ciclo: gastado es gastado — lo que no puede
    # pasar es apartar plata para algo que ya compraste.
    pagos_exc = {}
    for uuid, v in lab.items():
        ident = (v or {}).get("excepcional")
        if not ident:
            continue
        t = txm.get(uuid) or {}
        monto = v.get("monto_bs")
        if monto is None:
            monto = round(float(v.get("monto_usd") or 0) * fx, 2)
        pagos_exc.setdefault(ident, []).append({
            "uuid": uuid, "fecha": v.get("fecha") or (t.get("created_at") or "")[:10],
            "bs": round(float(monto or 0), 2),
            "nota": v.get("nota") or v.get("label") or "",
        })
    for v in pagos_exc.values():
        v.sort(key=lambda x: x["fecha"], reverse=True)

    # Lo más reciente arriba, y dentro del día lo más caro primero: si sólo vas a etiquetar
    # una cosa, que sea la que más mueve el número.
    pend.sort(key=lambda x: (x["fecha"], x["bs"]), reverse=True)
    # Y los ya descritos al final (sort estable: conserva el orden de arriba). Lo que hace
    # falta que mires es lo que NO tiene contexto todavía.
    pend.sort(key=lambda x: bool(x.get("descripcion")))

    # Taxonomía de botones. Sale de tx-labels.json (_categories), ordenada por USO real:
    # las categorías que más usas quedan al alcance del pulgar. Determinista: el orden lo
    # decide el motor con tus datos, no el criterio de quien escribió la interfaz.
    uso = {}
    for L in lab.values():
        if L.get("cat"):
            uso[L["cat"]] = uso.get(L["cat"], 0) + 1
    catdef = labels.get("_categories", {})
    orden = [k for k in catdef if not k.startswith("_") and k != "Sin clasificar"]
    taxonomia = [{"nombre": k, "fijo": bool(catdef[k].get("fijo")),
                  "desc": catdef[k].get("desc", ""), "usos": uso.get(k, 0),
                  "no_consumo": k in excl_cat}
                 for k in sorted(orden, key=lambda k: (-uso.get(k, 0), orden.index(k)))]

    auto_n = [g for g in sp["wallbit_items"] if g.get("auto_default")]

    r = b.get("restriccion_real", {})
    # La caja gastable NO es sólo Wallbit: cuando quien lo usa retira al banco, la plata sigue
    # siendo suya. Contar sólo la API daba "disponible" NEGATIVO después de un retiro grande.
    # Se suman todas las cuentas líquidas; lo invertido (BTC, índice) queda fuera a propósito.
    caja = (est["wallbit"]["checking"] + est["wallbit"]["inv_cash"]
            + sum(a["usd"] for a in est["manual_accounts"] if a.get("kind") == "liquido"))
    fijos_pend = r.get("fijos_pendientes_bs", 0)
    # Días que la plata tiene que aguantar: de HOY al día de pago, inclusive. Antes era
    # largo−día, que excluye hoy y deja el número diario optimista (397 en vez de 383).
    dias_rest = max((date.fromisoformat(est["next_pay"]) - hoy).days, 1)
    # El colchón NO es plata gastable. Si sigue contando en el disponible no es un
    # ahorro, es un saldo: y un saldo que puedes tocar se termina tocando.
    colchon = est.get("colchon_current", 0)
    libre_bs = (caja - colchon) * fx - est["debt_left"] * fx - fijos_pend

    return {
        "generado": datetime.now(BOL).isoformat(timespec="seconds"),
        "demo": False,
        "hoy": est["today"], "sincronizado": est["synced_at"],
        "fx": fx, "fx_api": est["fx_api"], "fx_fuente": est["fx_src"],
        "ciclo": {"inicio": est["cycle_start"], "fin": est["next_pay"],
                  "dia": sp["day_in_cycle"], "largo": largo,
                  "dias_al_pago": est["days_to_payday"]},
        "presupuesto": {"techo": b.get("techo_total_bs"), "fijos": b.get("fijos_total_bs"),
                        "diario_total": diario_total,
                        "diario_gastado": round(sp["var_bs"], 2),
                        "fijos_detalle": b.get("fijos_bs", {}),
                        "gasto_real_medido": b.get("gasto_real_medido_bs_mes"),
                        "gasto_real_neto": b.get("gasto_real_neto_onetimes_bs_mes")},
        "caja": {"gastable_usd": round(caja - colchon, 2), "total_liquido_usd": round(caja, 2),
                 "libre_bs": round(libre_bs, 2),
                 "fijos_pendientes_bs": fijos_pend, "dias_restantes": dias_rest,
                 "diario_a_cero": round(libre_bs / dias_rest, 2),
                 "retiros_sin_identificar": sin_id,
                 "retirado_sin_identificar_bs": round(sum(x["bs"] for x in sin_id), 2)},
        # LA COLA DE TRABAJO. Todo lo que el sistema no sabe qué fue. Va arriba en la app:
        # mientras esto tenga cosas, los números de abajo están incompletos.
        "pendientes": pend,
        "pendiente_bs": round(sum(p["bs"] for p in pend), 2),
        "taxonomia": taxonomia,
        "auto_clasificados": {"n": len(auto_n), "bs": round(sum(g["monto_bs"] for g in auto_n), 2),
                              "cat": (labels.get("default_qr_rule", {}) or {}).get("cat", "Comida"),
                              "max_bs": (labels.get("default_qr_rule", {}) or {}).get("max_bs", 200)},
        "movimientos": sorted(
            [{"uuid": g.get("uuid"), "fecha": g["fecha"],
              "hora": hora_local(txm[g["uuid"]]) if g.get("uuid") in txm else "",
              "nombre": nombre_comercio(g.get("nota")),
              "banco": banco_de(g.get("nota")),
              "metodo": METODO.get(g.get("type"), "Pago"),
              "cat": g.get("cat") or "Sin clasificar", "bs": round(g["monto_bs"], 2),
              "usd": round(g["monto_bs"] / fx, 2) if fx else None,
              "auto": bool(g.get("auto_default")),
              "fijo": bool(g.get("fijo")), "tipo": g.get("type")}
             for g in sp["wallbit_items"]],
            key=lambda x: (x["fecha"], x["bs"]), reverse=True),
        "serie": serie, "serie_previa": prev,
        "categorias": sp["cat_breakdown"],
        "patrimonio": {
            "activos": round(est["assets"], 2), "neto": round(est["net"], 2),
            # Los tres números que quien lo usa pide de entrada: cuánto tiene, cuánto está
            # trabajando (invertido) y cuánto puede tocar hoy (líquido).
            "invertido": round(est["wallbit"]["etf"]
                               + sum(a["usd"] for a in est["manual_accounts"]
                                     if a.get("kind") == "invertido"), 2),
            "liquido": round(est["wallbit"]["checking"] + est["wallbit"]["inv_cash"]
                             + sum(a["usd"] for a in est["manual_accounts"]
                                   if a.get("kind") == "liquido"), 2),
            # QR/tarjeta + lo pagado por banco con etiqueta de gasto
            "gastado_ciclo_bs": round(sp["total_bs"] - sp.get("no_consumo_bs", 0) + fuera, 2),
            "gastado_wallbit_bs": round(sp["total_bs"] - sp.get("no_consumo_bs", 0), 2),
            "gastado_fuera_bs": round(fuera, 2),
            "cuentas": (
                [{"nombre": "Wallbit · líquido", "usd": est["wallbit"]["checking"], "tipo": "liquido"},
                 {"nombre": "Wallbit · sin invertir", "usd": est["wallbit"]["inv_cash"], "tipo": "liquido"},
                 {"nombre": "Wallbit · índice SPY", "usd": est["wallbit"]["etf"], "tipo": "invertido"}]
                + [{"nombre": a["name"], "usd": round(a["usd"], 2),
                    "tipo": a.get("kind", "liquido")} for a in est["manual_accounts"]])},
        # Las cuentas que la API no ve. Se editan DESDE la app (POST /manual-balances):
        # si para corregir un saldo hay que abrir un archivo JSON, no se corrige nunca.
        "cuentas_manuales": [{"name": a["name"], "amount": a["amount"],
                              "currency": a.get("currency", "USD"),
                              "kind": a.get("kind", "liquido"), "usd": round(a["usd"], 2)}
                             for a in est["manual_accounts"]],
        "deuda": {"total": est["debt_total"], "restante": est["debt_left"],
                  "acreedores": est["debt_dist"],
                  "cerrada": est["debt_left"] <= 0, "fecha_cero": est["milestones"].get("debt_zero")},
        "colchon": {"actual": est["colchon_current"], "meta": est["colchon_meta"],
                    "falta": round(max(est["colchon_meta"] - est["colchon_current"], 0), 2),
                    "pct": round(est["colchon_current"] / est["colchon_meta"], 4) if est["colchon_meta"] else 0,
                    "aporte_plan": (est.get("next_plan") or {}).get("colchon", 0),
                    "meses_al_ritmo": (
                        round(max(est["colchon_meta"] - est["colchon_current"], 0)
                              / (est.get("next_plan") or {}).get("colchon", 0), 1)
                        if (est.get("next_plan") or {}).get("colchon") else None)},
        "hitos": est["milestones"], "proximo_plan": est["next_plan"],
        "excepcionales": excepcionales(b, fx, libre_bs, dias_rest, hoy, pagos_exc),
        "ingresos": sp["ingresos"], "n_movimientos": len(sp["wallbit_items"]),
    }


def slug_exc(nombre):
    """Identificador estable de un excepcional. Se deriva del nombre pero aguanta que le
    cambies el texto: se compara sin tildes, sin signos y sin mayúsculas."""
    t = (nombre or "").lower()
    for a, b_ in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")):
        t = t.replace(a, b_)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]


def excepcionales(b, fx, libre_bs, dias_rest, hoy, pagos=None):
    """El TERCER BALDE: gastos con fecha y monto ya decididos (cumpleaños, viaje).

    Vivían sólo en plan.json y nunca llegaban a la pantalla, así que el número de
    "puedes gastar hoy" los ignoraba: 324 Bs/día con 500 dólares ya comprometidos
    en los próximos 17 días es el mismo error que contar un retiro como plata libre.

    NO se toca `caja.diario_a_cero` (de ahí comen el selftest, la alerta nocturna y
    el motor). Se agrega al lado el número CON la reserva puesta, y la app muestra
    ese como el grande. Lo excepcional se presupuesta, lo diario se controla.
    """
    exc = (b or {}).get("excepcionales") or {}
    items = []
    reservado_bs = 0.0
    for it in exc.get("items", []):
        f = it.get("fecha")
        d = None
        try:
            d = date.fromisoformat(f) if f else None
        except (TypeError, ValueError):
            d = None
        pasado = bool(d and d < hoy)
        bs = round(float(it.get("usd") or 0) * fx, 2)
        # Lo que YA pagaste de esto no hay que volver a apartarlo. Sin esto, comprar el
        # pasaje del viaje bajaba tu caja Y seguía reservando el pasaje entero: la misma
        # plata contada dos veces, y el número diario mintiendo hacia abajo.
        ident = it.get("id") or slug_exc(it.get("nombre"))
        pagado_bs = round(sum(p["bs"] for p in (pagos or {}).get(ident, [])), 2)
        restante_bs = round(max(bs - pagado_bs, 0), 2)
        if not pasado:
            reservado_bs += restante_bs
        items.append({"id": ident, "nombre": it.get("nombre"), "fecha": f,
                      "usd": it.get("usd"), "bs": bs,
                      "pagado_bs": pagado_bs, "restante_bs": restante_bs,
                      "pagos": (pagos or {}).get(ident, []),
                      "saldado": pagado_bs >= bs - 1,
                      "dias_faltan": (d - hoy).days if d else None,
                      "pasado": pasado, "nota": it.get("nota")})
    items.sort(key=lambda x: (x["fecha"] or "9999"))

    disponible = libre_bs - reservado_bs
    return {
        "items": items,
        "reservado_bs": round(reservado_bs, 2),
        "reservado_usd": round(reservado_bs / fx, 2) if fx else 0,
        "libre_tras_reserva_bs": round(disponible, 2),
        # El número honesto: lo que queda por día DESPUÉS de apartar lo ya decidido.
        "diario_con_reserva": round(disponible / dias_rest, 2) if dias_rest else 0,
        "alcanza": disponible > 0,
        # La clave lleva la fecha en que se escribió (`_veredicto_2026-07-27`), así que
        # se busca por prefijo: si mañana se re-decide, el nuevo aparece solo.
        "veredicto": next((v for k, v in sorted(exc.items(), reverse=True)
                           if k.lower().startswith("_veredicto") and isinstance(v, str)), None),
    }




# Todo campo que la app dibuja tiene que existir acá. Si falta, la interfaz mostraba
# NaN sin explicación; ahora la generación falla de una y dice cuál falta.
REQUERIDOS = [
    ("patrimonio", ["activos", "neto", "invertido", "liquido", "gastado_ciclo_bs"]),
    ("caja", ["gastable_usd", "libre_bs", "dias_restantes", "diario_a_cero"]),
    ("ciclo", ["inicio", "fin", "dia", "largo", "dias_al_pago"]),
    ("presupuesto", ["techo", "fijos", "diario_total", "diario_gastado"]),
    ("deuda", ["total", "restante", "acreedores", "cerrada"]),
    ("colchon", ["actual", "meta", "falta", "pct"]),
]
# La cola de trabajo y sus botones no son adorno: si faltan, la app deja de ser
# operable y vuelve a ser un tablero para mirar. Se valida como todo lo demás.
LISTAS = ("serie", "movimientos", "categorias", "hitos", "pendientes", "taxonomia",
          "cuentas_manuales")
# Cada pendiente tiene que traer con qué reconocerlo. Un "570 Bs, 26 jul" sin hora,
# sin comercio y sin uuid no se puede etiquetar: ni te acuerdas tú, ni el servidor
# sabe dónde escribirlo.
CAMPOS_PENDIENTE = ("uuid", "fecha", "hora", "nombre", "metodo", "bs", "usd")


def validar(estado):
    faltan = []
    for seccion, campos in REQUERIDOS:
        if seccion not in estado:
            faltan.append(seccion)
            continue
        faltan += [f"{seccion}.{c}" for c in campos if c not in estado[seccion]]
    for lista in LISTAS:
        if lista not in estado:
            faltan.append(lista)
    for i, p in enumerate(estado.get("pendientes", [])):
        faltan += [f"pendientes[{i}].{c}" for c in CAMPOS_PENDIENTE if c not in p]
    if faltan:
        sys.exit("\n  El estado generado está incompleto; la app mostraría '—' en:\n"
                 + "\n".join("    · " + f for f in faltan)
                 + "\n\n  Es un error del generador, no de tus datos. Reporta esto.\n")
    return estado


def cocinar_demo():
    """Genera demo.json COCINÁNDOLO con el motor real, no escribiéndolo a mano.

    Inventa las respuestas crudas de la API (`motor/demo-fuente.py`), las deja en una
    carpeta temporal y corre ESTE MISMO archivo apuntado ahí con MI_PLATA_DIR. Lo que sale
    pasó por `construir()`, igual que tus datos de verdad.

    Antes el demo se armaba a mano y era una segunda implementación: se desincronizó en
    silencio y la página pública terminó enseñando un número diario hasta 50% más alto que
    el del producto real (repartía el colchón como plata gastable). Con esto no puede
    volver a pasar: si el motor cambia, el demo cambia con él.
    """
    import importlib.util, tempfile
    ruta = os.path.join(AQUI, "demo-fuente.py")
    spec = importlib.util.spec_from_file_location("demo_fuente", ruta)
    fuente = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fuente)

    with tempfile.TemporaryDirectory(prefix="mi-plata-demo-") as tmp:
        fuente.generar(tmp)
        env = {**os.environ, "MI_PLATA_DIR": tmp, "MI_PLATA_HOY": fuente.HOY}
        out = subprocess.run([sys.executable, os.path.abspath(__file__), "--emitir"],
                             capture_output=True, text=True, env=env, cwd=tmp)
        if "{" not in out.stdout:
            detalle = (out.stderr or out.stdout or "sin salida").strip().splitlines()
            sys.exit("\n  El generador del demo no pudo cocinar los datos:\n"
                     + "\n".join("    " + l for l in detalle[-6:]) + "\n")
        estado = json.loads(out.stdout[out.stdout.index("{"):])

    # Marcas fijas: sin esto el archivo cambiaría cada día por el timestamp y ensuciaría
    # el historial de git aunque los datos fueran idénticos.
    estado["demo"] = True
    estado["generado"] = f"{fuente.HOY}T09:00:00-04:00"
    estado["sincronizado"] = f"{fuente.HOY}T13:00:00+00:00"
    return estado


if __name__ == "__main__":
    if "--emitir" in sys.argv:          # interno: lo usa cocinar_demo()
        print(json.dumps(construir(), ensure_ascii=False))
        sys.exit(0)
    if "--demo" in sys.argv:
        estado = validar(cocinar_demo())
        json.dump(estado, open(os.path.join(DIR, "demo.json"), "w"),
                  ensure_ascii=False, indent=1)
        c, tipos = estado["caja"], estado.get("_tipos_api", {})
        print(f"demo.json  ·  cocinado por el motor real  ·  {estado['n_movimientos']} movimientos  "
              f"·  {c['diario_a_cero']:,.0f} Bs/día")
        print("             100% sintético: personas, comercios y montos inventados.")
        sys.exit(0)
    real = construir()
    if True:
        json.dump(validar(real), open(os.path.join(DIR, "state.json"), "w"),
                  ensure_ascii=False, indent=1)
        c = real["caja"]
        print(f"state.json  ·  día {real['ciclo']['dia']}/{real['ciclo']['largo']}  ·  "
              f"{len(real['serie'])} días de serie  ·  libre {c['libre_bs']:,.0f} Bs  "
              f"= {c['diario_a_cero']:,.0f} Bs/día")
