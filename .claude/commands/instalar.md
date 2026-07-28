---
description: Instalar Mi plata desde cero, guiando a la persona paso a paso
---
Ayudá a la persona a dejar esto funcionando.

1. Verificá el estado actual — no asumas nada:
   `python3 motor/setup.py --doctor`
2. Si falta configuración, dile que corra `python3 motor/setup.py` **ella misma**
   en su terminal. Es interactivo y le va a pedir su API key: no lo corras ti ni le
   pidas que te la pegue en el chat.
3. Cuando termine, confirma con `--doctor` y muéstrale su primer resumen con
   `python3 motor/finanzas.py`.

Si algo falla, el doctor ya devuelve el comando exacto de arreglo: úsalo en vez de
improvisar un diagnóstico. Nunca imprimas el contenido de `~/.finanzas/wallbit.key`.
