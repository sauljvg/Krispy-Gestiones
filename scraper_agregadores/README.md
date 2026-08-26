# Scraper Agregadores — Krispy Kreme Madrid

Corre en un portátil aparte (necesita un navegador real — Uber Eats exige ventana visible,
ver nota anti-bot abajo). Comprueba disponibilidad en JustEat/Glovo/Uber Eats para un grid
de direcciones alrededor de cada tienda y manda cada resultado a la API en vivo de Krispy
Gestiones (`backend/agregadores_routes.py`) — no guarda nada localmente. El grid, el
geocoding y todo el histórico viven en el servidor.

## Setup

```bash
cd scraper_agregadores
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt
venv/Scripts/python -m playwright install chromium
cp .env.example .env
```

Rellena en `.env`:
- `KG_API_BASE_URL`: URL de la app desplegada (o `http://localhost:8000` si estás
  probando contra un backend corriendo en local).
- `KG_API_KEY`: debe coincidir con la variable de entorno `AGREGADORES_API_KEY` del
  backend (si no está puesta ahí, la API rechaza todas las peticiones del scraper).

## Validar (chequeo manual, 1 dirección por agregador)

```bash
venv/Scripts/python main.py
```

## Correr el scheduler (automático, dos velocidades)

```bash
venv/Scripts/python daemon.py
```

Cercano cada 10 min (pocos puntos, reacción rápida a un bloqueo total), completo cada 60
min (grid completo, mapea la zona de cobertura). Solo dentro de horas punta (9:00-22:00).
No es "datos en vivo": el objetivo es un informe de cuándo y dónde bloquean, no un
dashboard en tiempo real — por eso el completo no va cada 10 min (una pasada tarda ~30-40
min con las pausas anti-bot; programarlo más seguido dejaría el scraper trabajando casi
sin parar toda la franja de apertura).

### Varias instancias en paralelo (refuerzo puntual)

Con `SCRAPER_WORKERS=N` en el `.env` de una máquina, `iniciar_daemon.bat` lanza N
procesos de `daemon.py` en paralelo, repartiéndose el trabajo entre sí por (tienda,
agregador) -- nunca se pisan ni repiten direcciones que ya tienen dato. Pensado para
encender un ordenador con más CPU/RAM puntualmente como refuerzo del que corre 24/7
(que se queda con `SCRAPER_WORKERS` sin definir = 1, comportamiento normal). Ambos
mandan a la misma API en vivo.

## Notas anti-bot

- **JustEat**: puede bloquear temporalmente (WAF) tras muchas peticiones seguidas desde la
  misma IP. Por eso hay pausa (`DELAY_ENTRE_CHEQUEOS_SEG`) entre chequeos.
- **Uber Eats**: Cloudflare bloquea Chromium headless en este sitio incluso con
  `playwright-stealth`. La solución fue lanzar el navegador en modo visible
  (`iniciar_headless = False` en `UberEatsScraper`) — pasa sin intervención manual. Si algún
  día también bloquea el modo visible, `BaseAggregatorScraper` ya tiene soporte para pausar
  y pedir que un humano resuelva el challenge a mano (con timeout, solo si hay terminal
  interactiva — ver `_comprobar_challenge` en `scrapers/base.py`), pero de momento no ha
  hecho falta.
- Los carruseles/banners promocionales en autoplay de estos sitios hacían que Playwright
  reintentara con scroll una y otra vez (esperando a que el elemento "se estabilice");
  `scrapers/base.py` desactiva animaciones/transiciones CSS al cargar la página para
  evitarlo.
