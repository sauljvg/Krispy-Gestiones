# Krispy Track — Analítica de reseñas de Google Maps

Plataforma para extraer, analizar y visualizar las reseñas de Google Maps de
varias tiendas Krispy Kreme (ver `scraper/stores.py` para el listado actual).

## Estructura

```
proyecto-krispy-analytics/
├── scraper/
│   ├── scraper_v2.py      # Extractor (Selenium)
│   ├── stores.py          # Registro de tiendas (nombre + URL de Google Maps)
│   └── config.py          # Parámetros de scroll
├── common.py               # Parseo de fechas relativas + sentimiento (compartido)
├── backend/
│   ├── main.py             # App FastAPI
│   ├── routes.py           # Endpoints /api/*
│   ├── db.py                # Conexión SQLite
│   ├── analytics.py         # Stats, timeline, keywords
│   └── utils.py              # Paginación, CSV
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/{filters,analytics,dashboard}.js
├── krispy_kreme.db          # Se genera al correr el scraper
├── requirements.txt
└── .replit                  # Config de despliegue (Replit)
```

## 1. Extraer las reseñas

```bash
cd scraper
python scraper_v2.py              # tienda por defecto (parquesur)
python scraper_v2.py <clave>       # otra tienda, ver stores.py
```

Abre una ventana real de Chrome (no headless) y hace scroll sobre el panel de
reseñas de Google Maps hasta cargarlas todas. Google las sirve en lotes con
latencia variable, así que el proceso puede tardar bastante y a veces se
queda "parado" varios minutos entre lotes — es normal, el script espera con
backoff adaptativo antes de darse por vencido. En la práctica, sesiones
automatizadas parecen tener un tope real de cuántas reseñas sirve Google (no
siempre se llega al 100% del total anunciado).

Guarda checkpoints cada ~100 reseñas nuevas en `krispy_kreme.db`, `.json` y
`.csv`, así que si el proceso se corta (conexión, cierre de la ventana) no se
pierde el progreso — solo hay que volver a lanzarlo (vuelve a extraer desde
cero, pero lo ya guardado en `krispy_kreme.db` queda como estaba hasta ese
punto).

### Añadir una tienda nueva

Añadir una entrada en `scraper/stores.py` con la clave, el nombre a mostrar y
la URL de Google Maps de esa tienda. Todas las reseñas quedan en la misma
`krispy_kreme.db`, distinguidas por la columna `tienda` — el dashboard y la
API ya filtran/agrupan por tienda automáticamente.

### Actualizar una tienda ya scrapeada (rápido)

```bash
python scraper_v2.py <clave> --update
```

En vez de recorrer todo el histórico otra vez, ordena por "Más recientes" y
para el scroll en cuanto encuentra 15 reseñas seguidas que ya están en la BD
(todo lo que viene después, en orden cronológico, ya lo tenemos). Para una
tienda con pocas reseñas nuevas desde la última vez, esto tarda segundos en
vez de los 15-60+ minutos de un scrape completo.

## 2. Levantar la app (API + dashboard, un solo proceso)

```bash
pip install -r requirements.txt
python backend/main.py
```

Sirve todo en `http://127.0.0.1:8000` — el backend monta el frontend estático
en `/`, así que un único proceso basta tanto en local como al desplegar (ver
`.replit`). También puede lanzarse con `uvicorn backend.main:app --host
0.0.0.0 --port 8000`.

- El botón "Actualizar" y el scheduler nocturno automático que lanzaban
  `scraper_v2.py` desde la web se quitaron: el contenedor de producción no
  tiene Chrome instalado, así que nunca funcionaron ahí de verdad. La vía
  soportada dentro de la app para traer reseñas es **"Importar Takeout"**
  (botón en el dashboard, sube el `.zip` que exporta Google Takeout de
  "Perfil de Empresa en Google" — lee todas las oficiales y solo añade las
  que falten, sin duplicar). El scraping de Maps con Selenium sigue
  existiendo como herramienta de terminal en local
  (`scraper/scraper_v2.py`, con o sin `--update`), para quien tenga Chrome
  con sesión propia.
- `scraper/scraper_v2.py <clave> --reconciliar` y `scraper/scrap_absoluto.py`
  siguen existiendo como scripts de terminal, pero **la vía para subir su
  resultado a producción (`POST /api/reviews/reconciliacion`) se quitó**: ya
  no se scrapea Maps en vivo, solo se importa vía Google Takeout, así que el
  número de reseñas "que Google anuncia" quedaba siempre desactualizado y
  confundía. El dashboard ya no muestra ese número ni tiene el toggle "Solo
  Google".

La mayoría de endpoints de lectura aceptan los mismos
filtros `tienda`, `rating`, `sentiment`, `date_from`, `date_to`, `q` — así que
las estadísticas, gráficos y exportaciones siempre reflejan lo que esté
filtrado en el dashboard, no el total global:

- `GET /api/stores` — tiendas presentes en la BD con su nº de reseñas
- `GET /api/stats` — total, promedio, distribución por estrellas, % positivas
- `GET /api/timeline` — reseñas y promedio por mes
- `GET /api/keywords` — palabras más mencionadas
- `GET /api/staff-mentions` — ranking de personal mencionado (actuales/anteriores)
- `GET /api/reviews` — listado paginado, con filtros `tienda`, `rating`,
  `sentiment`, `date_from`, `date_to`, `q` (búsqueda en texto/autor), `staff`, `sort`
- `GET /api/reviews/export` — CSV con los mismos filtros
- `GET /api/reviews/export/xlsx` — Excel (.xlsx) con los mismos filtros

## 3. Desplegar

En producción (Railway, ver `Dockerfile`) `DATA_DIR` apunta a un volumen
persistente donde vive `krispy_kreme.db` — **la base de datos está
deliberadamente fuera de git** (ver `.gitignore`), así que nunca se
actualiza con un `git push`: los datos nuevos entran solo vía "Importar
Takeout" en la web, o restaurando un backup (ver `backend/backups.py`). El
scraping con Selenium necesita un Chrome real y solo puede correr en local,
nunca en el contenedor de producción.

## Notas sobre el análisis de sentimiento

La etiqueta positivo/neutral/negativo se basa principalmente en la
calificación en estrellas del propio usuario (4-5★ = positivo, 3★ = neutral,
1-2★ = negativo), reforzada con un score de texto (léxico simple en
español) usado solo para búsqueda/orden fino. Es más fiable que un análisis
de texto puro, porque la estrella es la señal que el propio usuario dio.
