#!/usr/bin/env python3
"""Instalación guiada. Al terminar, o funciona, o te dice exactamente qué falta.

  python3 motor/setup.py            instalar (o retomar donde quedaste)
  python3 motor/setup.py --doctor   diagnosticar una instalación que no anda
  python3 motor/setup.py --reset    borrar la configuración y empezar de cero

TRES DECISIONES DE DISEÑO, para que esto no se rompa:

1. MEDIR ANTES DE PREGUNTAR. Nadie sabe cuánto gasta al mes. Preguntarlo en un campo
   vacío garantiza un número inventado y un presupuesto que falla a la semana. Acá se
   leen tus últimos 35 días reales desde la API y se te propone un techo con base en
   eso; tú sólo lo confirmas o lo ajustas.

2. ESCRITURA ATÓMICA. Nada se guarda a medias. Cada archivo se escribe en un temporal,
   se vuelve a leer para comprobar que es JSON válido, y recién ahí reemplaza al bueno.
   Si te cortas a la mitad (Ctrl-C, se cae la luz), lo que ya estaba sigue intacto.

3. IDEMPOTENTE. Correrlo dos veces no rompe nada: detecta lo que ya está configurado y
   te ofrece conservarlo. Todas las preguntas traen un valor por defecto entre [corchetes]:
   con Enter avanzas.
"""
import json, os, re, subprocess, sys, tempfile
import urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
KEY_FILE = os.path.expanduser("~/.finanzas/wallbit.key")
API = "https://api.wallbit.io/api/public/v1"
MIN_PY = (3, 9)

C = {"ok": "\033[92m", "err": "\033[91m", "warn": "\033[93m",
     "dim": "\033[90m", "b": "\033[1m", "_": "\033[0m"}
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = {k: "" for k in C}


def titulo(n, total, txt):
    print(f"\n{C['b']}[{n}/{total}] {txt}{C['_']}")
    print(C["dim"] + "─" * 66 + C["_"])


def ok(m):    print(f"  {C['ok']}✓{C['_']} {m}")
def malo(m):  print(f"  {C['err']}✗{C['_']} {m}")
def aviso(m): print(f"  {C['warn']}!{C['_']} {m}")
def nota(m):  print(f"    {C['dim']}{m}{C['_']}")


def preguntar(txt, defecto=None, valida=None, ayuda=None):
    """Pregunta hasta obtener algo válido. Enter acepta el valor por defecto."""
    if ayuda:
        nota(ayuda)
    while True:
        d = f" [{defecto}]" if defecto not in (None, "") else ""
        try:
            r = input(f"  {txt}{d}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Cancelado. Nada quedó a medias.\n")
            sys.exit(1)
        if not r and defecto is not None:
            r = str(defecto)
        if not r:
            malo("Hace falta un valor.")
            continue
        if valida:
            v, msg = valida(r)
            if v is None:
                malo(msg)
                continue
            return v
        return r


def si_no(txt, defecto=True):
    d = "S/n" if defecto else "s/N"
    while True:
        try:
            r = input(f"  {txt} [{d}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Cancelado.\n")
            sys.exit(1)
        if not r:
            return defecto
        if r in ("s", "si", "sí", "y", "yes"):
            return True
        if r in ("n", "no"):
            return False


# ── validadores ──
def v_entero(lo, hi, nombre="valor"):
    def f(r):
        try:
            n = int(re.sub(r"[^\d-]", "", r))
        except ValueError:
            return None, f"{nombre}: escribe un número entero."
        if not (lo <= n <= hi):
            return None, f"{nombre}: tiene que estar entre {lo} y {hi}."
        return n, ""
    return f


def v_monto(r):
    try:
        n = float(re.sub(r"[^\d.]", "", r.replace(",", ".")))
    except ValueError:
        return None, "Escribe sólo el número, sin símbolos."
    if n < 0:
        return None, "No puede ser negativo."
    return round(n, 2), ""


