# Krispy Gestiones — Estado del proyecto (resumen para retomar en otra conversación)

> Generado el 2026-08-24. Léeme primero en vez de pedirle a Claude que explore
> todo el repo desde cero — ahorra tokens.

## Qué es esto

"Krispy Gestiones" es una plataforma de backoffice multi-marca (Krispy Kreme,
Saona, La Voz, La Receta) que cubre:

- **RRHH**: reclutamiento (+ extracción de CVs), entrevistas (+PDF), tests
  DISC (con formulario público), encuestas, clima laboral (+PDF), scoring de
  valores, usuarios/auth.
- **Comunicación interna**: boletines (con builder), blog, informes.
- **Analítica de reseñas de Google Maps**: scraper Selenium + import de
  Google Takeout, dashboard con stats/timeline/keywords/staff-mentions.
- **Agregadores de delivery**: monitor de cobertura en Uber Eats, Just Eat,
  Glovo (`scraper_agregadores/`), con un mapa "9am" (herramienta de pincel
  para pintar zonas de cobertura).

**Stack**: backend FastAPI (Python) en `backend/`, frontend estático
(HTML/CSS/JS vanilla, sin build) en `frontend/`, SQLite (`krispy_kreme.db`,
fuera de git). Repo en GitHub: `github.com/sauljvg/Krispy-Gestiones`.
Se despliega en Railway (ver `Dockerfile`, `fly.toml` es vestigial).

## Qué se hizo en esta sesión (24/08/2026)

El escritorio tenía **7 carpetas sueltas**, cada una usada históricamente
para un módulo distinto del proyecto:

| Carpeta original | Qué tenía | Qué se hizo |
|---|---|---|
| `Krispy Gestiones` (sin guion) | Clon del repo **más actualizado** (commit `6d56aa0`, 23/08) + PDFs DISC, fuentes, logos, textos clima laboral | Es la base de la carpeta final. Recursos sueltos → `_recursos/` |
| `Krispy-Gestiones` (con guion) | Clon del mismo repo pero **117 commits desactualizado** (commit `22f43c1`, 10/08) + 10 archivos sueltos de agregadores sin commitear | Los 10 archivos se copiaron al repo bueno. La carpeta en sí **no se pudo borrar** (ver pendientes) |
| `Reseñas KK` | Datos de Google Takeout (export oficial de reseñas) | Copiado a `_recursos/resenas-takeout/` |
| `Clima Laboral` | Excel/PDFs reales de clima laboral por tienda | Copiado a `_recursos/clima-laboral/` |
| `Agregadores KK` | Copia vieja de `scraper_agregadores` + docs sueltos (ofertas de trabajo, plan de monitor) | Docs → `_recursos/agregadores-docs/`. El código no se copió (ya superado por el del repo bueno) |
| `BBDD SV` | App aparte "candidatos-app" (Next.js/Prisma, sin relación con el backend actual) | **Obsoleta, enviada a la papelera** por decisión del usuario |
| `App` | App aparte "Cribar CVs" (Node.js, offline, sin integrar en el backend) | **Obsoleta, enviada a la papelera** por decisión del usuario |

**Resultado**: todo unificado en **`Escritorio/Krispy-Gestiones/`** (esta
misma carpeta — no se creó ninguna carpeta nueva, se actualizó la que ya
existía). Contiene:
- El código del repo, actualizado al commit más reciente de `origin/main`
  (`6d56aa0`, 23/08) vía `git reset --hard origin/main`, con los 10 archivos
  sueltos de agregadores conservados sin commitear.
- `_recursos/` — todo lo que no es código: `disc/`, `clima-laboral/`,
  `resenas-takeout/`, `fuentes-logos/`, `agregadores-docs/`.

(Se creó una carpeta intermedia `Krispy-Gestiones-FINAL` durante el proceso,
pero ya se fusionó aquí y se borró — no debería quedar en el escritorio.)

## Pendiente (no completado en esta sesión)

**2 carpetas del escritorio siguen sin eliminar** porque son el directorio
de trabajo de otras dos conversaciones de Claude Code de este mismo
proyecto (agrupadas junto a esta en la app):

- `Reseñas KK` → conversación "Krispy Kreme reviews ATS platform"
- `Agregadores KK` → conversación "Leer archivos markdown"

Ambas están inactivas (`isRunning: false`), pero al intentar borrarlas
apareció un proceso que las bloqueaba (posible tarea programada de Windows
ligada a `scraper_agregadores/setup_tarea_programada.ps1`, relanzándose).
El usuario pidió no forzar el borrado por ahora, para no romper esas
conversaciones mientras decide si centraliza todo aquí.

