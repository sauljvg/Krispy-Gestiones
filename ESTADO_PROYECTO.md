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
  clon también estaba desactualizado). Decidir qué mecanismo de autoarranque
  se queda (Task Scheduler `setup_tarea_programada.ps1` vs el acceso directo
  en la carpeta de Inicio que se añadió esta sesión) y quitar el otro. Para
  ver el mini dashboard local en esa máquina: `venv/Scripts/python
  status_server.py` dentro de `scraper_agregadores/`, abre en
  `localhost:8787`.
