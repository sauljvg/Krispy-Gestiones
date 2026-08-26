"""Pasada puntual solo para las tiendas que fallaron en el scrap completo --
un blip de red hizo que obtener_direcciones() fallara con timeout para 5 de
las 6 tiendas seguidas (parquesur sí completó bien), así que no hace falta
repetirla."""
import asyncio
import logging

import config
from scheduler import _chequear_agregador_aislado
from main import SCRAPERS

logging.basicConfig(level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_faltantes")

TIENDAS_FALTANTES = ["princesa", "caleido", "granplaza2", "plenilunio", "lagavia"]


async def main():
    exitosos = fallidos = 0
    for tienda in TIENDAS_FALTANTES:
        resultados = await asyncio.gather(
            *(_chequear_agregador_aislado(tienda, agregador_nombre, cercano=False) for agregador_nombre in SCRAPERS)
        )
        exitosos += sum(1 for r in resultados if r)
        fallidos += sum(1 for r in resultados if not r)
    logger.info("Pasada de faltantes terminada: %d ok, %d fallidos.", exitosos, fallidos)


if __name__ == "__main__":
    asyncio.run(main())
