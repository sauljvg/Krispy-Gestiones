import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# DATA_DIR es la misma variable de entorno que usa backend/db.py para
# apuntar al volumen persistente en producción — sin esto, el import de
# Takeout (y cualquier otro uso de este config.py) escribía en un
# krispy_kreme.db distinto dentro de la carpeta del proyecto, invisible
# para la app real y probablemente no escribible en el contenedor.
DATA_DIR = os.environ.get("DATA_DIR") or PROJECT_ROOT
DB_PATH = os.path.join(DATA_DIR, "krispy_kreme.db")
JSON_OUTPUT_PATH = os.path.join(PROJECT_ROOT, "krispy_kreme_todas_resenas.json")
CSV_OUTPUT_PATH = os.path.join(PROJECT_ROOT, "krispy_kreme_todas_resenas.csv")

# Scroll/scrape tuning
MAX_SCROLL_ITERATIONS = 8000
# Con 4 pasadas (relevantes/recientes/mejor/peor) cada una debe rendirse rápido
# si de verdad está atascada, para no gastar toda la ejecución en la primera.
MAX_ITERATIONS_WITHOUT_GROWTH = 70
SCROLL_PAUSE_SECONDS = 0.9
MAX_SCROLL_PAUSE_SECONDS = 4.0
EXPAND_EVERY_N_ITERATIONS = 3
CHECKPOINT_EVERY_N_REVIEWS = 100