**Nada de contenido único se perdería si se borran** — ya está todo copiado
dentro de `_recursos/`. Cuando el usuario confirme, el siguiente paso es:
1. Archivar esas 2 sesiones (`mcp__ccd_session_mgmt__archive_session`).
2. Revisar el Programador de tareas de Windows por si hay una tarea
   apuntando a esas carpetas, y editarla para que apunte a
   `Krispy-Gestiones\scraper_agregadores` en su lugar (o deshabilitarla).
3. Borrar `Reseñas KK` y `Agregadores KK` (papelera de reciclaje, no
   borrado permanente).

Las otras 4 carpetas sobrantes (`Krispy Gestiones`, `Clima Laboral`,
`BBDD SV`, `App`) ya se enviaron a la Papelera de reciclaje.

## Se quitó el número "total de Google" de reseñas (24/08/2026)

Como ya no se scrapea Maps en vivo (solo se importa vía Google Takeout), se
eliminó todo lo relacionado con `total_google`/`visible_en_google` por estar
siempre desactualizado y confundir en el popup de importación: el toggle
"Solo Google" del dashboard, el check "✓ 100% capturado", la insignia "no
visible en Google" en cada reseña, y el endpoint
`POST /api/reviews/reconciliacion`. Las columnas de la BD se dejaron intactas
(sin migración) por compatibilidad, simplemente ya no se leen ni escriben.
`scraper/scraper_v2.py --reconciliar` sigue existiendo como script suelto,
pero si se corre ahora fallará al intentar subir el resultado (con un aviso
claro, no un crash) porque ese endpoint ya no existe.

## Solicitud de acceso a la API de reseñas de Google (24/08/2026)

Llevábamos meses esperando que Google aprobara el acceso a la API de reseñas
de Business Profile (`accounts.locations.reviews.list`/`batchGetReviews`,
`mybusiness.googleapis.com/v4`) — el plazo se cumplió el 5/08/2026 sin
respuesta. Se comprobó en Cloud Console (proyecto `krispy-reviews-export`,
número `48525790961`) que el acceso nunca se concedió (no aparece en la
lista de APIs habilitadas), aunque las credenciales OAuth 2.0 sí estaban
listas ("Krispy Reviews OAuth"). Se reenvió una segunda solicitud el
24/08/2026 vía `support.google.com/business/contact/api_default`
("Application for Basic API Access"), cubriendo solo las 6 tiendas de
Krispy Kreme (sin Saona, es un negocio aparte).

**Caso de soporte abierto: `9263000040737`** — revisión estimada 7-10 días
laborables (≈ 2-4 de septiembre de 2026).

**Si aprueban el acceso**: se podría sustituir la importación manual de
Google Takeout por una llamada automática a la API (con OAuth ya
configurado en el proyecto `krispy-reviews-export`), integrándolo en
`scraper/import_takeout.py` o un módulo nuevo equivalente. Hasta entonces,
seguir usando Takeout como hasta ahora — no hay nada que cambiar en el
código todavía.

## Scraper de agregadores: multi-worker, dedup y limpieza (26/08/2026)

Sesión larga centrada solo en `scraper_agregadores/` y `backend/agregadores.py`.
Todo lo de abajo ya está en `origin/main` y desplegado en Railway.

### 1. Varios workers en paralelo (boost puntual desde otro ordenador)

- `daemon.py` acepta `--worker-index`/`--worker-count`. `scheduler.py` reparte el
  trabajo por par `(tienda, agregador)`, en orden **agregador-major** (todo
  JustEat primero, luego todo Glovo, luego todo Uber Eats) para que un agregador
  con mucho pendiente no compita por turno con uno ya completo.
- `iniciar_daemon.bat` lee `SCRAPER_WORKERS` del `.env` **local de cada máquina**
  (no versionado) y lanza esa cantidad de workers. Sin la variable = 1 worker,
  comportamiento de siempre. `detener_daemon.bat` los para a todos.
- Pensado para: el portátil de trabajo (OT) corre 1 worker 24/7; un ordenador más
  potente (OP) puede subir `SCRAPER_WORKERS=6-8` en su propio `.env` cuando se
  encienda, como refuerzo puntual. Mismo código, sin duplicar carpetas.
