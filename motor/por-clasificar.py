#!/usr/bin/env python3
"""Lo que describiste y falta encasillar.

El reparto de trabajo: tú escribes QUÉ fue un movimiento — eso sólo lo sabes tú —, y meterlo
en la taxonomía es mecánico, así que lo hace tu agente. Este script es el puente: lista lo
descrito y sin clasificar, con el monto, el comercio y las categorías válidas al lado.

  python3 por-clasificar.py              # qué falta
  python3 por-clasificar.py --json       # lo mismo, para leerlo desde el agente
"""
import json, os, sys, urllib.request

# Los datos viven en la RAÍZ del repo; el código, en motor/.
DIR = os.environ.get("MI_PLATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://localhost:8765"


def leer(n, d=None):
    try:
        return json.load(open(os.path.join(DIR, n), encoding="utf-8"))
    except Exception:
        return d


def pendientes():
    tl = leer("tx-labels.json", {}) or {}
    st = leer("state.json", {}) or {}
    desc = tl.get("descripciones", {}) or {}
    porUuid = {p["uuid"]: p for p in st.get("pendientes", [])}
    cats = [k for k in (tl.get("_categories", {}) or {}) if not k.startswith("_")]
    out = []
    for uuid, d in desc.items():
        p = porUuid.get(uuid, {})
        out.append({
            "uuid": uuid,
            "texto": d.get("texto", ""),
            "descrito_el": d.get("fecha", ""),
            "fecha": p.get("fecha", ""), "hora": p.get("hora", ""),
            "bs": p.get("bs"), "usd": p.get("usd"),
            "comercio": p.get("nombre", ""), "banco": p.get("banco", ""),
            "metodo": p.get("metodo", ""), "detalle": p.get("detalle", ""),
        })
    out.sort(key=lambda x: (x.get("fecha") or "", x.get("bs") or 0), reverse=True)
    return out, cats


def clasificar(uuid, cat):
    """Aplica la categoría vía el servidor — nunca escribiendo el JSON a mano, para que
    pase por la validación, el backup y la regeneración del estado."""
    req = urllib.request.Request(
        API + "/label", method="POST",
        data=json.dumps({"uuid": uuid, "cat": cat}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    if "--clasificar" in sys.argv:
        i = sys.argv.index("--clasificar")
        uuid, cat = sys.argv[i + 1], sys.argv[i + 2]
        print(json.dumps(clasificar(uuid, cat))[:200])
        sys.exit(0)

    items, cats = pendientes()
    if "--json" in sys.argv:
        print(json.dumps({"items": items, "categorias": cats}, ensure_ascii=False, indent=1))
        sys.exit(0)

    if not items:
        print("\n  Nada por clasificar. Todo lo que describiste ya tiene categoría.\n")
        sys.exit(0)

    print(f"\n  {len(items)} movimiento(s) descritos, falta encasillarlos\n")
    for x in items:
        monto = f"{x['bs']:,.0f} Bs".replace(",", ".") if x.get("bs") else "?"
        print(f"  · {x['fecha']} {x['hora']}   {monto:>12}   {x['comercio'][:34]}")
        print(f"      dijo: «{x['texto']}»")
        print(f"      uuid: {x['uuid']}")
    print(f"\n  Categorías válidas: {', '.join(cats)}")
    print(f"\n  Para aplicar:  python3 por-clasificar.py --clasificar <uuid> <categoría>\n")
