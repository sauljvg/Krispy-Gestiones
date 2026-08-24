import asyncio
import logging

import config
from scheduler import chequeo_completo

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

if __name__ == "__main__":
    asyncio.run(chequeo_completo())