- **Ojo, redundancia sin resolver**: esta sesión añadió un acceso directo en la
  carpeta de Inicio de Windows (`shell:startup`) para autoarrancar el daemon,
  sin saber que `setup_tarea_programada.ps1` (ya en el repo, con tareas
  `AgregadoresScraperLogon`/`AgregadoresScraperDiario` vía Task Scheduler +
  `detener_daemon_nocturno.bat` para la parada de las 22:00) ya resolvía esto de
  forma más completa (el repo local de esa máquina llevaba 164 commits de
  retraso, ver más abajo). Los dos mecanismos coexisten sin pisarse (el guard
  de `iniciar_daemon.bat` evita duplicados), pero sobra uno — decidir cuál se
  queda y quitar el otro.

### 2. Dos fixes en el flujo normal del daemon (`main.py`)

- **"Tienda no confirmada" persistente** ya no se guarda como error técnico
  (se reintentaba sin fin cada pasada, sin avanzar nunca) — se acepta como
  `no_disponible` real, igual que ya hacía `buscar_limite_cobertura.py`
  (constante compartida `MARCADOR_TIENDA_NO_CONFIRMADA` en `scrapers/base.py`).
- **Reutiliza chequeos cercanos** (`buscar_chequeo_cercano`, <100m, <24h, de
  cualquier tienda) antes de scrapear — evita re-scrapear el mismo sitio real
  solo porque tiene una fila en dos tiendas distintas.

### 3. Mini dashboard local (`status_server.py`)

No auto-arranca (a diferencia del daemon) — hay que lanzarlo a mano en cada
máquina donde se quiera ver:

```
venv/Scripts/python status_server.py
```

Abre en `http://localhost:8787`, se refresca solo cada 30s. Muestra: workers
activos en esa máquina, cobertura real deduplicada (sitios únicos) por
agregador, y el desglose bruto por tienda con las direcciones que faltan
listadas. Todo en vivo contra la API de producción (misma `KG_API_KEY` del
`.env`), no lee ninguna BD local.

### 4. Deduplicación de direcciones solapadas entre tiendas

Los grids de tiendas vecinas se solapan geográficamente — la misma dirección
real podía tener una fila por tienda (y a veces varias filas en la MISMA
tienda, por geocoding cayendo en el mismo sitio sin número). Ya aplicado en
producción:

- **Fusión** de puntos a <200m (`UMBRAL_DUPLICADO_KM` en `backend/agregadores.py`,
  antes 100m): 494 puntos fusionados en su mejor representante (la tienda
  realmente más cercana, vía `_tienda_mas_cercana`). El historial de chequeos
  del perdedor se re-apunta al ganador antes de desactivarlo, no se pierde.
- **Limpieza de direcciones sin número de portal** (193 desactivadas): no son
  destinos de entrega reales, se borran sin excepción aunque tuvieran algún
  chequeo real (pedido explícito del usuario).
- **Cierre de raíz**: `get_o_crear_direcciones` ya NO crea un punto nuevo si
  cualquier tienda tiene uno activo a <200m — antes de este fix, seguían
  naciendo duplicados nuevos aunque se limpiara el histórico.
- Resultado: de ~1500 filas brutas por agregador a ~900 sitios únicos reales.
- Endpoints nuevos (API key, admin): `GET .../admin/direcciones/resumen-deduplicado`,
  `POST .../admin/direcciones/deduplicar?aplicar=&umbral_m=`,
  `POST .../admin/direcciones/limpiar-sin-numero?aplicar=`. Los dos POST son
  dry-run por defecto (`aplicar=false`).

**Nota técnica de la agrupación por proximidad** (`_agrupar_por_proximidad`):
usa un punto "ancla" por cluster, no cierre transitivo — un cierre transitivo
(A cerca de B, B cerca de C → A/B/C juntos) encadenaba puntos claramente
distintos a 200m (llegó a mezclar una autovía y un carril bici). Si se vuelve
a tocar este umbral, probarlo primero en dry-run y revisar los clusters más
grandes antes de aplicar.

### 5. Merge con origin/main (164 commits de diferencia)

El clon de la máquina donde se hizo esta sesión llevaba 164 commits de
retraso respecto a `origin/main` (módulos de Reclutamiento, Evaluaciones 360,
etc., sin relación con agregadores). Se resolvió con un merge normal —
conflictos en `backend/agregadores.py`, `frontend/js/agregadores.js`,
`scraper_agregadores/{scheduler.py,utils/api_client.py,detener_daemon.bat}`,
todos resueltos conservando ambos lados. Si otra máquina (como la de trabajo)
también está desactualizada, esperar conflictos parecidos al hacer `git pull`
— revisar con calma, no forzar.

### 6. "0 faltan" en la API pero el mapa real muestra "Sin datos" (26/08/2026)

