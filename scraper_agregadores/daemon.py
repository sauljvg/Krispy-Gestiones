"""Daemon: arranca el scheduler y lo deja corriendo hasta Ctrl+C.

Uso:
    venv/Scripts/python daemon.py
    venv/Scripts/python daemon.py --worker-index 2 --worker-count 6

Necesita KG_API_BASE_URL y KG_API_KEY en .env apuntando a la API en vivo de Krispy
Gestiones (ver backend/agregadores_routes.py, variable de entorno AGREGADORES_API_KEY
del lado del servidor debe coincidir con KG_API_KEY aquí).

--worker-index/--worker-count: para correr varios daemons en paralelo en la misma
máquina (ver iniciar_daemon.bat + SCRAPER_WORKERS en .env) -- pensado para cuando el
ordenador personal (OP) se enciende como refuerzo del portátil de trabajo (OT), que
corre 24/7 con un solo worker. Cada worker se queda con una porción distinta del
trabajo (ver scheduler.py::_pares_asignados), nunca se pisan entre sí. Sin estos flags
(valores por defecto 0/1) el comportamiento es exactamente el de siempre: un solo
proceso cubriendo todo.
"""
import argparse
import asyncio
import logging

import config
from scheduler import crear_scheduler, es_horario_apertura, _pares_asignados
from scrapers.ubereats import UberEatsScraper
from utils.ventana import calcular_posicion_ventana

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("daemon")


async def main(worker_index: int, worker_count: int):
    if not config.KG_API_KEY:
        logger.warning(
            "KG_API_KEY no configurada (.env) — la API de KG rechazará todas las peticiones."
        )

    if worker_count > 1:
        # Sin esto, las ventanas visibles de Uber Eats de varios workers en paralelo
        # quedarían apiladas en el mismo punto de pantalla (ver utils/ventana.py).
        posicion, tamano = calcular_posicion_ventana(worker_index)
        UberEatsScraper.posicion_ventana_visible = posicion
        UberEatsScraper.tamano_ventana_visible = tamano

    scheduler = crear_scheduler(worker_index=worker_index, worker_count=worker_count)
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
    if worker_count > 1:
        logger.info(
            "Worker %d/%d -- pares (tienda, agregador) asignados: %s",
            worker_index, worker_count, _pares_asignados(),
        )

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Deteniendo scraper daemon...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.worker_index, args.worker_count))
