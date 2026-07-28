---
description: Resumen del estado financiero de la persona, con el número del día
---
1. `python3 motor/finanzas.py --sync`
2. Leé el resultado y responde en 5–8 líneas: cuánto tiene, cuánto puede gastar hoy,
   si va en ritmo, y qué le toca hacer.

Reglas:
- El número diario sale del motor. No lo recalcules a mano.
- Si `--alerta` sale con código 1, está fuera de ritmo: díselo con la cifra, sin sermón.
- Si hay retiros a banco sin identificar, avísale que ese monto **no está contado como
  gasto** y pregúntale qué fueron.
