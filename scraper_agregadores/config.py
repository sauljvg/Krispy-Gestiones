import os

from dotenv import load_dotenv

load_dotenv()

# El grid/geocoding y la persistencia viven en la API de KG (backend/agregadores.py) —
# este scraper solo necesita saber qué tiendas comprobar y a qué API hablarle. La lista de
# tiendas/slugs es la misma que backend/agregadores.py; si se añade una tienda ahí, hay que
# añadirla aquí también (o promover esto a un GET /api/agregadores/tiendas si se automatiza).
TIENDAS_SCHEDULER = ["parquesur", "princesa", "caleido", "granplaza2", "plenilunio", "lagavia"]

# Hora de cierre de cada tienda (hora local, formato 24h) -- un chequeo hecho
# tras el cierre puede salir "cerrado por horario" en vez de reflejar
# cobertura real, contaminando la búsqueda de límite (confirmado en vivo
# 08/08). Todas confirmadas en la ficha real de cada tienda en Google Maps
# (no en la web genérica de "horario de restauración" del centro comercial,
# que resultó no coincidir -- p.ej. Caleido decía cierre a las 21:00 ahí,
# pero la ficha real de la tienda y la actividad en vivo esa noche confirman
# 23:00). Parquesur/Princesa/Caleido además confirmadas a mano esa misma noche.
HORARIOS_CIERRE_TIENDAS = {
    "parquesur": 22.5,   # 22:30 -- confirmado a mano 08/08 y en Google Maps (ya aparecía "Cerrado" a las 22:2x)
    "princesa": 23.0,    # 23:00 -- confirmado a mano 08/08 y en Google Maps ("Cierra pronto · 11 p.m.")
    "caleido": 23.0,     # 23:00 -- confirmado a mano 08/08 y en Google Maps ("Cierra pronto · 11 p.m.")
    "granplaza2": 22.5,  # 22:30 -- confirmado en Google Maps (ficha real de la tienda)
    "plenilunio": 22.0,  # 22:00 -- confirmado en Google Maps (ficha real, horario 10:00-22:00 todos los días)
    "lagavia": 22.0,     # 22:00 -- confirmado en Google Maps (ficha real, horario 10:00-22:00 todos los días)
}

# Uber Eats reactivado 09/08: el bloqueo anti-bot 100% confirmado el 07/08 se
# debía a que la ventana no-headless se mandaba fuera de pantalla -- con
# BaseAggregatorScraper.mantener_visible=True (ver scrapers/base.py) la
# ventana queda genuinamente visible en el segundo monitor y deja de
# bloquear (commit 80ee533). Cada chequeo de Uber Eats abre una ventana de
# Chrome real y visible mientras el daemon corre -- es esperado, no un bug.
AGREGADORES = ["justeat", "glovo", "ubereats"]

# No queremos "datos en vivo": el objetivo es un informe de "a esta hora bloquearon en esta
# zona", no un dashboard en tiempo real. Por eso dos velocidades:
#   - CERCANO: pocos puntos (1 km), frecuente — detecta rápido un bloqueo total real.
#   - COMPLETO: los 48 puntos, con más margen — mapea la zona sin machacar el sitio (una
#     pasada completa tarda ~30-40 min con las pausas anti-bot).
FRECUENCIA_CHEQUEO_CERCANO_MIN = 10
FRECUENCIA_CHEQUEO_COMPLETO_MIN = 60

HORARIOS_APERTURA = [{"inicio": 9, "fin": 22}]

# Pausa entre chequeos individuales (dirección x agregador) para reducir el riesgo de
# bloqueo anti-bot al no lanzar ráfagas de peticiones seguidas contra el mismo sitio.
DELAY_ENTRE_CHEQUEOS_SEG = 4

SCRAPER_ENABLED = os.getenv("SCRAPER_ENABLED", "True") == "True"
SCRAPER_LOG_LEVEL = os.getenv("SCRAPER_LOG_LEVEL", "INFO")
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "30"))
SCRAPER_RETRY_MAX = int(os.getenv("SCRAPER_RETRY_MAX", "3"))

KG_API_BASE_URL = os.getenv("KG_API_BASE_URL", "http://localhost:8000")
KG_API_KEY = os.getenv("KG_API_KEY", "")

# Modo pruebas: mientras se está estabilizando un scraper (ver Uber Eats,
# agosto 2026), correr contra producción de verdad escribe datos rotos que
# hay que andar limpiando a mano (agregadores_chequeos/alertas). Con esto en
# True, el scraper sigue navegando y leyendo los sitios reales -- solo deja
# de mandar los resultados a la API de KG (ver utils/api_client.py). Sigue
# leyendo el grid de direcciones real (no escribe nada, no hace falta
# aislarlo). Volver a "False" cuando se confirme que el scraper es estable.
MODO_LOCAL = os.getenv("SCRAPER_MODO_LOCAL", "False") == "True"