Descubierto al priorizar Uber Eats: el scraper (`solo_sin_datos=True`,
`get_o_crear_direcciones`) usa `_cobertura_confirmada_por_limite` para saltarse
puntos que caen DENTRO del polígono de cobertura ya confirmado -- los da por
"ya sabemos la respuesta" sin comprobarlos uno por uno (decisión deliberada de
antes de esta sesión, commit "Un punto sin datos dentro del límite ya
confirmado no cuenta como frontera", pensada para no repetir miles de
chequeos redundantes). Por eso el scraper decía "0 faltan" en Uber Eats
mientras el mapa real de cobertura (`Mapa de cobertura` del dashboard, capa
Uber Eats) seguía marcando **251 puntos como "Sin datos"** -- nunca tuvieron
un chequeo propio, solo la suposición del polígono.

**Pendiente de decidir con el usuario**: si desactivar esa suposición para
Uber Eats (comprobar esos 251 uno por uno de verdad) o dejarla como está.
No tocado todavía.

De paso esta sesión:
- `config.AGREGADORES` reordenado a `["ubereats", "glovo", "justeat"]`
  (antes `["justeat", "glovo", "ubereats"]`) -- pedido explícito del usuario
  para priorizar Uber Eats en el reparto de workers (`scheduler.py` reparte
  en este mismo orden, agregador-major).
- Al reiniciar el daemon (`detener_daemon.bat`) se borraron de paso las
  tareas de Task Scheduler `AgregadoresScraperLogon`/`AgregadoresScraperDiario`
  en ESTA máquina (el script las quita a propósito en una parada manual, ver
  sección 1 más arriba) -- el acceso directo de la carpeta de Inicio sigue
  siendo el único autoarranque activo aquí ahora mismo.
- **26/08, más tarde**: decisión explícita del usuario -- se quita también
  el acceso directo de la carpeta de Inicio y se para el daemon de 24/7 en
  esta máquina. El flujo pasó a ser vueltas completas manuales con
  `revalidar_completo.py` (20 workers por agregador, JustEat → Glovo →
  Uber Eats en secuencia, un orquestador .ps1 detached encadena los tres) en
  vez del daemon continuo -- por ahora NO hay ningún autoarranque activo del
  scraper en esta máquina. Si se quiere retomar el daemon 24/7 más adelante,
  hay que volver a crear el acceso directo o la tarea programada a mano.

## Para la próxima conversación

- Trabajar directamente sobre `Escritorio/Krispy-Gestiones/` — ya está al
  día con origin/main.
- Verificar `git status` al empezar: quedan sin commitear los 10 archivos
  de `scraper_agregadores/`, `AGREGADORES_MAPA.md`, un `.png` de scratchpad,
  y `_recursos/` (que probablemente no se quiera commitear a git, son
  binarios/datos — considerar añadir `_recursos/` a `.gitignore`).
- Si `Reseñas KK` / `Agregadores KK` siguen en el escritorio, ver la sección
  de pendientes arriba antes de intentar borrarlas.
- Revisar si llegó respuesta al caso `9263000040737` (ver sección de arriba)
  — si aprobaron el acceso a la API de reseñas, se puede empezar a
  reemplazar el flujo de Takeout.
- **Scraper de agregadores (ver sección de arriba, 26/08)**: en la máquina de
  trabajo, hacer `git pull` primero (puede pedir resolver conflictos si ese
  clon también estaba desactualizado). El autoarranque (Task Scheduler y el
  acceso directo de Inicio) se quitó del todo esta sesión -- ver más abajo,
  ya no hay que decidir nada ahí. Para ver el mini dashboard local en esa
  máquina: `venv/Scripts/python status_server.py` dentro de
  `scraper_agregadores/`, abre en `localhost:8787` (o el nuevo botón
  "Dashboard del scraper" en `agregadores.html`, solo admin, no necesita
  levantar nada aparte).
