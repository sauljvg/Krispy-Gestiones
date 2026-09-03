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
#
# Orden con ubereats primero (pedido explícito del usuario 26/08: priorizarlo
# porque suele acumular más pendientes) -- scheduler.py reparte el trabajo
# entre workers en este mismo orden (agregador-major, ver _pares_asignados),
# así que ubereats ocupa los primeros huecos del reparto round-robin y le
# toca a más workers en paralelo cuando hay varios corriendo a la vez.
AGREGADORES = ["ubereats", "glovo", "justeat"]

# Dos cadencias (10 min / 60 min) sobre EL MISMO trabajo: cubrir puntos sin
# datos aún, para seguir empujando el descubrimiento del borde de cobertura
# (ver scheduler.py). Ya no hay un recorrido "completo" que re-chequee lo ya
# confirmado -- eso es una necesidad de otra fase, una vez el borde esté
# confirmado, no de esta (pedido explícito del usuario 10/08). Se mantienen
# las dos cadencias tal cual por si conviene retomar una vigilancia periódica
# más adelante sin tener que rehacer el scheduler entero.
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

# Cuántas tiendas corre el scheduler EN PARALELO dentro de una misma pasada (ver
# scheduler.py::_chequeo) -- antes de 02/09 las 6 tiendas de TIENDAS_SCHEDULER se
# procesaban una detrás de otra (solo los 3 agregadores DENTRO de cada tienda corrían a
# la vez), y como Uber Eats es el más lento de los tres (ventana de Chrome visible real,
# no headless -- ver AGREGADORES arriba), el tiempo total de una pasada completa era
# aprox. 6 x (tiempo de Uber Eats por tienda) -- ~33 min medidos en vivo por el usuario
# el 02/09. Con MAX_TIENDAS_PARALELO tiendas a la vez, el límite pasa a ser ~ceil(6 /
# MAX_TIENDAS_PARALELO) x (tiempo de Uber Eats por tienda).
#
# Por defecto 3 (no las 6 de golpe): esto multiplica por hasta 3 el número de ventanas
# de Chrome visibles de Uber Eats abiertas a la vez en el portátil que corre el daemon
# 24/7 (ver docstring de scheduler.py) -- buscar_limite_cobertura.py ya probó en vivo
# que 8 procesos Chrome en paralelo van bien de CPU/RAM (ver utils/ventana.py), pero
# esos son procesos sueltos lanzados a mano, no algo desatendido 24/7. Subir esto a 6
# (máximo paralelismo real, una tienda por celda de la rejilla) es seguro de probar si
# el equipo aguanta bien con 3 sin problemas.
MAX_TIENDAS_PARALELO = int(os.getenv("MAX_TIENDAS_PARALELO", "3"))

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

# Proxies opcionales (27/08, experimento gratis de rotación de IP para ver si baja
# el bloqueo "Oh, no!" de Glovo bajo carga -- ver revalidar_completo.py --proxy-index).
# Formato en .env: SCRAPER_PROXIES="host1:puerto1:usuario1:pass1,host2:puerto2:usuario2:pass2"
# (así viene el "Proxy List" de Webshare, un proxy por línea separados por ":").
# Vacío por defecto -- sin esto configurado, todo sigue igual que siempre (IP propia).
def _parsear_proxies(raw: str) -> list[dict]:
    proxies = []
    for entrada in raw.split(","):
        entrada = entrada.strip()
        if not entrada:
            continue
        partes = entrada.split(":")
        if len(partes) != 4:
            continue
        host, puerto, usuario, password = partes
        proxies.append({"server": f"http://{host}:{puerto}", "username": usuario, "password": password})
    return proxies


PROXIES = _parsear_proxies(os.getenv("SCRAPER_PROXIES", ""))
