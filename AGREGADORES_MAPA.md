# Mapa de cobertura — Agregadores (JustEat/Glovo/Uber Eats)

Resumen de todo lo construido sobre el **mapa de cobertura** del módulo
Agregadores (`frontend/agregadores.html` + `frontend/js/agregadores.js` +
`backend/agregadores.py` + `backend/agregadores_routes.py`). Para el scraper
en sí (cómo se recogen los datos), ver `scraper_agregadores/README.md`.

Este documento existe para que una conversación nueva pueda retomar el
trabajo sin releer todo el historial de chat. Está pensado para lectura
puntual, no se mantiene solo — si hay cambios grandes en el mapa, actualízalo.

## Qué es

Por cada tienda (parquesur, princesa, caleido, granplaza2, plenilunio,
lagavia) y cada agregador, se dibuja un polígono "araña/radar": un vértice
por ángulo de bearing desde el centro de la tienda, a la distancia real de
cobertura comprobada en esa dirección — no un envolvente convexo, así que sí
puede representar huecos reales (cobertura cerrada al norte, abierta al sur).

## Algoritmo del polígono (`agrDibujarPoligonoLimite` en agregadores.js)

Estado actual (restaurado 10/08 tarde a como estaba a las 9:00 del mismo día,
pedido explícito del usuario — la versión "filtrada por tienda más cercana"
de última hora de la tarde se descartó):

- **Vértices base**: uno por cada fila de `agregadores_limites` (búsqueda
  binaria de límite), con su `angulo_grados`/`limite_km`. Si no hay lat/lng
  guardado se reconstruye geométricamente desde el ángulo nominal.
- **`TOLERANCIA_ANGULO_GRADOS = 3`**: un dot dentro de 3° de un vértice base
  EXTIENDE ese vértice (si va más lejos) o lo ENCOGE (si es no_disponible más
  cerca) en vez de crear un vértice nuevo pegado al lado.
- **puntosLejanos**: un dot `disponible` que cae FUERA del borde recto entre
  dos vértices vecinos se inserta como vértice nuevo (estira el polígono).
- **puntosCercanos**: espejo hacia dentro — un dot `no_disponible` que cae
  DENTRO del borde recto se inserta como vértice nuevo (recorta el polígono).
- **Sin filtro de "tienda más cercana"**: todos los dots/vértices de la
  tienda cuentan, sin comprobar si en realidad pertenecen a otra sucursal más
  cercana (esa lógica existe en el código —`agrEsTiendaMasCercana`— pero ya
  NO se usa en el dibujado principal; sigue viva para el mapa de referencia
  de las 9:00 y quedó sin uso en el polígono principal tras el revert).
- **Sin tope duro de distancia**: si un límite real llega a 9km, cuenta tal
  cual ("si de verdad reparte hasta ahí, hay que tomarlo en cuenta").
- **Relleno agresivo entre vértices sin confirmar: DESACTIVADO.** Se probó y
  se quitó — con chequeos "disponible" contaminados por sucursales reales de
  Krispy Kreme no rastreadas, promediar/subir un tramo entero producía
  círculos irreales (caso confirmado: Caleido se volvía un círculo perfecto
  de 6km). Cada vértice se queda con su propio dato.

## Herramientas de edición manual (sobre el polígono ya calculado)

Todas requieren `agrFiltroAgregador` fijado (un agregador concreto elegido
arriba, no "Todos") — se guardan en el backend, no solo en el navegador.

- **➕ Añadir punto** (`agrModoAnadir`): clic en el mapa añade una dirección
  de test fuera del grid fijo. En vista "Todas" se asigna sola a la tienda
  más cercana.
- **🔗 Unir puntos** (`agrModoUnir` / `agrUnionElegirPunto`): clic en dos
  puntos (dots o vértices ya calculados) los conecta con una línea recta,
  eliminando los vértices intermedios en ese arco corto. Para huecos/picos
  raros justo en el BORDE del polígono. Tabla `agregadores_uniones`
  (lat_a/lng_a/lat_b/lng_b, no direccion_id — los vértices del borde no
  siempre tienen una fila de dirección real detrás).
- **🖌️ Pincel: rellenar hueco** (`agrModoPincel` / `agrPincelClick` /
  `agrPincelTerminar`, añadido 10/08 tarde): clic en 3+ puntos libres del
  mapa (no hace falta que caigan sobre un dot/vértice) dibuja un área que se
  fusiona con `turf.union` sobre el polígono calculado. Para huecos DENTRO
  del polígono que "unir puntos" no puede tapar (un puente solo conecta dos
  puntos del borde). Tabla `agregadores_rellenos` (lista de `[lat,lng]` en
  JSON). Botones "✅ Rellenar (N puntos)" / "✕ Cancelar" aparecen con 3+
  puntos trazados.