- **IMPORTANTE -- Glovo, bloqueo/limitación del lado de Glovo (actualizado
  26/08)**: tras varias pasadas con 20/15/10 workers, todas con ~29-31% de
  fallos idénticos (página "Oh, no! It looks like there's a problem" de
  Glovo, en inglés, captura guardada en cada fallo desde hoy), el usuario
  probó a mano con datos móviles (sin WiFi) -- Glovo carga bien. Con el
  WiFi de la oficina -- el mismo "Oh, no!" incluso en un navegador normal,
  sin scraper de por medio. Se descartaron antes con pruebas reales:
  concurrencia (20→15→10 workers, mismo % de fallo), bloqueo de
  imágenes/media (`--permitir-imagenes`, sin diferencia), y fingerprint de
  Chromium headless (test con `--visible`, ventana genuinamente visible
  igual que Uber Eats, 20 workers: 45 hechos / 20 fallos, mismo ~31% que en
  headless -- **no hay diferencia, se descarta headless como causa**;
  vuelto a headless, que es lo que sigue usando Glovo por defecto).
  Además, probando manualmente desde un navegador en la nube (IP de
  Anthropic, no la de la oficina) también salió el mismo "Oh, no!" de forma
  intermitente (a veces recargar lo arregla, a veces no) -- así que no es
  solo un bloqueo fijo de la IP de la oficina, sino algo más parecido a un
  límite de volumen/tasa o patrón de tráfico que Glovo dispara bastante en
  general. El usuario confirmó 26/08 que activando NordVPN sí carga bien
  desde la oficina. NO relanzar Glovo con muchos workers seguidos desde la
  misma IP/red -- seguir insistiendo solo prolonga el bloqueo. JustEat y
  Uber Eats no muestran este problema por ahora, pero vigilar por si les
  pasa lo mismo con el tiempo.
- **26/08, cierre de sesión -- selectores en español YA adaptados, pero
  concurrencia baja NO arregla el bloqueo**: `scrapers/glovo.py` se cambió
  para usar `https://glovoapp.com/es/es/madrid` (pedido explícito del
  usuario) con todos los selectores de texto traducidos (verificado a mano
  paso a paso en un navegador real: "Denegar", "¿Cuál es tu dirección?",
  "Otro", "Confirmar", "¿Qué necesitas?", "Buscar" -- las clases CSS/
  data-testid no cambian con el idioma). Sin commitear -- pendiente probar
  en limpio (ver más abajo). Aparte, se probó reducir de 20 a **8 workers**
  (con el código en inglés de siempre, para no mezclar dos cambios a la
  vez): **empeoró, no mejoró** -- 47% de fallo (78 hechos / 70 fallos) tras
  148 de 488 puntos en ~29 min, y la tasa de fallo iba SUBIENDO con el
  tiempo (38% a los 13 min → 47% a los 27 min), no bajando. Se cortó a mano
  (`paremos por hoy`) antes de completar la vuelta. Conclusión: **no es un
  problema de cuántos workers a la vez** (ya se descartó 20/15/10/8, todos
  con fallo alto), sino de volumen/tiempo acumulado insistiendo desde la
  misma IP -- cuanto más se insiste, peor, sea cual sea la concurrencia.
  Un test manual de UN solo punto con la web en español, mientras los 8
  workers en inglés corrían a la vez, también falló 4/4 -- pero no es dato
  limpio (había 9 sesiones de Glovo simultáneas desde la misma IP en ese
  momento, no 1), así que la validación de los selectores en español sigue
  pendiente de una prueba real sin solape con ningún otro test de Glovo.
  **Para la próxima sesión**: (1) probar el flujo en español con un único
  punto, sin ningún otro proceso de Glovo corriendo a la vez, para
  confirmar que los selectores traducidos funcionan de verdad; (2)
  plantearse si vale la pena seguir insistiendo desde esta IP/red en
  absoluto, o si hace falta otra estrategia (esperar más tiempo sin tocar
  Glovo en absoluto, red distinta, etc.) antes de intentar la vuelta
  completa de Glovo otra vez.

