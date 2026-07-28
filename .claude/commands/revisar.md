---
description: Auditar que los números cuadren, recalculando por fuera del motor
---
1. `python3 motor/finanzas.py --selftest` — 24 invariantes.
2. Verificación independiente: recalcula desde `wallbit-snapshot.json` **sin usar las
   funciones del motor** y compara. Validar un motor con el mismo motor no prueba nada.
   Mínimo: activos = invertido + líquido · Σ cuentas = activos · Σ categorías = gasto
   variable · Σ serie diaria = gasto variable · Σ acreedores = deuda original ·
   techo = fijos + variable · días restantes = de hoy al día de cobro.
3. Reportá solo lo que NO cuadra, con la diferencia exacta.

Si encontrás un error de cálculo, arréglalo en `motor/finanzas.py` y agrega un
invariante al selftest para que no vuelva a pasar desapercibido.
