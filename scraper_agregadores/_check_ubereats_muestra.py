"""Prueba más amplia de Uber Eats tras el fix del falso positivo -- varias
direcciones en varias tiendas, modo local (no escribe en producción), para
confirmar que el arreglo aguanta antes de plantear reactivarlo."""
import asyncio
import logging

import config
from main import chequear_tienda

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
config.MODO_LOCAL = True


async def main():
    for tienda in ["parquesur", "princesa", "caleido"]:
        await chequear_tienda(tienda, "ubereats", cercano=True, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG)


if __name__ == "__main__":
    asyncio.run(main())