def escribir(nombre, datos):
    """Escritura atómica: temporal -> validar -> reemplazar. Nunca deja un archivo a medias."""
    destino = os.path.join(RAIZ, nombre)
    fd, tmp = tempfile.mkstemp(dir=RAIZ, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        json.load(open(tmp, encoding="utf-8"))     # si no relee, no reemplaza
        os.replace(tmp, destino)
        return True
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        malo(f"No pude escribir {nombre}: {e}")
        return False


def leer(nombre, defecto=None):
    try:
        return json.load(open(os.path.join(RAIZ, nombre), encoding="utf-8"))
    except Exception:
        return defecto


def api(path, key, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


# ══════════════════════════════════════════════════════════════════════════
def instalar_hook():
    """Activa el guardia de commits. Las reglas escritas se ignoran; un hook no."""
    h = os.path.join(RAIZ, "hooks", "pre-commit")
    if not os.path.exists(h) or not os.path.isdir(os.path.join(RAIZ, ".git")):
        return
    try:
        os.chmod(h, 0o755)
        subprocess.run(["git", "config", "core.hooksPath", "hooks"],
                       cwd=RAIZ, capture_output=True, check=True)
        ok("Guardia de commits activo: git rechaza tus datos y tu key si intentan subir")
    except Exception:
        aviso("No pude activar el hook. Actívalo con:  git config core.hooksPath hooks")


def paso_python(n, t):
    titulo(n, t, "Python")
    if sys.version_info < MIN_PY:
        malo(f"Tienes Python {sys.version_info.major}.{sys.version_info.minor}; "
             f"hace falta {MIN_PY[0]}.{MIN_PY[1]} o superior.")
        nota("En macOS:  brew install python3       En Ubuntu:  sudo apt install python3")
        sys.exit(1)
    ok(f"Python {sys.version_info.major}.{sys.version_info.minor} — sirve. Cero dependencias que instalar.")
    instalar_hook()
    return True


def paso_key(n, t):
    titulo(n, t, "Tu API key de Wallbit")
    key = os.environ.get("WALLBIT_API_KEY")
    if not key and os.path.exists(KEY_FILE):
        key = open(KEY_FILE).read().strip()
        if key:
            ok(f"Encontré una key guardada en {KEY_FILE}")
            if not si_no("¿La uso?", True):
                key = None
    if not key:
        print()
        print(f"  {C['b']}Sin una API key de Wallbit esto no puede funcionar.{C['_']}")
        print("  Es lo único que necesitas. Sacarla toma un minuto:\n")
        print(f"    1. Entra a  {C['b']}https://developer.wallbit.io/dashboard/{C['_']}")
        print("    2. Inicia sesión con tu cuenta de Wallbit")
        print("    3. Crea una key nueva. Si te deja elegir permisos, dale SOLO LECTURA:")
        print("       este proyecto nunca escribe en tu cuenta.")
        print(f"    4. {C['warn']}Cópiala en ese momento{C['_']} — Wallbit la muestra una sola vez.\n")
        nota("Docs: https://developer.wallbit.io/docs/quickstart")
        nota("¿Prefieres ver cómo se ve antes de sacarla?")
        nota("  https://moiwalter.github.io/mi-plata/  (demo, sin configurar nada)")
        print()
        key = preguntar("Pega tu API key acá")

    print("\n  Probándola contra la API…")
    try:
        d = api("/balance/checking", key)
    except urllib.error.HTTPError as e:
        malo(f"La API respondió {e.code}.")
        if e.code in (401, 403):
            nota("Esa key no es válida o no tiene permisos de lectura.")
            nota("Crea una nueva en https://developer.wallbit.io/dashboard/")
            nota("Ojo: Wallbit la muestra una sola vez; si la perdiste, genera otra.")
        else:
            nota("Puede ser un problema temporal de Wallbit. Intenta de nuevo en un rato.")
        return None
    except Exception as e:
        malo(f"No pude conectarme: {e}")
        nota("¿Tienes internet? Si estás detrás de un proxy, exporta HTTPS_PROXY.")
        return None

    saldos = d.get("data", []) if isinstance(d, dict) else []
    ok("La key funciona.")
    for b in saldos:
        nota(f"{b.get('currency')}: {b.get('balance')}")

    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w") as f:
        f.write(key + "\n")
    os.chmod(KEY_FILE, 0o600)
    ok(f"Guardada en {KEY_FILE} (permisos 600, fuera del repositorio)")
    return key


def paso_moneda(n, t, key):
    titulo(n, t, "Tu moneda local")
    nota("Wallbit guarda dólares; tú gastas en la moneda de tu país.")
    cur = preguntar("Código de tu moneda local (BOB, ARS, COP, MXN…)", "BOB",
                    lambda r: (r.upper(), "") if re.fullmatch(r"[A-Za-z]{3}", r)
                    else (None, "Son 3 letras, como BOB o ARS."))
    try:
        r = api("/rates", key, {"source_currency": "USD", "dest_currency": cur})
        tasa = float((r.get("data") or r).get("rate") or 0)
        if tasa:
            ok(f"1 USD = {tasa:,.2f} {cur} (según la API, ahora mismo)")
            return cur, tasa
    except Exception:
        pass
    aviso(f"La API no me dio la tasa para {cur}.")
    tasa = preguntar(f"¿Cuántos {cur} vale 1 USD?", "1", v_monto)
    return cur, tasa


MONEDA = ["?"]


def paso_medir(n, t, key, tasa):
    """Lee el gasto real de los últimos 35 días. Es lo que evita un presupuesto inventado."""
    titulo(n, t, "Cuánto gastas de verdad")
    nota("Leo tus últimos 35 días para proponerte un presupuesto con base en datos,")
    nota("no en una corazonada. Esto tarda unos segundos.")
    r = subprocess.run([sys.executable, os.path.join(AQUI, "wallbit-sync.py"), "--days", "35"],
                       capture_output=True, text=True, cwd=RAIZ)
    snap = leer("wallbit-snapshot.json")
    if r.returncode != 0 or not snap:
        aviso("No pude bajar el historial; seguimos sin la medición.")
        nota((r.stderr or r.stdout or "").strip()[:200])
        return None

    BOL = timezone(timedelta(hours=0))
    def dia(x):
        return datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")).date()
    gastos = [x for x in snap.get("transactions", [])
              if x.get("status") == "COMPLETED" and x.get("type") in ("PAY_QR", "CARD_SPENT")]
    if not gastos:
        aviso("No encontré gastos en los últimos 35 días. Usaré valores genéricos.")
        return None
    tot = sum((x["dest_amount"] if x["dest_currency"]["code"] != "USD"
               else x["source_amount"] * tasa) for x in gastos)
    dias = max((max(map(dia, gastos)) - min(map(dia, gastos))).days, 1)
    mes = tot / dias * 30
    ok(f"{len(gastos)} movimientos en {dias} días  ·  {tot:,.0f} {MONEDA[0]} en total")
    ok(f"Tu ritmo real: {tot/dias:,.0f} {MONEDA[0]} por día  =  {mes:,.0f} al mes")
    return round(mes)


def usd_(v):
    return f"${v:,.0f}"


def paso_plan(n, t, cur, tasa, medido):
    titulo(n, t, "Tu plan")
    prev = leer("plan.json")
    if prev and not si_no("Ya tienes un plan.json. ¿Lo rehago?", False):
        ok("Conservo el que ya tenías.")
        return prev

    payday = preguntar("¿Qué día del mes cobras?", 1, v_entero(1, 28, "Día"),
                       "Si cobras el 30 o 31, pon 28: el ciclo necesita un día que exista siempre.")
    ingreso = preguntar("¿Cuánto cobras al mes, en USD?", 1000, v_monto)

    print()
    deudas = []
    if si_no("¿Debes plata a alguien?", False):
        while True:
            nom = preguntar("  Nombre (o 'listo' para terminar)", "listo")
            if nom.lower() in ("listo", "no", "fin"):
                break
            deudas.append({"name": nom,
                           "amount": preguntar(f"  ¿Cuánto le debes a {nom}? (USD)", 100, v_monto),
                           "paid": False})
    deuda_total = sum(d["amount"] for d in deudas)

    print()
    base = medido or round(ingreso * tasa * 0.5)
    if medido:
        nota(f"Medido: gastas ~{medido:,.0f} {cur} al mes.")
        nota(f"Te propongo {round(base*0.85):,.0f} — un 15% menos, exigente pero alcanzable.")
    techo = preguntar(f"Tu techo de gasto mensual en {cur}", round(base * 0.85), v_monto)

    print()
    nota("Ahora los FIJOS: lo que cae en bloque (alquiler, servicios, suscripciones).")
    nota("No cuentan contra tu número diario, por eso van aparte.")
    fijos = {}
    while True:
        nom = preguntar("  Nombre del gasto fijo (o 'listo')", "listo")
        if nom.lower() in ("listo", "no", "fin", "ninguno"):
            break
        fijos[nom] = preguntar(f"  ¿Cuánto es {nom} al mes? ({cur})", 100, v_monto)
        sub = sum(fijos.values())
        if sub >= techo:
            aviso(f"Tus fijos ({sub:,.0f}) ya igualan o superan el techo ({techo:,.0f}).")
            nota("O sube el techo, o algo de esto no es realmente fijo.")
    fijos_total = sum(fijos.values())
    if fijos_total >= techo:
        techo = preguntar(f"Sube el techo (fijos = {fijos_total:,.0f})",
                          round(fijos_total * 1.6), v_monto)

    variable = round(techo - fijos_total, 2)
    print()
    ok(f"Fijos {fijos_total:,.0f} + diario {variable:,.0f} = techo {techo:,.0f} {cur}")
    ok(f"Tu número a vigilar: {variable/30:,.0f} {cur} por día")

    print()
    colchon = preguntar("Meta de colchón de emergencia, en USD",
                        round(techo / tasa * 3), v_monto,
                        "Lo habitual son 3 meses de gastos.")

    # Antes de guardar, mostrar lo entendido. Un dato mal tecleado se corrige acá,
    # no tres días después cuando el tablero muestre un número que no cuadra.
    print()
    print(f"  {C['b']}Esto entendí:{C['_']}")
    print(f"    Cobras {usd_(ingreso)} el día {payday} de cada mes")
    if deudas:
        print(f"    Debes {usd_(deuda_total)} a {len(deudas)} persona(s): "
              + ", ".join(d["name"] for d in deudas))
    else:
        print("    No debes plata a nadie")
    print(f"    Techo de gasto: {techo:,.0f} {cur} al mes")
    print(f"      = {fijos_total:,.0f} de fijos ({', '.join(fijos) or 'ninguno'})")
    print(f"      + {variable:,.0f} para el día a día  →  {C['b']}{variable/30:,.0f} {cur} por día{C['_']}")
    print(f"    Meta de colchón: {usd_(colchon)}")
    print()
    if not si_no("¿Está bien?", True):
        print("\n  Sin problema: volvemos a empezar este paso.\n")
        return paso_plan(n, t, cur, tasa, medido)

    hoy = date.today()
    prox = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, min(payday, 28))
    plan = {
        "_meta": "Tu plan. Generado por motor/setup.py — edítalo cuando cambie algo. "
                 "Está en .gitignore: nunca se sube.",
        "updated": hoy.isoformat(),
        "income_monthly_usd": ingreso, "payday": payday,
        "moneda_local": cur,
        "debt": {"total_original_usd": deuda_total or 0, "interest": "0%",
                 "creditors": deudas},
        "colchon": {"meta_usd": colchon, "rail": "Cuenta de ahorro en USD"},
        "dca": {"split": {"btc": 0.5, "index": 0.5},
                "btc_rail": "Exchange", "index_rail": "Wallbit (SPY)"},
        "plan_by_payday": [],
        "milestones": {
            "debt_zero": prox.isoformat() if deuda_total else hoy.isoformat(),
            "colchon_done": (hoy + timedelta(days=365)).isoformat(),
            "dca_full": (hoy + timedelta(days=400)).isoformat()},
        "budget": {
            "_note": "DOS BALDES: los fijos caen en bloque y NO cuentan al ritmo diario. "
                     "El balde diario es el único número a vigilar. techo = fijos + variable.",
            "techo_total_bs": techo, "techo_diario_bs": round(variable / 30),
            "fijos_total_bs": fijos_total, "variables_total_bs": variable,
            "fijos_bs": fijos or {"Sin fijos": 0},
            "fijos_match": {},
            "variables_bs": {"Día a día": variable},
            "gasto_real_medido_bs_mes": medido or 0,
            "gasto_real_neto_onetimes_bs_mes": medido or 0,
            "restriccion_real": {"fijos_pendientes_bs": fijos_total}},
    }
    if not fijos:
        plan["budget"]["fijos_bs"] = {}
        plan["budget"]["fijos_total_bs"] = 0
        plan["budget"]["variables_total_bs"] = techo
        plan["budget"]["techo_diario_bs"] = round(techo / 30)
    return plan if escribir("plan.json", plan) else None


def paso_cuentas(n, t, cur):
    titulo(n, t, "Cuentas que Wallbit no ve")
    prev = leer("manual-balances.json")
    if prev and not si_no("Ya tienes manual-balances.json. ¿Lo rehago?", False):
        ok("Conservo el que tenías.")
        return prev
    nota("Tu banco local, un exchange, efectivo. Si no tienes, ponle 'listo'.")
    cuentas = []
    while True:
        nom = preguntar("  Nombre de la cuenta (o 'listo')", "listo")
        if nom.lower() in ("listo", "no", "fin", "ninguna"):
            break
        m = preguntar(f"  Saldo de {nom}", 0, v_monto)
        c = preguntar(f"  ¿En qué moneda? (USD / {cur})", cur).upper()
        k = "invertido" if si_no(f"  ¿{nom} está invertido (no lo vas a gastar)?", False) else "liquido"
        cuentas.append({"name": nom, "amount": m, "currency": c, "kind": k,
                        "note": "Actualízalo cuando cambie."})
    datos = {"_meta": "Cuentas que la API de Wallbit no ve. 'liquido' = puedes gastarlo hoy; "
                      "'invertido' = está trabajando. En .gitignore: nunca se sube.",
             "updated": date.today().isoformat(), "accounts": cuentas}
    return datos if escribir("manual-balances.json", datos) else None


def paso_labels_silencioso():
    if leer("tx-labels.json"):
        return True
    base = leer("ejemplos/tx-labels.example.json") or {}
    try:
        base = json.load(open(os.path.join(RAIZ, "ejemplos", "tx-labels.example.json"), encoding="utf-8"))
    except Exception:
        base = {"labels": {}, "merchant_rules": [], "exclude_from_techo": ["Deuda"]}
    base["updated"] = date.today().isoformat()
    return escribir("tx-labels.json", base)


def paso_ledger():
    """Libro de aportes: se crea vacío para que exista desde el primer día."""
    if leer("data.json") is None:
        escribir("data.json", {
            "_meta": "Libro de aportes: cada vez que pagas deuda, apartas colchón o "
                     "inviertes, queda registrado acá. En .gitignore: nunca se sube.",
            "expenses": [], "aportes": [], "ingresos": [], "checks": {}})


def paso_verificar(n, t):
    titulo(n, t, "Verificación")
    paso_ledger()
    r = subprocess.run([sys.executable, os.path.join(AQUI, "finanzas.py"), "--selftest"],
                       capture_output=True, text=True, cwd=RAIZ)
    print("\n".join("  " + l for l in r.stdout.strip().splitlines()))
    if r.returncode != 0:
        malo("La verificación falló. Arregla lo de arriba en plan.json y vuelve a correr:")
        nota("python3 motor/setup.py --doctor")
        return False
    for cmd, msg in [(["visor-data.py"], "datos de la app"), (["build.py"], "app.local.html")]:
        r = subprocess.run([sys.executable, os.path.join(AQUI, cmd[0])],
                           capture_output=True, text=True, cwd=RAIZ)
        if r.returncode != 0:
            malo(f"Falló generando {msg}: {(r.stderr or r.stdout).strip()[:200]}")
            return False
        ok(f"{msg} generado")
    return True


def doctor():
    print(f"\n{C['b']}Diagnóstico{C['_']}")
    print(C["dim"] + "─" * 66 + C["_"])
    problemas = []
    if sys.version_info < MIN_PY:
        problemas.append(("Python muy viejo", f"Instala Python {MIN_PY[0]}.{MIN_PY[1]}+"))
    else:
        ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")

    if os.environ.get("WALLBIT_API_KEY") or (os.path.exists(KEY_FILE) and open(KEY_FILE).read().strip()):
        ok("API key presente")
        if os.path.exists(KEY_FILE) and (os.stat(KEY_FILE).st_mode & 0o077):
            aviso(f"{KEY_FILE} es legible por otros usuarios")
            nota(f"chmod 600 {KEY_FILE}")
    else:
        problemas.append(("Falta la API key de Wallbit — sin ella nada funciona",
                          "Sácala en https://developer.wallbit.io/dashboard/ "
                          "y corre: python3 motor/setup.py"))

    for f, arregla in [("plan.json", "python3 motor/setup.py"),
                       ("manual-balances.json", "python3 motor/setup.py"),
                       ("tx-labels.json", "cp ejemplos/tx-labels.example.json tx-labels.json")]:
        if leer(f) is None:
            problemas.append((f"Falta {f}", arregla))
        else:
            ok(f)

    snap = leer("wallbit-snapshot.json")
    if not snap:
        problemas.append(("Nunca sincronizaste", "python3 motor/finanzas.py --sync"))
    else:
        try:
            h = (datetime.now(timezone.utc) - datetime.fromisoformat(snap["synced_at"])).total_seconds() / 3600
            (ok if h < 48 else aviso)(f"Último sync hace {h:.0f} h")
            if h >= 48:
                nota("python3 motor/finanzas.py --sync")
        except Exception:
            aviso("El snapshot existe pero no pude leer su fecha")

    if not problemas:
        r = subprocess.run([sys.executable, os.path.join(AQUI, "finanzas.py"), "--selftest"],
                           capture_output=True, text=True, cwd=RAIZ)
        print("\n".join("  " + l for l in r.stdout.strip().splitlines()))
        if r.returncode == 0:
            print(f"\n  {C['ok']}Todo en orden.{C['_']}\n")
            return 0
        problemas.append(("La verificación no pasa", "Mira el detalle de arriba"))

    print(f"\n  {C['err']}{len(problemas)} problema(s):{C['_']}")
    for p, a in problemas:
        print(f"    · {p}\n      → {C['b']}{a}{C['_']}")
    print()
    return 1


def main():
    if "--doctor" in sys.argv:
        sys.exit(doctor())
    if "--reset" in sys.argv:
        print()
        if si_no("Esto borra plan.json, manual-balances.json y tx-labels.json. ¿Seguro?", False):
            for f in ("plan.json", "manual-balances.json", "tx-labels.json",
                      "state.json", "wallbit-snapshot.json"):
                p = os.path.join(RAIZ, f)
                if os.path.exists(p):
                    os.unlink(p)
                    ok(f"borrado {f}")
            nota("Tu API key NO se borró. Para eso: rm ~/.finanzas/wallbit.key")
        print()
        return

    T = 7
    print(f"\n{C['b']}  Mi plata · instalación{C['_']}")
    print(f"  {C['dim']}Son {T} pasos. Enter acepta el valor entre corchetes.")
    print(f"  Puedes cortar con Ctrl-C: nada queda a medias.{C['_']}")

    paso_python(1, T)
    key = paso_key(2, T)
    if not key:
        print(f"\n  {C['err']}Sin key no puedo seguir.{C['_']} Consíguela y vuelve a correr esto.\n")
        sys.exit(1)
    cur, tasa = paso_moneda(3, T, key)
    MONEDA[0] = cur
    medido = paso_medir(4, T, key, tasa)
    if not paso_plan(5, T, cur, tasa, medido):
        sys.exit(1)
    if paso_cuentas(6, T, cur) is None:
        sys.exit(1)
    paso_labels_silencioso()
    if not paso_verificar(7, T):
        sys.exit(1)

    print(f"\n{C['ok']}{C['b']}  Listo.{C['_']}\n")
    destino = os.path.join(RAIZ, "app.local.html")
    abierto = False
    try:
        import webbrowser
        abierto = webbrowser.open("file://" + destino)
    except Exception:
        pass
    if abierto:
        ok("Te abrí el tablero en el navegador.")
        nota(f"Está en {destino} — guárdalo en favoritos.")
    else:
        print("  Abre tu tablero:")
        print(f"    {C['b']}open app.local.html{C['_']}          (o con doble clic)")
    atajo = os.path.join(RAIZ, "actualizar.sh")
    try:
        with open(atajo, "w") as f:
            f.write("#!/bin/sh\n# Refresca tus datos y regenera el tablero.\n"
                    'cd "$(dirname "$0")" || exit 1\n'
                    "python3 motor/finanzas.py --sync || exit 1\n"
                    "python3 motor/visor-data.py && python3 motor/build.py\n")
        os.chmod(atajo, 0o755)
        print("\n  Para actualizarlo cuando quieras:")
        print(f"    {C['b']}./actualizar.sh{C['_']}")
    except Exception:
        print("\n  Para actualizarlo:")
        print(f"    {C['b']}python3 motor/finanzas.py --sync && python3 motor/visor-data.py && python3 motor/build.py{C['_']}")
    print("\n  Si algo deja de funcionar:")
    print(f"    {C['b']}python3 motor/setup.py --doctor{C['_']}\n")


if __name__ == "__main__":
    main()
