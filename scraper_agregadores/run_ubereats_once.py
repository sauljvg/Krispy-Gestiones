"""Chequeo completo de un solo agregador (Uber Eats), para repasar rápido tras
un fix sin tener que volver a esperar a JustEat/Glovo también."""
import asyncio
import logging

import config
from main import chequear_tienda

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# Uber Eats está desactivado en producción (ver config.AGREGADORES) hasta que
# esté estable -- este script es justo para seguir probándolo en local, así
# que fuerza el modo dry-run sin depender de que .env lo tenga puesto.
config.MODO_LOCAL = True


async def main():
    for tienda in config.TIENDAS_SCHEDULER:
        await chequear_tienda(
            tienda, "ubereats", cercano=False, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG
        )


if __name__ == "__main__":
    asyncio.run(main())
