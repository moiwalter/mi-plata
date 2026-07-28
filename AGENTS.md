# Instrucciones para agentes

Este archivo es para ti, el asistente de IA que está trabajando en este repositorio.
La persona que te está pidiendo ayuda quiere entender o controlar **su propia plata**.
Lee esto entero antes de tocar nada.

---

## Qué es esto

Un centro de control de finanzas personales conectado a la **API pública de Wallbit**.
Un motor determinista en Python (cero dependencias) baja los datos, calcula, y una app
de una sola página los dibuja.

**La matemática vive en `motor/finanzas.py`, no en tu cabeza.** No calcules saldos,
promedios ni proyecciones mentalmente para responderle: corre el motor y lee el
resultado. Si un número te parece raro, el problema está en el motor o en los datos —
arréglalo ahí, no lo compenses en la respuesta.

### Tú eres una de las dos puertas

Este sistema se maneja desde dos lados, y conviene que sepas cuál eres:

- **Tú** lo instalas, lo conectas y lo gobiernas. Aquí llegan las preguntas —
  *«¿me alcanza para el viaje?»*, *«clasifica lo que anoté»*, *«¿por qué bajó mi número?»*.
  Responder es justo lo que un tablero no puede hacer.
- **El tablero** (`localhost:8765`) es el día a día a toques: ver el número, decir qué fue
  un gasto, corregir un saldo, traer lo nuevo con **↻**.

Los dos escriben en los **mismos archivos**, así que lo que hace uno lo ve el otro de
inmediato. Antes de preguntarle por chat qué fue un movimiento, fíjate si ya está en la
cola del tablero: resolverlo ahí es un toque, contestarte por chat es un párrafo.

Todo corre **en su computadora**. No hay servidor de nadie ni cuenta que crear, y sus datos
financieros no salen de su máquina. No le prometas acceso desde el teléfono.

**Empieza siempre por leer el estado, no por preguntar.** `python3 motor/setup.py --doctor`
te dice en un comando si esto está instalado y qué falta.

---

## 🔴 Reglas duras — no las rompas nunca

**1. La API key no se imprime, no se copia, no se pega.**
Vive en `~/.finanzas/wallbit.key` (permisos 600) o en `$WALLBIT_API_KEY`. Nunca la
muestres en pantalla, ni en un mensaje, ni en un comentario, ni en un commit. Si
necesitas comprobar que existe, verifica el archivo, no su contenido:

```bash
test -s ~/.finanzas/wallbit.key && echo "key presente"    # ✅
cat ~/.finanzas/wallbit.key                               # ❌ NUNCA
```

**2. Los datos financieros de la persona no se suben a git.**
`plan.json`, `manual-balances.json`, `tx-labels.json`, `data.json`, `state.json`,
`wallbit-snapshot.json` y `app.local.html` están en `.gitignore` por una razón.
Antes de cualquier commit, comprueba que no se colaron:

```bash
git status --porcelain
```

Si ves alguno de esos archivos ahí, **paras y avisas**. No hagas `git add -A` a ciegas.

**3. `demo.json` es el único archivo con cifras que se versiona.**
Es 100% sintético (generado con semilla fija por `motor/visor-data.py --demo`). Nunca
lo regeneres a partir de los datos reales de la persona: aunque cambies los nombres, la
*forma* del gasto sigue siendo identificable.

**4. Nada de capturas ni ejemplos con cifras reales.**
Si vas a documentar o mostrar el proyecto, usa el demo.

**5. Al terminar cualquier cambio, corre la verificación.**

```bash
python3 motor/finanzas.py --selftest
```

Sale con código 0 si la plata cuadra. Si sale 1, tu cambio rompió algo: arréglalo antes
de decir que terminaste.

---

## El requisito que bloquea todo

**Sin una API key de Wallbit este proyecto no puede leer nada.** Es lo primero que hay
que resolver, antes que cualquier otra cosa.

Si la persona no la tiene, mándala a **https://developer.wallbit.io/dashboard/** y
avísale que **Wallbit la muestra una sola vez**: si no la copia ahí, tiene que generar
otra. Recomiéndale permisos de solo lectura.

**Nunca le pidas que te la pegue en el chat.** El instalador se la pide en su terminal
y la guarda en `~/.finanzas/wallbit.key` con permisos 600. Tú no necesitas verla nunca.

---

## Si la persona recién empieza

No la hagas editar JSON a mano. Dile que corra:

```bash
python3 motor/setup.py
```

