"""Comprobación puntual de Uber Eats -- 1 sola dirección, modo local (no
escribe en producción). Para probar el aviso de captcha + resolución manual."""
import asyncio
import logging

import config
from main import chequear_tienda
from scrapers.ubereats import UberEatsScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
config.MODO_LOCAL = True

# Este script es justo para que un humano lo lance a mano desde su propia
# terminal y esté pendiente -- por eso (y solo aquí) se reactiva la ventana
# visible + aviso al detectar un challenge real. El resto de scripts
# (daemon, scheduler, pruebas en background) se quedan con el default
# (False) para no disparar notificaciones cuando no hay nadie mirando.
UberEatsScraper.permitir_resolucion_manual = True


async def main():
    await chequear_tienda("parquesur", "ubereats", cercano=True, max_direcciones=1)


if __name__ == "__main__":
    asyncio.run(main())
