---
description: Clasificar los movimientos que el sistema todavía no sabe qué son
---
Hay dos grupos, y se tratan distinto.

## 1. Los que ya describió en la app (empieza por acá)

`python3 motor/por-clasificar.py`

Son los que abrió el tablero, escribió con sus palabras qué fueron y guardó. **La parte
difícil ya está hecha**: sólo hay que meterlos en la taxonomía. Eso es mecánico y te toca
a ti — para eso los describió en vez de encasillarlos él.

Para cada uno, aplica la categoría que corresponda a lo que dijo:

`python3 motor/por-clasificar.py --clasificar <uuid> "<categoría>"`

Su descripción se absorbe como nota del movimiento; no hace falta repetirla. Si la
descripción es ambigua de verdad (no si sólo es corta), pregúntale — pero una sola vez y
con la opción que te parece más probable ya puesta.

## 2. Los que no tienen ninguna explicación

`python3 motor/finanzas.py --import`

Muéstrale **sólo** los que siguen sin identificar; los ya etiquetados no se vuelven a
preguntar nunca. Espera su respuesta y recién entonces aplica la categoría.

## Siempre

- Se indexa por **`uuid`**, nunca por monto o fecha: se repiten.
- Si un movimiento es parte de un gasto ya decidido (el pasaje de un viaje, la cena de un
  cumpleaños), pásale también `excepcional` con el id de ese gasto. Si no, el sistema
  seguirá apartando plata para algo que ya está comprado.
- Si un comercio se va a repetir, propón una regla en `merchant_rules` para no volver a
  preguntar nunca por él.
- Termina con `python3 motor/finanzas.py --selftest`.

**Nunca decidas por él en qué categoría va un gasto suyo** cuando no te dio la información.
Clasificar lo que ya describió no es decidir: es transcribir.

**Y no inventes categorías.** Usa las que existen en `tx-labels.json → _categories`. Si de
verdad ninguna encaja, propón el nombre y espera el sí — una taxonomía que crece sola
termina con quince etiquetas parecidas y un desglose inútil. Si ves que "Otros" se está
llenando, esa es la señal de que falta una categoría con nombre propio: dísela.