- **Mover límite** (arrastrar un vértice): `PUT /limites/{tienda}`,
  recalcula la distancia real desde la nueva posición.
- **Compás de ángulos**: líneas cada 15° desde la tienda, solo con una
  tienda sola seleccionada — ayuda a ubicar a ojo en qué dirección cae un
  hueco antes de añadir un punto ahí.

## Mapa de referencia "9:00" (`agr-panel-9am`, solo lectura)

Segundo mapa debajo del principal, en escala de grises, que muestra el
polígono calculado con el algoritmo TAL COMO ESTABA a las 9:00 del 10/08
(`agrCalcularPoligono9am`): tolerancia 3°, sin filtro de tienda-más-cercana
(el mismo comportamiento que ahora tiene el mapa principal — quedaron casi
idénticos tras el revert, la diferencia real es que el mapa 9am NUNCA tiene
en cuenta uniones/rellenos manuales, es puramente el cálculo automático).
Visible para cualquier usuario con acceso al módulo "agregadores" (no solo
admin). Se reencuadra (`fitBounds`) solo cuando cambia de verdad la
selección de tienda/agregador, para no pisar el zoom/pan a mano.

## Contador del daemon en vivo (`agr-daemon-live`)

Pill en la barra superior — **solo visible para el usuario `saul`**. Muestra
qué tienda está recorriendo el daemon ahora mismo y el progreso
(hechos/total), leyendo `tienda_actual` de `agregadores_sesiones` (el
scheduler la actualiza en cada vuelta, ver `scraper_agregadores/scheduler.py`
y `utils/api_client.py::actualizar_tienda_actual`).

## Otras piezas del backend relevantes

- `agrCentrosTodos` (frontend): las 6 tiendas SIEMPRE, sin filtrar por chips
  activas — necesario para que "tienda más cercana" tenga con qué comparar
  aunque solo haya una tienda visible en el mapa (esta lógica sigue en el
  código para el mapa 9am, aunque el polígono principal ya no la usa).
- El filtro por agregador (botones JustEat/Glovo/Uber Eats) y las chips de
  tienda seleccionada refrescan TANTO el mapa principal como el mapa 9am al
  instante (antes solo el principal se actualizaba al cambiar de agregador;
  arreglado 10/08).
- "Cobertura combinada" (checkbox): usa `turf.union` para fusionar los
  anillos de varias tiendas visibles en un solo contorno, ocultando el
  detalle individual (vértices/líneas por tienda) para que no se vea como
  una maraña.

## Pendiente / ideas sueltas

- El contador del daemon en vivo sigue solo para `saul` — no se ha pedido
  abrirlo a todos los usuarios del módulo (a diferencia del mapa 9am, que sí
  se abrió).
- Contaminación de datos: sucursales reales de Krispy Kreme no rastreadas
  por este sistema generan chequeos "disponible" legítimos pero lejanos, sin
  forma automática de distinguirlos de cobertura real de la tienda vigilada.
  Sin solución técnica aplicada — el pincel/unir puntos son la vía manual
  para corregir visualmente si hace falta.
- `remove_near_dots.py` (script en el scratchpad de una sesión anterior,
  no en el repo): identificaba direcciones "sin_datos" a <1km de cada
  tienda para depurarlas; se abandonó a medio camino, no llegó a haber
  ninguna dirección sin coordenadas que calificara. Si se retoma ese pedido,
  hay que redefinir primero qué cuenta como "sin datos" (¿sin chequeo
  reciente? ¿sin lat/lng? ¿origen=grid viejo?) antes de escribir el filtro.

## Convenciones a tener en cuenta

- **Cache buster**: cada cambio en `agregadores.js` necesita subir el
  `?v=` del `<script>` en `agregadores.html` (esquema `YYYYMMDDx`, letra
  incremental) o el navegador sirve la versión cacheada.
- **Despliegue**: Railway, proyecto `adequate-commitment` /
  `krispy-gestiones`. `git push` a la rama desplegada dispara el build solo;
  hay que sondear `get-status` hasta `SUCCESS` antes de dar el cambio por
  verificado en producción.
- **OP/OT**: el usuario distingue dos máquinas físicas (Ordenador Personal /
  Ordenador de Trabajo). El daemon del scraper corre como proceso local en
  una de las dos — una sesión de Claude Code en una máquina no puede ver ni
  controlar procesos en la otra.
- Comentarios largos en `agregadores.js` documentan el *por qué* de cada
  decisión no obvia (con fecha y a veces cita textual del usuario) — son la
  fuente más fiable de contexto histórico si este README se queda corto.
