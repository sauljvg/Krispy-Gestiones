"""Daemon: arranca el scheduler y lo deja corriendo hasta Ctrl+C.

Uso:
    venv/Scripts/python daemon.py

Necesita KG_API_BASE_URL y KG_API_KEY en .env apuntando a la API en vivo de Krispy
Gestiones (ver backend/agregadores_routes.py, variable de entorno AGREGADORES_API_KEY
del lado del servidor debe coincidir con KG_API_KEY aquí).
"""
import asyncio
import logging

import config
from scheduler import crear_scheduler, es_horario_apertura

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("daemon")


async def main():
    if not config.KG_API_KEY:
        logger.warning(
            "KG_API_KEY no configurada (.env) — la API de KG rechazará todas las peticiones."
        )

    scheduler = crear_scheduler()
    scheduler.start()

    logger.info(
        "Scraper daemon iniciado contra %s. Cercano cada %d min, completo cada %d min, "
        "ambos solo durante horario de apertura (%s). En este momento %s horario de apertura.",
        config.KG_API_BASE_URL,
        config.FRECUENCIA_CHEQUEO_CERCANO_MIN,
        config.FRECUENCIA_CHEQUEO_COMPLETO_MIN,
        config.HORARIOS_APERTURA,
        "SÍ es" if es_horario_apertura() else "NO es",
    )

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Deteniendo scraper daemon...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