Son 7 pasos, con valores por defecto en todo. Mide su gasto real de los últimos 35 días
y le propone un presupuesto sobre esa base. Es idempotente y no deja estados a medias.

Si algo no anda:

```bash
python3 motor/setup.py --doctor
```

Diagnostica y devuelve el comando exacto de arreglo. **Corre esto antes de improvisar
un diagnóstico propio.**

---

## El modelo de dominio

Entender esto evita el 90% de las respuestas equivocadas.

### Ciclo

No es el mes calendario. Va del **día de cobro** al mismo día del mes siguiente
(`plan.json → payday`). Un ciclo dura entre 28 y 31 días; nunca asumas 30.

### Dos baldes

El gasto se parte en dos y **no son intercambiables**:

- **Fijos** — alquiler, servicios, suscripciones. Caen en bloque. **No cuentan contra
  el ritmo diario**: pagar el alquiler el día 3 no significa "te pasaste".
- **Balde diario** — todo lo demás, repartido entre los días que faltan. Es el **único
  número que la persona tiene que vigilar**.

Invariante que el motor verifica solo: `techo = fijos + balde diario`. Si tocas uno,
recalcula los otros o el selftest falla.

### El tercer balde: lo ya decidido

Un cumpleaños o un viaje con fecha y monto **no son indisciplina: son gastos decididos**.
Viven en `plan.json → budget.excepcionales.items`. El motor los **aparta antes** de repartir
lo que queda entre los días, y expone dos números: `caja.diario_a_cero` (sin apartar nada,
de ahí comen el selftest y la alerta) y `excepcionales.diario_con_reserva` (el honesto, el
que la app muestra grande).

**Un excepcional lleva cuenta de lo que ya se pagó.** Cuando etiquetas un movimiento le
puedes pasar `excepcional: "<id>"`; el motor suma esos pagos y sólo reserva
`bs − pagado_bs`. Sin eso, comprar el pasaje del viaje **bajaba la caja y encima seguía
reservando el pasaje entero**: la misma plata apartada dos veces y el número diario
mintiendo hacia abajo.

El gasto **igual cuenta en la curva del ciclo**. Gastado es gastado; lo único que cambia es
que se deja de reservar plata para algo ya comprado.

### Describir ≠ clasificar

Son dos trabajos distintos y el sistema los separa a propósito:

- **Qué fue un movimiento** sólo lo sabe la persona, y lo sabe *ahora*. Lo escribe con sus
  palabras en la app y se guarda en `tx-labels.json → descripciones`. El movimiento **sigue
  en la cola**, ahora con contexto.
- **Meterlo en la taxonomía** es mecánico y **te toca a ti**. `motor/por-clasificar.py` lista
  lo descrito y sin clasificar; `--clasificar <uuid> "<categoría>"` lo aplica.

Al clasificar, la descripción se **absorbe** como nota del movimiento y sale de pendientes.
Clasificar lo que ya describió **no es decidir por ella: es transcribir**. Lo que sí está
prohibido es inventar la categoría de algo que no explicó.

### Dos límites distintos

Cuando alguien pregunta "¿cuánto puedo gastar?", hay dos respuestas y confundirlas es
un error grave:

- **Según el plan** — lo que queda del balde diario. Respetarlo preserva el ahorro del ciclo.
- **Según la caja** — lo que el efectivo aguanta. Llega al día de cobro con cero.

Gastar entre uno y otro no deja a nadie sin comer: **deja sin ahorro ese mes**. Dilo así.

### La taxonomía es suya, no tuya

Las categorías viven en `tx-labels.json → _categories` y de ahí salen los botones de la
cola. La plantilla trae una **semilla genérica** para que el día uno funcione; a partir de
ahí es de ella: las renombra, las borra, agrega las que le falten.

**No inventes categorías nuevas por tu cuenta.** Si un movimiento no encaja en ninguna,
**propón el nombre y espera el sí** antes de escribirlo. Una taxonomía que crece sola
termina con quince etiquetas parecidas —"Comida", "Comidas", "Super", "Supermercado"— y un
desglose que no dice nada. Que falte una categoría es información: significa que apareció
una parte de su vida que el sistema todavía no nombra, y ese nombre lo pone ella.

Señal de que hace falta una: si **"Otros" se está llenando**, no es que gaste en cosas
raras — es que falta una categoría con nombre propio.

