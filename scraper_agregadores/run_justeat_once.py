"""Chequeo completo de un solo agregador (JustEat), para repasar rápido tras
un fix sin tener que volver a esperar a Glovo/Uber Eats también."""
import asyncio
import logging

import config
from main import chequear_tienda

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


async def main():
    for tienda in config.TIENDAS_SCHEDULER:
        await chequear_tienda(
            tienda, "justeat", cercano=False, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG
        )


if __name__ == "__main__":
    asyncio.run(main())
