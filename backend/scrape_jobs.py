"""Registro de qué tiendas pertenecen a cada empresa (KK/SAONA).

Antes también lanzaba scraper_v2.py como subproceso desde el botón
"Actualizar" del dashboard, pero el contenedor de producción no tiene Chrome
instalado — ese botón nunca funcionó de verdad ahí (fallaba en silencio) y
se quitó. El scraping de Maps sigue existiendo como herramienta de terminal
en local (scraper/scraper_v2.py) para quien tenga Chrome con sesión propia;
dentro de la app, la vía soportada para traer reseñas es "Importar Takeout".
"""
import os
import sys

SCRAPER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scraper"))

sys.path.insert(0, SCRAPER_DIR)
from stores import STORES  # noqa: E402


def tiendas_de_empresa(empresa):
    """Nombres públicos de las tiendas de una marca ("kk" o "saona") — lo usa
    el middleware de main.py para que el dashboard de Reseñas de una marca no
    pueda ver reseñas de la otra (misma tabla `reviews`, sin columna propia
    de empresa: la separación vive aquí, en el registro de tiendas)."""
    return [data["nombre"] for data in STORES.values() if data.get("empresa", "kk") == empresa]