- **27/08 -- selectores en español SÍ funcionan, cifra de bloqueo real
  bastante más baja de lo que sugería 26/08, y confirmado que SÍ importa la
  concurrencia (contradice la conclusión de 26/08 de más arriba)**: con
  vueltas completas reales (`revalidar_completo.py`, resumibles) durante
  toda la tarde/noche del 27/08, la tasa de FALLO DEFINITIVO (agotar los 3
  intentos internos, no solo un intento suelto) con 5 workers se mantuvo
  **7.0-8.4% de forma consistente en 3 pasadas distintas repartidas entre
  las 17:33 y las 20:34** (200, 119 y 211 puntos respectivamente) -- con 10
  workers subió a **22-29%** en dos pruebas aparte. Como las pruebas de 5
  workers se repartieron por toda la tarde
  (incluida hora punta de cena, 20:00+) sin que la tasa se moviera, se
  descarta que sea solo "hora punta" -- es la concurrencia la que importa
  de verdad, contradiciendo la conclusión de 26/08 de que "no es problema
  de cuántos workers a la vez" (esa prueba fue con el código en inglés
  viejo y datos más ruidosos). **Conclusión operativa: Glovo se queda en 5
  workers**, no subir.
  Se probaron 3 mitigaciones adicionales de código (todas ya en
  `scrapers/base.py`/`scrapers/glovo.py`/`revalidar_completo.py`, activas
  por defecto, sin flag): UA/viewport variable en vez de fijo siempre,
  backoff largo (30-60s aleatorios) específico cuando la página devuelve su
  propio "Oh, no! It looks like there's a problem" (antes se trataba igual
  que cualquier timeout, con backoff de 2-4s), y jitter en el delay entre
  chequeos (antes fijo 4s). Con 5 workers, la tasa se quedó en 8.06% (17
  fallos / 211 puntos) -- prácticamente empatada con el 7.0% de antes de
  estos cambios, no una mejora clara, pero tampoco empeora, y el detector
  de "Oh, no!" sí se dispara con frecuencia real (51 veces en 20 min) con
  la mayoría recuperándose solos tras esperar.
  También se probó rotación de IP con proxies gratis de Webshare (10
  datacenter, plan gratuito permanente) -- **empeoró, no mejoró**: 27.5% de
  fallo con proxy vs 8.4% sin proxy en la misma ventana de tiempo, con los
  3 proxies probados (Madrid + 2 Londres) dando un resultado parecido entre
  sí (no es uno malo aislado). Conclusión: son proxies de DATACENTER, el
  tipo de IP que un sistema anti-bot/rate-limit ya suele tener fichada --
  no vale la pena repetir con proxies gratis, haría falta un proveedor
  residencial de pago para tener alguna chance real, sin garantía.

  **HALLAZGO IMPORTANTE relanzado esta noche, casi se pasa por alto**: la
  nota de 26/08 de arriba dice que el usuario confirmó A MANO que
  **activando NordVPN el "Oh, no!" desaparece incluso desde un navegador
  normal, sin scraper de por medio** -- y NordVPN está instalado y con
  procesos corriendo en esta máquina ahora mismo (`C:\Program
  Files\NordVPN`, `NordVPN.exe`/`nordvpn-service.exe` activos). Esto es
  potencialmente MUCHO más efectivo que cualquier ajuste de código de los
  de arriba, y ya viene confirmado por el propio usuario, no es una
  hipótesis nueva. NO lo activé/probé con el scraper esta noche (sesión
  autónoma, 27/08 noche) -- conectar/desconectar una VPN es un cambio de
  red a nivel de todo el sistema, no solo del scraper, y cae dentro de "no
  tocar configuración de sistema sin confirmar" aunque el usuario ya diera
  luz verde a experimentar con el código. **Para la próxima sesión (con el
  usuario presente o con su confirmación explícita): probar
  `revalidar_completo.py` con la VPN activa a mano, comparando la tasa de
  fallo definitivo contra el 7-8% de sin VPN** -- si de verdad lo arregla
  como sugiere la nota de 26/08, es la solución real, por delante de
  cualquier cosa de las de arriba.

  **Actualización la misma noche del 27/08, con el usuario presente**:
  probado NordVPN (Madrid) con el scraper de verdad -- a 20 workers dio
  24.3% de fallo, prácticamente igual que sin VPN a esa misma concurrencia.
  **Conclusión: la VPN NO soluciona el problema de concurrencia** (contra
  lo que sugería la nota de 26/08) -- ese hallazgo de ayer probablemente
  era sobre un bloqueo DISTINTO (posible penalización acumulada por horas/
  días insistiendo desde la misma IP de oficina, no el "Oh, no!" de
  sobrecarga por concurrencia que se ve hoy). Después el usuario probó
  conectando otra IP de Madrid por su cuenta (no NordVPN, otra red) -- con
  solo 5 workers (el número ya confirmado seguro, 7-8% con la IP de
  oficina) esa IP dio **41.4% de fallo**, mucho PEOR que la IP habitual a
  la misma concurrencia. O sea que la IP sí importa, pero no en el sentido
  de "cualquier IP nueva ayuda" -- hay IPs claramente peores que la de la
  oficina. **Conclusión operativa final de esta sesión: quedarse con la IP
  de oficina de siempre + 5 workers (7-8%, ~87 min para los 350 puntos)
  es la mejor combinación probada hasta ahora.** El objetivo de "toda la
  vuelta de Glovo en 30 min" que pidió el usuario esta noche NO se
  consiguió y no parece alcanzable sin aceptar una tasa de fallo mucho más
  alta -- probado con 4 combinaciones de concurrencia/IP distintas, todas
  con el mismo techo.