Al agregar una, respeta la forma: `"Nombre": {"fijo": bool, "desc": "..."}`. `fijo: true`
la saca del ritmo diario (cae en bloque, como el alquiler). Si además no es consumo
—deuda, ahorro, inversión— va también en `exclude_from_techo`.

### Qué es gasto y qué no

| Movimiento | ¿Es gasto? |
|---|---|
| Pago QR, cargo de tarjeta | Sí |
| Pago de deuda | **No** — es traslado de pasivo. `exclude_from_techo` |
| Aporte a colchón o inversión | **No** — sigue siendo suyo |
| Envío on-chain a su propio exchange | **No** — es ahorro |
| Envío on-chain a otro lado | Depende: mira `tx-labels.json → addresses` |
| Transferencia saliente a otra persona | Sí |
| Retiro a su banco | **Desconocido** hasta que se etiquete. Ver abajo |

### El punto ciego de los retiros

Wallbit ve que la plata salió al banco, **no en qué terminó**. Un retiro sin etiquetar
no cuenta como gasto — y eso puede ser mucha plata invisible. Si ves montos grandes en
`caja.retiros_sin_identificar`, **pregunta qué fueron** y guarda la respuesta en
`tx-labels.json → labels` por `uuid`. Nunca vuelvas a preguntar por uno ya etiquetado.

### La app también escribe

Antes esto era de sólo lectura y todo lo que el motor no sabía clasificar se resolvía
por chat. Resultado previsible: nadie lo resolvía y el tablero se llenaba de "sin
identificar". Ahora **la app escribe**, contra el servidor local (`motor/servidor.py`):

| Endpoint | Qué hace | Dónde escribe |
|---|---|---|
| `POST /label` | etiqueta una transacción (`{uuid, cat, label?, nota?}`) o la desetiqueta (`{uuid, accion:"borrar"}`) | `tx-labels.json → labels[uuid]` |
| `POST /manual-balances` | actualiza los saldos que la API no ve (`{accounts:[{name, amount}]}`) | `manual-balances.json` |

Reglas de esos endpoints, que valen también para ti:

- La categoría tiene que existir en `tx-labels.json → _categories`. Categoría
  desconocida = **400**, no una categoría nueva inventada.
- Toda escritura es atómica y deja backup del día (`archivo.bak-YYYY-MM-DD`).
- Después de escribir, el servidor **regenera `state.json` con el motor** y devuelve el
  estado nuevo. La app no recalcula nada por su cuenta: dibuja lo que devolvió el motor.
- Si trabajas sobre la app, mantén esa regla. Un número calculado en JavaScript es un
  número que va a divergir del motor.

---

## Trampas reales (ya costaron caro)

**Zona horaria.** Wallbit sella en UTC. Si la persona vive en UTC−4 y gasta de noche,
todo lo posterior a las 20:00 locales cae al día siguiente — y lo del último día del
ciclo se va al ciclo siguiente. El motor convierte con `fecha_local()`. **Si escribes
código que compare fechas de transacciones, usa esa función, no `created_at[:10]`.**

**Dos tipos de cambio.** `/rates` devuelve la tasa de **retiro a banco**. Los pagos QR
liquidan a otra, normalmente mejor. El motor mide la efectiva de los QR de los últimos
3 días. No uses la de la API para valuar gasto.

**Gasto en dólares.** `CARD_SPENT` liquida en USD, no en moneda local. Hay que
multiplicar por la tasa o las suscripciones aparecen a una fracción de su valor.

**Tipos de movimiento nuevos.** Todo tipo que devuelva la API tiene que estar en
`KNOWN_TYPES` (`motor/finanzas.py`). Si aparece uno desconocido, el selftest **falla a
propósito**: es preferible a perder plata en silencio. Si pasa, clasifica el tipo nuevo
en el conjunto que corresponda y documenta por qué.

**Nunca escribas `demo.json` a mano.** Se COCINA: `motor/demo-fuente.py` inventa las
respuestas crudas de la API y **el motor de siempre las procesa** (`visor-data.py --demo`).
Escribirlo a mano crea una segunda implementación, y las segundas implementaciones se
desincronizan en silencio — así fue como la página pública repartía el fondo de emergencia
como plata gastable y mostraba un número diario 50% más alto que el producto real. Si el
demo está mal, el bug está en el motor o en el generador.

**Si tocas un cálculo, tócalo en un solo lugar.** El mismo motor produce los datos reales y
los del demo. Antes de dar por buena una diferencia entre dos copias del código, comprueba
que sea intencional: parsea ambas con `ast`, neutraliza las constantes string, borra
docstrings y diffea. Lo que no sea una ruta o una lista local es drift.

