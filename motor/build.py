#!/usr/bin/env python3
"""Incrusta los datos dentro de app.html para poder abrirla sin servidor.

  python3 motor/build.py           -> app.local.html  (TUS datos, en .gitignore)
  python3 motor/build.py --demo    -> index.html      (datos de ejemplo, publicable)

La app también sabe leer state.json / demo.json por fetch cuando la sirves por HTTP;
esto es sólo para el caso de abrirla con doble clic (file:// bloquea fetch).
"""
import io, json, os, sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
demo = "--demo" in sys.argv
datos = os.path.join(RAIZ, "demo.json" if demo else "state.json")
salida = os.path.join(RAIZ, "index.html" if demo else "app.local.html")

if not os.path.exists(datos):
    sys.exit(f"Falta {os.path.basename(datos)}. Corre primero:  python3 motor/visor-data.py"
             + (" --demo" if demo else ""))

plantilla = io.open(os.path.join(RAIZ, "app.html"), encoding="utf-8").read()
estado = json.load(open(datos, encoding="utf-8"))
# El marcador va como comentario (`/*__STATE__*/null`) para que app.html SIN construir
# también sea JavaScript válido: servida por HTTP la app busca los datos sola, y una
# plantilla rota dejaba la página en blanco sin decir por qué.
MARCA = "/*__STATE__*/null"
if MARCA not in plantilla:
    sys.exit(f"app.html no trae el marcador {MARCA}; no sé dónde incrustar los datos.")
io.open(salida, "w", encoding="utf-8").write(
    plantilla.replace(MARCA, json.dumps(estado, ensure_ascii=False, separators=(",", ":"))))
print(f"{os.path.basename(salida)}  ·  {'datos de ejemplo' if demo else 'TUS DATOS — no lo subas'}")