- **03-04/09 -- RUTAS RÁPIDAS: la dirección se fija por URL/cookie con la sesión
  caliente, en vez de repetir la interfaz en cada punto.** El coste real por
  dirección no estaba en la búsqueda sino en repetir para CADA punto: lanzar
  Chromium + cargar la portada entera + los ~6-7 pasos del flujo de dirección.
  - **Uber Eats**: acepta la dirección como parámetro de URL `pl` =
    base64(percent-encode(JSON con address + lat/lng)); el placeId puede ir
    vacío, no lo valida. Se va directo a
    `/es/search?q=Krispy%20Kreme&pl=...&diningMode=DELIVERY`.
  - **Glovo**: se reutiliza la cookie `glovo_delivery_address` ya conocida del
    27/08, cambiándola entre direcciones sin tocar la interfaz.
  - **Por qué habían fallado los dos intentos anteriores** (Uber 08/08, Glovo
    27/08): se probaban con un navegador NUEVO en cada chequeo. Con sesión fría,
    entrar directo a una URL profunda dispara el challenge y la página de
    resultados sale vacía. La diferencia es CALENTAR la sesión una vez (visita
    normal a la portada) y REUTILIZARLA para todas las direcciones de ese worker.
  - **Validación A/B** (lo que importa no es "lejos = no reparte" -- Uber reparte
    en el 91% de los puntos -- sino que las dos rutas digan LO MISMO): Uber Eats
    6/6 idéntico al flujo de interfaz (2.9s vs 78.9s de media); Glovo 8/8
    idéntico en dos pasadas seguidas (2.6s vs 30.4s en los puntos que resuelve).
  - Ambas caen automáticamente al flujo de interfaz de siempre si fallan, con
    cortacircuitos temporal, así que nunca se pierde ni se falsea un punto.

- **04/09 -- RONDAS REALES, resultados medidos.**
  - **Uber Eats: 18.1 puntos/min con SOLO 4 WORKERS** (234 puntos reales,
    96.6% resueltos por la ruta rápida) -> ~22 min proyectados para los 390
    puntos. La ronda de referencia hacía los 390 en 34 min **con 20 workers**:
    son ~8x por worker. Es el mejor resultado conseguido hasta ahora.
  - **Glovo: SIN MEJORA en tiempo de ronda.** Tres lecturas consistentes
    (5.2-6.0 pts/min con 5 workers) dan los mismos ~57 min de siempre. La ruta
    rápida funciona (12x en los puntos que resuelve), pero el **40% de los
    puntos acaba en el flujo lento** por el "Oh, no!" (60 sobrecargas en 93
    puntos). Quien marca el ritmo es el límite por IP de Glovo, no el código.
    Confirma la conclusión del 27/08 desde otro ángulo.

- **04/09 -- PROBLEMA ABIERTO: Uber Eats corta a los ~13-15 min.** Dos rondas
  (23:41 y 10:39), AMBAS con 4 workers y ambas a 18.1 pts/min, se cortaron en esa
  ventana: el contador de disponibles se congela y a partir de ahí TODO son
  fallos técnicos (no ensucian datos -- se guardan con error_texto, no como
  no_disponible). El bloqueo **persiste más de 10 minutos** tras parar (medido:
  una ronda lanzada 10 min después venía rota desde el primer punto, 1 acierto
  de 25). Esperar NO sirve como solución: el tiempo se dispararía.
  - **OJO, aviso metodológico**: en una primera lectura se comparó "10 workers vs
    4 workers" para concluir que el predictor era el TIEMPO y no el volumen. Esa
    comparación era ERRÓNEA -- se mezcló el worker-count de una ronda que nunca
    llegó a funcionar (lanzada sobre un bloqueo activo) con los puntos de otra.
    **Las dos rondas buenas fueron de 4 workers.** Con misma configuración y
    mismo ritmo, tiempo y volumen acumulado crecen juntos: con los datos que hay
    NO se puede distinguir cuál dispara el corte.
  - Hipótesis viva, SIN validar: la edad de la sesión del navegador (que desde
    el 03/09 se reutiliza toda la ronda). Implementado el reciclaje cada 8 min
    (`_MINUTOS_MAX_SESION` en scrapers/ubereats.py), pendiente de una prueba
    limpia. La prueba debe confirmar que el contador de disponibles SIGUE
    subiendo pasado el minuto 15.
  - **SIEMPRE sondear antes de lanzar una ronda** (un solo chequeo, 30s): si no
    devuelve un resultado bueno, el sitio sigue bloqueado y la ronda solo
    generará errores. Saltarse este paso costó una prueba entera de 13 minutos.

