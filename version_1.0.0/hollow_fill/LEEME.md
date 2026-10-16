# Hollow Fill 1.0.0

Complemento para Blender 4.2 a 5.x. **Vacía una pieza** dejando una pared del grosor que elijas y le
abre un **agujero de llenado** (y un respiradero) para rellenarla después con **resina epoxi,
poliuretano colado o espuma**. Todo en modo Objeto; la pieza original no se toca (se oculta).
Licencia GPL-3.0-or-later.

## Uso (Vista 3D → N → pestaña Hollow Fill)

1. **Selecciona la pieza** (cerrada; si no lo está, pásala antes por «Dejar listo» o Mesh Doctor).
2. **Pared**: 2 mm va bien para rellenar; 1,6 mm si la pieza es pequeña, 3 mm si es grande.
3. **Agujero**: diámetro y dónde va:
   - **Con clic**: pulsas el botón, pasas el ratón por la pieza y haces clic donde quieres el agujero.
   - **Abajo** / **Arriba**: en el punto más bajo/alto del hueco, centrado.
4. **Respiradero** (recomendado): un agujero pequeño en la punta del hueco más lejana al agujero,
   por donde sale el aire mientras rellenas.
5. Sale `<pieza>_vacio` y te dice **cuántos ml de relleno** necesitas (y los gramos según la densidad).
6. **Exportar STL** en mm.

## Cómo es la pared

- Mide lo mismo en toda la pieza. Las zonas más finas que dos paredes (dedos, orejas, bordes) se
  quedan **macizas**: no salen paredes cruzadas ni rotas.
- Solo se vacía el hueco al que llega el agujero. Si hay otro hueco que no conecta (por ejemplo, dos
  partes gordas unidas por algo fino), se deja macizo para que no quede aire encerrado sin rellenar.
  El mensaje te lo dice.

## Consejos para rellenar

- Imprime con el agujero arriba o dale la vuelta antes de verter. Vierte despacio y deja que salga el
  aire por el respiradero; tápalo con cinta cuando empiece a salir resina.
- El poliuretano y la epoxi calientan al curar: con piezas grandes vierte en dos o tres tandas.
- Espuma expansiva de poliuretano: rellena solo una parte del hueco (mira la expansión del fabricante)
  y deja el respiradero abierto.
