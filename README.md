# Mi plata

Un centro de control para tus finanzas personales, conectado a la **API pública de
[Wallbit](https://developer.wallbit.io)**. Tus pagos QR y cargos de tarjeta se capturan
solos: no hay nada que anotar a mano.

### ▸ [Pruébalo ahora](https://moiwalter.github.io/mi-plata/)

Demo en vivo con datos de ejemplo, sin instalar ni configurar nada.

---

## Se maneja desde dos lados

No son dos programas: es el mismo sistema con dos puertas, y cada una sirve para algo
distinto. Escriben en los mismos archivos, así que lo que haces en una la ve la otra al
instante.

| | |
|---|---|
| **Tu agente**<br>(Claude Code, Codex) | Lo **instala**, lo conecta a tu cuenta y lo **gobierna**. Ahí le hablas: *«¿me alcanza para el viaje?»*, *«clasifica lo que anoté»*, *«¿por qué bajó mi número?»*. Es lo que un tablero no puede hacer: responder. |
| **El tablero**<br>(`localhost:8765`) | El **día a día, a toques**. Ver el número, decir qué fue un gasto, corregir un saldo, traer lo nuevo de Wallbit con **↻**. Sin escribir un comando. |

**La regla: si es una pregunta, al agente; si es un toque, al tablero.**

Las dos corren **en tu computadora**. Esto no vive en internet, no hay servidor de nadie ni
cuenta que crear: tus datos financieros no salen de tu máquina. La contrapartida es que el
tablero se abre donde lo estés corriendo — no es una app que lleves en el teléfono.

El agente no es un extra opcional — es cómo se instala y cómo se le pregunta. El tablero
tampoco es sólo para mirar: **escribe**. Cada botón guarda en tu archivo y vuelve a correr
el motor. Después de instalar no necesitas volver a la terminal.

Los atajos del agente viven en `.claude/commands/` y las reglas duras en
[`AGENTS.md`](AGENTS.md), que Claude Code y Codex leen igual.

---

## Antes de empezar: necesitas una API key de Wallbit

Es **el único requisito**. Sin ella esto no puede leer nada y no funciona.

1. Entra a **[developer.wallbit.io/dashboard](https://developer.wallbit.io/dashboard/)**
2. Inicia sesión con tu cuenta de Wallbit
3. Crea una key. Si te deja elegir permisos, dale **solo lectura**: este proyecto
   nunca escribe en tu cuenta.
4. **Cópiala en ese momento** — Wallbit la muestra una sola vez.

> ¿Todavía no tienes cuenta en Wallbit? Entonces esto no es para ti todavía.
> El proyecto lee de tu cuenta; no reemplaza al banco.

Guárdala donde el instalador la va a buscar:

```bash
mkdir -p ~/.finanzas && chmod 700 ~/.finanzas
echo "TU_API_KEY" > ~/.finanzas/wallbit.key && chmod 600 ~/.finanzas/wallbit.key
```

O simplemente corre el instalador y pégasela cuando te la pida.

---

## Qué responde

| | |
|---|---|
| **¿Cuánto puedo gastar hoy?** | lo primero y lo más grande: un solo número, sobre la plata real que queda |
| **¿Qué fue este movimiento?** | la cola de lo que el sistema no supo clasificar — se resuelve con un toque |
| **¿Cuánto tengo?** | patrimonio, cuánto está invertido, cuánto puedes tocar hoy |
| **¿En qué se me va?** | categorías, día por día, y el registro completo |
| **¿Cómo voy contra el plan?** | curva de consumo con proyección a fin de mes |

---

## No es un tablero: se opera

Un tablero de sólo lectura acumula basura. Aparece un retiro que no sabes en qué
terminó, no hay forma de anotarlo desde ahí, y al mes tienes miles sin identificar —
con el gasto del mes mintiendo por ese monto.

Así que la app **escribe**:

- **La cola "Por identificar" va arriba de todo**, antes que cualquier gráfico, con
  fecha y **hora local**, monto en las dos monedas, comercio, banco y método. Un toque
  en la categoría y queda guardado por `uuid` en `tx-labels.json` — no se vuelve a
  preguntar por ese movimiento nunca. Con nota opcional, y con deshacer.
- **Los saldos que la API no ve** (tu banco, un exchange) se editan en la misma página.
  Antes había que abrir un JSON en el editor; un saldo que se corrige así no se corrige.

Cada escritura la recibe el servidor local, que valida, guarda de forma atómica con
backup, **vuelve a correr el motor** y devuelve el estado recalculado. La app no hace
una sola cuenta por su cuenta.

---

## Se explica solo la primera vez

Un tablero de finanzas tiene un problema de arranque: cada número es una decisión de
diseño («¿por qué 182 y no 298?»), y sin explicarla el que llega ve cifras sueltas y se va.

La primera vez que abres la app arranca un recorrido que **no cuenta qué hace el tablero,
cuenta por qué cada número está calculado como está**: por qué el diario no es tu saldo,
por qué lo ya decidido se aparta antes, por qué el colchón no cuenta. También explica las
dos puertas —agente y tablero— y para qué sirve cada botón, que es lo que más se malentiende.

Va contra la pantalla real —cada paso hace scroll a su sección y la resalta— y los
ejemplos salen de los datos que tengas cargados, así que te habla de **tus** cifras, no de
una ilustración. El último paso es cómo conectar tu cuenta con tu API key de Wallbit.

Se reabre cuando quieras con el botón **?** del encabezado. Flechas ←/→ para moverte,
`Esc` para salir.

---

## Instalación

Necesitas **Python 3.9 o superior**. Nada más: cero dependencias, solo la librería estándar.

```bash
git clone https://github.com/moiwalter/mi-plata.git
cd mi-plata
```

Ahora abre esa carpeta en tu agente (Claude Code, Codex) y dile **`/instalar`**. Él te pide
la API key, mide tus últimos 35 días reales y te propone el techo desde ahí.

Si prefieres hacerlo tú, es el mismo instalador:

```bash
python3 motor/setup.py
```

Eso es todo. La instalación guiada te lleva paso a paso, valida tu API key contra la
API antes de guardarla, **mide tu gasto real de los últimos 35 días** y te propone un
presupuesto con base en eso — no en una corazonada. Al terminar tienes el tablero abierto.

Si algo deja de funcionar más adelante:

```bash
python3 motor/setup.py --doctor
```

Te dice qué falta y con qué comando se arregla. Nunca vas a ver un traceback.

---

<details>
<summary><b>Configuración manual</b> (si prefieres no usar el instalador)</summary>

### 1. Tu API key de Wallbit

Sácala de [developer.wallbit.io/dashboard](https://developer.wallbit.io/dashboard/) y
guárdala **fuera del repositorio**:

```bash
mkdir -p ~/.finanzas
echo "TU_API_KEY_AQUI" > ~/.finanzas/wallbit.key
chmod 600 ~/.finanzas/wallbit.key
```

O como variable de entorno:

```bash
export WALLBIT_API_KEY="TU_API_KEY_AQUI"
```

> **Usa una key de solo lectura.** Este proyecto nunca escribe en tu cuenta: lee saldos,
> tipo de cambio y transacciones. No le des permisos de operación.

### 2. Tu configuración

```bash
cp ejemplos/plan.example.json             plan.json
cp ejemplos/manual-balances.example.json  manual-balances.json
cp ejemplos/tx-labels.example.json        tx-labels.json
```

Abre `plan.json` y pon lo tuyo: el día que cobras, tus deudas, tu meta de ahorro y
tu presupuesto. Los tres archivos están en `.gitignore` — **nunca se suben**.

### 3. Arranca

```bash
python3 motor/finanzas.py --sync      # trae tus datos y muestra el resumen
python3 motor/visor-data.py           # genera state.json para la app
python3 motor/servidor.py --open      # abre el tablero en http://localhost:8765/
```

> Usa `motor/servidor.py`, no `python3 -m http.server`: es el que recibe lo que la app
> escribe (etiquetas y saldos). Con un servidor estático la app se ve, pero no guarda.

---

## Los tres archivos que configuras

**`plan.json`** — tu plan. Cuánto ganas, qué día, a quién le debes, cuánto quieres
ahorrar y cuál es tu techo de gasto.

**`manual-balances.json`** — las cuentas que Wallbit no ve: tu banco local, un exchange,
efectivo. Marca cada una como `liquido` (puedes gastarla) o `invertido` (está trabajando).

**`tx-labels.json`** — la memoria de qué fue cada movimiento. La API vuelve a bajar las
transacciones en cada sync pero **no recuerda** cómo las clasificaste; esto sí, por `uuid`.
También lleva reglas por comercio, que se aplican solas a futuro.

Ahí adentro está `_categories`, **tu taxonomía**: de ahí salen los botones de la cola.
Viene con una semilla genérica para que el primer día funcione, pero es tuya — renómbralas,
borra las que no uses y agrega las que te falten. Si **"Otros" se te está llenando**, no es
que gastes en cosas raras: falta una categoría con nombre propio.

---

## El modelo de dos baldes

El error clásico de un presupuesto es un número diario plano: pagas el alquiler el día 3
y "ya te pasaste". Acá el gasto se parte en dos:

- **Fijos** — alquiler, servicios, suscripciones. Caen en bloque, están presupuestados y
  **no cuentan contra tu ritmo diario**.
- **Balde diario** — todo lo demás, dividido entre los días que faltan. **Es el único
  número que tienes que vigilar.**

Regla que el sistema verifica solo: `techo = fijos + balde diario`, siempre.

---

## Comandos

```bash
python3 motor/setup.py               # instalación guiada (o retomar donde quedaste)
python3 motor/setup.py --doctor      # diagnosticar qué falta y cómo arreglarlo
python3 motor/setup.py --reset       # borrar la configuración y empezar de cero
python3 motor/servidor.py --open     # abre el tablero operable (localhost:8765)
python3 motor/finanzas.py            # resumen en la terminal
python3 motor/finanzas.py --sync     # refresca desde Wallbit y resume
python3 motor/finanzas.py --import   # propone clasificar los movimientos nuevos
python3 motor/finanzas.py --selftest # verifica que la plata cuadre (24 invariantes)
python3 motor/finanzas.py --alerta   # calla si vas bien; habla si te pasaste
python3 motor/visor-data.py          # genera state.json para la app
python3 motor/visor-data.py --demo   # regenera demo.json con cifras inventadas
```

### El selftest

`--selftest` no comprueba que el programa corra: comprueba que **la plata cuadre**.
Sale con código 1 si algo no reconcilia, así puedes colgarlo de un cron y que te avise
solo cuando haya problema.

Verifica, entre otras cosas:

- que **ningún tipo de movimiento quede sin clasificar** — si Wallbit agrega uno nuevo,
  falla en vez de perderlo en silencio;
- que no haya **direcciones on-chain sin identificar**, ni entrando ni saliendo;
- que el tipo de cambio sea creíble y no diverja de la API;
- que `techo = fijos + variable` y que los acreedores sumen la deuda original;
- que si **retiraste a tu banco** y no actualizaste el saldo manual, te avise: esa plata
  salió de la vista de la API y tu patrimonio queda mal.

---

## Por qué la instalación no se rompe

- **Mide antes de preguntar.** Nadie sabe cuánto gasta al mes. Preguntarlo en un campo
  vacío garantiza un número inventado. El instalador lee tus últimos 35 días y te propone
  un techo con base en eso.
- **Escritura atómica.** Cada archivo se escribe en un temporal, se vuelve a leer para
  comprobar que es JSON válido, y recién ahí reemplaza al original. Si te cortas a la
  mitad, lo que ya estaba sigue intacto.
- **Idempotente.** Correrlo dos veces detecta lo que ya configuraste y te ofrece
  conservarlo.
- **Sin callejones sin salida.** Si tus gastos fijos superan tu techo, te avisa y te hace
  ajustarlo ahí mismo en vez de guardar un presupuesto imposible.
- **Errores que explican.** Ningún fallo termina en un traceback: dice qué pasó y con
  qué comando se arregla.

---

## Detalles que importan (y que cuestan caro descubrir)

**Zona horaria.** Wallbit sella todo en UTC. Si vives en UTC−4 y gastas de noche, cada
movimiento después de las 20:00 cae en el día siguiente — y uno del último día del ciclo
se va al ciclo que viene. El motor convierte a hora local antes de comparar fechas.

**Dos tipos de cambio.** El endpoint `/rates` devuelve la tasa de **retiro a banco**.
Los pagos QR liquidan a una tasa distinta, normalmente algo mejor. El motor mide la tasa
efectiva de tus propios QR de los últimos 3 días, porque un promedio largo queda viejo
cuando la moneda se mueve.

**Gasto en dólares.** Los cargos de tarjeta (`CARD_SPENT`) liquidan en USD, no en moneda
local. Hay que convertirlos o tus suscripciones aparecen a una fracción de su valor real.

**Salidas que no son gasto.** Una transferencia a otro usuario, un envío on-chain a tu
propio exchange o un retiro a tu banco **no son consumo** — pero tampoco son invisibles.
La libreta de direcciones (`tx-labels.json → addresses`) distingue ahorro de gasto; sin
ella, mandar plata a invertir y mandarla a gastar se ven idénticos.

**Retiros a tu banco.** Wallbit ve que la plata salió, no en qué terminó. Lo que retires
y no clasifiques **no cuenta como gasto**: la app te lo dice en la cara y te deja
resolverlo ahí mismo, sin abrir un archivo.

---

## Si usas un asistente de IA

El repo trae **[`AGENTS.md`](AGENTS.md)** (con `CLAUDE.md` apuntando ahí): instrucciones
para que cualquier agente que abras sobre este proyecto sepa qué es, cómo ayudarte, y
sobre todo **qué no puede hacer nunca** — imprimir tu API key, subir tus datos, o
clasificar tus gastos por su cuenta.

Trae también comandos listos en `.claude/commands/`:

| | |
|---|---|
| `/instalar` | te guía en la instalación sin pedirte la key por chat |
| `/como-voy` | resumen del día con el número que puedes gastar |
| `/clasificar` | pregunta sólo por los movimientos que aún no sabe qué son |
| `/revisar` | audita que los números cuadren, recalculando por fuera del motor |

Y por si las instrucciones se ignoran, hay un **guardia de commits** que las hace cumplir:

```bash
git config core.hooksPath hooks     # lo activa setup.py solo
```

Rechaza cualquier commit que incluya tus archivos de datos o algo que parezca una
credencial. Probado: bloquea `git add -f plan.json` y bloquea una API key pegada en
un archivo.

---

## Privacidad

- La API key vive fuera del repositorio (`~/.finanzas/wallbit.key` o variable de entorno).
- `plan.json`, `manual-balances.json`, `tx-labels.json`, `state.json` y
  `wallbit-snapshot.json` están en `.gitignore`.
- Lo único versionado con cifras es **`demo.json`**, generado con datos inventados que
  no corresponden a ninguna persona.
- La app funciona con `state.json` si existe; si no, cae a `demo.json`. Así puedes
  enseñar el proyecto sin enseñar tu plata.

**Antes de tu primer push:**

```bash
git status --porcelain            # que no aparezcan tus .json
grep -r "TU_API_KEY" . || true    # que la key no se coló
```

---

## Estructura

```
app.html                  la aplicación (un archivo, sin dependencias)
demo.json                 datos de ejemplo — lo único con cifras que se versiona
motor/
  wallbit-sync.py         lee la API  -> wallbit-snapshot.json
  finanzas.py             el cálculo  -> resumen, --selftest, --alerta
  visor-data.py           arma los datos de la app -> state.json
  servidor.py             sirve la app y recibe lo que escribes (etiquetas, saldos)
ejemplos/
  plan.example.json
  manual-balances.example.json
  tx-labels.example.json
```

La matemática vive en `finanzas.py`, no repartida por la interfaz. La app solo dibuja
lo que el motor calculó.

---

## Diseño

Construido sobre [IBM Carbon Design System](https://carbondesignsystem.com) v11, tema
White. Esquinas rectas, sin sombras, tokens y escala tipográfica del sistema, y la paleta
categórica oficial para los gráficos. Los gráficos son SVG generados desde tus datos: sin
librerías, sin CDN, sin pedir nada a internet.

## Licencia

MIT — haz lo que quieras con esto.