- **04/09 -- Otros arreglos de Glovo, todos validados en vivo**: el banner de
  cookies tarda más de 8s en aparecer bajo carga y se quedaba abierto tapando el
  flujo entero (55% -> 0% de fallos ambiguos al subir la espera a 15s); el banner
  de "sin resultados" se trataba como fallo técnico cuando es una respuesta
  válida; y se bloquean las llamadas de tracking (GTM, proxiadas por el propio
  dominio) que solo añadían carga (15% -> 10% de fallo).

- **04/09 -- Sobre llevar esto a un VPS**: Glovo y JustEat corren headless y
  técnicamente irían, pero **la IP de datacenter de un VPS previsiblemente
  empeora Glovo** (medido el 27/08: proxies de datacenter dieron 27.5% de fallo
  frente al 8.4% de la IP de la oficina). Uber Eats necesita ventana visible de
  verdad, así que haría falta probar Xvfb (display virtual) antes de contar con
  ello -- sin probar, no se sabe si Cloudflare lo acepta. Son dos incógnitas
  independientes.

- **04/09 -- Glovo: encontrada su API interna (pista fuerte, sin explotar todavía).**
  Investigando cómo bajar las peticiones por punto -- que es lo único que mueve la
  aguja con un límite por IP -- se localizó el endpoint real de datos:
  `https://api.glovoapp.com/v1/web/store_wall/search?searchQuery=Krispy+Kreme`,
  y **la ubicación se le pasa POR CABECERAS**, no por URL ni cookie:
  `glovo-delivery-location-latitude` / `-longitude`, `glovo-location-city-code`,
  más cabeceras de sesión (`glovo-device-urn`, `glovo-dynamic-session-id`,
  `glovo-perseus-*`). Cambiar de dirección seria cambiar dos cabeceras.
  - Impacto potencial: **1 petición por punto en vez de ~50** (página completa con
    su bundle). Contra un limitador que cuenta peticiones por IP, es el ataque
    correcto al cuello de botella real.
  - **Lo que falta**: replicar esa llamada desde fuera de la página da **404**, tanto
    con las cabeceras `glovo-*` como mandando las 30 capturadas. Desde dentro de la
    página con `fetch` falla por CORS (su propio JS envuelve `fetch`). Hay que
    averiguar qué valida el backend (probablemente Origin/Referer, o alguna cabecera
    que Playwright no reproduce). Si se resuelve, la vuelta de Glovo pasaría de 57 min
    a minutos.
  - Descartado por el camino: el endpoint RSC de Next.js
    (`/search?q=...&_rsc=...`) responde 200 y es ligero, pero devuelve el MISMO
    contenido para cualquier dirección (7 de 7 direcciones, incluidas 4 sin cobertura,
    daban "Krispy Kreme" presente) -- es el armazón de la página, no los resultados.
    No sirve: seria una maquina de falsos positivos.

- **04/09 -- Glovo, avance sobre la API interna: el 404 RESUELTO (idea del usuario).**
  Replicar la llamada a `api.glovoapp.com/v1/web/store_wall/search` desde fuera de la
  pagina siempre daba 404. La solucion: NO replicarla, sino **dejar que la haga la
  propia pagina e interceptarla con `context.route()` reescribiendo al vuelo las
  cabeceras** `glovo-delivery-location-latitude` / `-longitude`. Asi la peticion sale
  del contexto legitimo (sin 404, sin CORS) pero con NUESTRAS coordenadas.
  - **Confirmado que funciona**: las respuestas cambian de tamano segun la direccion
    (351 KB / 105 KB / 234 KB), o sea que la API respeta las coordenadas inyectadas.
    Con el endpoint RSC pasaba lo contrario (mismo contenido siempre) y por eso se
    descarto.
  - **Falta 1 -- leer bien la disponibilidad**: "Krispy Kreme" aparece en los metadatos
    de analitica del JSON (junto a `shopAvailabilityStatus`, `promisedDeliveryTimeRange*`,
    `searchTerm`), pero buscar su entrada de tienda por las claves `name`/`storeName` no
    la encuentra -- el campo se llama de otra forma. Hay que mapear la estructura del
    JSON antes de fiarse de nada: comprobar el texto en bruto da FALSOS POSITIVOS
    (direcciones sin cobertura salian como disponibles).
  - **Falta 2 -- que compense de verdad**: tal como se probo, se sigue cargando la
    pagina de busqueda en cada punto (1.8-2.6s), asi que NO gana nada frente a la ruta
    rapida actual. La ganancia real solo llega cargando la pagina UNA vez y disparando
    despues las busquedas desde dentro (client-side), que vuelven a llamar a la API sin
    recargar: ahi serian ~0.3s y UNA peticion por punto, que es lo que de verdad
    atacaria el limite por IP.
