import os

from dotenv import load_dotenv

load_dotenv()

# El grid/geocoding y la persistencia viven en la API de KG (backend/agregadores.py) —
# este scraper solo necesita saber qué tiendas comprobar y a qué API hablarle. La lista de
# tiendas/slugs es la misma que backend/agregadores.py; si se añade una tienda ahí, hay que
# añadirla aquí también (o promover esto a un GET /api/agregadores/tiendas si se automatiza).
TIENDAS_SCHEDULER = ["parquesur"]

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
