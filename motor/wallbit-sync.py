#!/usr/bin/env python3
"""Wallbit read-only sync para el meta-agente de finanzas tuyos.

Trae de la API pública de Wallbit (https://developer.wallbit.io):
  - saldo líquido (checking)        GET /balance/checking
  - holdings de índice/ETF (20% DCA) GET /balance/stocks  (+ valúa con /assets/{symbol})
  - tasa USD→BOB en vivo            GET /rates
  - transacciones recientes          GET /transactions
y escribe un snapshot a `wallbit-snapshot.json` en la raíz del proyecto, para que el
motor lo lea junto a `data.json`.

SEGURIDAD: la API key vive FUERA de iCloud, en ~/.finanzas/wallbit.key (o env
WALLBIT_API_KEY). Nunca se escribe a disco dentro del proyecto ni a git. Solo lectura.

Uso:
  python3 wallbit-sync.py            # sync completo → snapshot
  python3 wallbit-sync.py --check    # smoke test: solo /balance/checking
  python3 wallbit-sync.py --days 90  # ventana de transacciones (default 60)
"""
import json, os, sys, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone

BASE = "https://api.wallbit.io/api/public/v1"
# Los datos y la configuración viven en la RAÍZ del repo; el código, en motor/.
# MI_PLATA_DIR redirige esa raíz: así el generador del demo puede correr ESTE MISMO motor
# contra datos sintéticos en una carpeta temporal, en vez de mantener una segunda
# implementación a mano que se desincroniza en silencio (fue justo lo que pasó con el colchón).
DIR = os.environ.get("MI_PLATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(DIR, "wallbit-snapshot.json")
KEY_FILE = os.path.expanduser("~/.finanzas/wallbit.key")


def get_key():
    k = os.environ.get("WALLBIT_API_KEY")
    if k:
        return k.strip()
    if os.path.exists(KEY_FILE):
        return open(KEY_FILE).read().strip()
    sys.exit(
        "✗ No hay API key.\n"
        "  Crea una en la app Wallbit → Agents → Create agent → permiso `read`,\n"
        f"  y guárdala en {KEY_FILE}\n"
        "  (o export WALLBIT_API_KEY=...). Nunca la pongas dentro del proyecto ni en git."
    )


def call(path, key, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        return None, f"HTTP {e.code} en {path}: {body}"
    except Exception as e:
        return None, f"ERR en {path}: {e}"


def main():
    key = get_key()
    args = sys.argv[1:]

    if "--check" in args:
        data, err = call("/balance/checking", key)
        if err:
            sys.exit("✗ " + err)
        print("✓ API key válida. Checking:")
        for b in data.get("data", []):
            print(f"    {b.get('currency')}: {b.get('balance')}")
        return

    days = 60
    if "--days" in args:
        days = int(args[args.index("--days") + 1])

    snap = {"synced_at": datetime.now(timezone.utc).isoformat(), "errors": []}

    # 1. Saldo líquido (checking)
    data, err = call("/balance/checking", key)
    if err:
        snap["errors"].append(err)
    else:
        snap["checking"] = data.get("data", [])
        snap["usd_liquid"] = sum(
            float(b.get("balance", 0)) for b in data.get("data", []) if b.get("currency") == "USD"
        )

    # 2. Holdings de índice/ETF + valuación
    data, err = call("/balance/stocks", key)
    if err:
        snap["errors"].append(err)
    else:
        holdings = data.get("data", [])
        valued, total = [], 0.0
        for h in holdings:
            sym, shares = h.get("symbol"), float(h.get("shares", 0))
            ad, aerr = call(f"/assets/{urllib.parse.quote(sym)}", key)
            price = None
            if not aerr and ad:
                a = ad.get("data", ad)
                price = a.get("price") or a.get("last_price") or a.get("current_price")
            val = (float(price) * shares) if price else None
            if val:
                total += val
            valued.append({"symbol": sym, "shares": shares, "price": price, "value_usd": val})
        snap["stocks"] = valued
        snap["stocks_value_usd"] = round(total, 2) if total else None

    # 3. Tasa USD→BOB en vivo (reemplaza el scrape de dolarblue)
    data, err = call("/rates", key, {"source_currency": "USD", "dest_currency": "BOB"})
    if err:
        snap["errors"].append(err)
    else:
        r = data.get("data", {})
        snap["fx_usd_bob"] = r.get("rate")
        snap["fx_updated_at"] = r.get("updated_at")

    # 4. Transacciones recientes (para auto-import propuesto, nunca silencioso)
    frm = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    txs, page, pages, count, perr = [], 1, 1, None, None
    while page <= pages and page <= 25:  # tope de seguridad: 25 páginas (1.250 tx)
        data, err = call("/transactions", key, {"from_date": frm, "to_date": to, "limit": 50, "page": page})
        if err:
            perr = err
            break
        inner = data.get("data", {})
        rows = inner.get("data", inner if isinstance(inner, list) else [])
        txs.extend(rows)
        if isinstance(inner, dict):
            pages = inner.get("pages", 1) or 1
            count = inner.get("count", len(txs))
        if not rows:
            break
        page += 1
    if perr and not txs:
        snap["errors"].append(perr)
    else:
        snap["transactions"] = txs
        snap["tx_count"] = count if count is not None else len(txs)
        snap["tx_window"] = {"from": frm, "to": to}
        if perr:
            snap["errors"].append(perr + " (parcial)")

    with open(SNAPSHOT, "w") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)

    # Resumen accionable
    print(f"\n  Wallbit snapshot → {os.path.basename(SNAPSHOT)}")
    if "usd_liquid" in snap:
        print(f"    Líquido USD:     ${snap['usd_liquid']:,.2f}")
    if snap.get("stocks_value_usd") is not None:
        print(f"    Índice/ETF:      ${snap['stocks_value_usd']:,.2f}")
    if snap.get("fx_usd_bob"):
        print(f"    Tasa USD→BOB:    {snap['fx_usd_bob']}")
    if "tx_count" in snap:
        print(f"    Transacciones:   {snap['tx_count']} (últimos {days}d)")
    if snap["errors"]:
        print("    ⚠ errores:")
        for e in snap["errors"]:
            print("      -", e)
    print()


if __name__ == "__main__":
    main()