**El charset y la caché no son detalle.** La app declara `<meta charset="utf-8">` como
primera etiqueta —tiene que caer en los primeros 1024 bytes o el navegador ya adivinó y
parte cada acento en dos— y el servidor manda `charset` y `no-store` en **todas** las
respuestas, no sólo en las de la API. Sin lo segundo, la persona cambia algo, recarga, y
sigue viendo la versión vieja sin entender por qué.

---

## Tareas frecuentes

```bash
# levantar el tablero operable (el que permite etiquetar)
python3 motor/servidor.py --open        # http://localhost:8765/

# actualizar todo y ver el tablero
python3 motor/finanzas.py --sync && python3 motor/visor-data.py && python3 motor/build.py

# resumen en texto (para responderle sin abrir la app)
python3 motor/finanzas.py

# lo que YA describió en la app y falta encasillar (empieza por acá)
python3 motor/por-clasificar.py
python3 motor/por-clasificar.py --clasificar <uuid> "<categoría>"

# movimientos sin ninguna explicación
python3 motor/finanzas.py --import      # propone; NO escribe nada solo

# regenerar el demo público (lo COCINA el motor; nunca lo edites a mano)
python3 motor/visor-data.py --demo && python3 motor/build.py --demo

# ¿va fuera de ritmo? (calla si va bien — sirve para cron)
python3 motor/finanzas.py --alerta

# verificar que la plata cuadre
python3 motor/finanzas.py --selftest
```

**`--import` propone, no decide.** Muéstrale lo que salió, espera su respuesta, y recién
ahí escribe las etiquetas. Nunca clasifiques su gasto por tu cuenta.

**Antes de preguntar por chat, mándala a la app.** La cola de "Por identificar" está
arriba de todo y se resuelve con un toque por movimiento. Preguntarle uno por uno en el
chat es más lento para ella y más caro para ti.

**Lo que ya describió es otra cosa.** Ahí la parte difícil está hecha: sabe qué fue y lo
escribió. Encasillarlo es transcribir, no decidir — hazlo tú y no se lo devuelvas como
pregunta. Si un movimiento es parte de un gasto ya decidido (el pasaje de un viaje),
pásale también `excepcional` con su id o el sistema seguirá apartando plata para algo ya
comprado.

---

## Mapa de archivos

```
app.html                la interfaz. Un archivo. SVG generado, sin librerías ni CDN
demo.json               datos sintéticos — lo único con cifras versionado
index.html              app.html + demo.json, para ver el proyecto sin configurar nada

motor/
  setup.py              instalación guiada · --doctor · --reset
  wallbit-sync.py       lee la API           -> wallbit-snapshot.json
  finanzas.py           TODA la matemática   -> resumen, --selftest, --alerta, --json
  visor-data.py         arma los datos de la app -> state.json  (o demo.json con --demo)
  servidor.py           sirve la app y recibe lo que escribe (/label, /manual-balances)
  build.py              incrusta los datos en la app -> app.local.html / index.html
  demo-fuente.py        inventa respuestas CRUDAS de la API para cocinar el demo
  por-clasificar.py     lo que la persona describió y falta encasillar

ejemplos/               plantillas comentadas de los 3 archivos de configuración
```

**Los datos viven en la raíz; el código en `motor/`.** Si agregas un script que llame a
otro, usa `AQUI` (la carpeta `motor/`) para código y `DIR` (la raíz) para datos.

Dos variables de entorno, sólo para el generador del demo — **no las uses en uso normal**:

| | |
|---|---|
| `MI_PLATA_DIR` | redirige la raíz de datos, para correr el motor contra datos sintéticos |
| `MI_PLATA_HOY` | congela el "hoy" (`hoy()` / `ahora()` en `finanzas.py`) |

Si tocas una llamada de fecha, **hazla pasar por `hoy()`**. Cuando el selftest miraba el
reloj real mientras el resto miraba la fecha congelada, inventaba tres fallos que no existían.

---

## Cómo hablarle a la persona

Es su plata: no la sermonees y no adornes las malas noticias. Si va a quedarse corta,
díselo con el número. Si un dato no se puede saber (típicamente: en qué terminó un
retiro), di que no se puede saber en vez de estimarlo y presentarlo como un hecho.

Cuando cambies algo del cálculo, explica **qué número cambia y por qué**, no solo qué
archivo tocaste.
