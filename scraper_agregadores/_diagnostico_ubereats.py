"""Diagnóstico silencioso de Uber Eats -- sin ventana visible, sin notificaciones,
modo local (no escribe en producción). Solo para ver qué pasa de verdad y
guardar una captura si detecta un challenge."""
import asyncio
import logging

import config
from main import chequear_tienda

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
config.MODO_LOCAL = True


async def main():
    await chequear_tienda("parquesur", "ubereats", cercano=True, max_direcciones=3)


if __name__ == "__main__":
    asyncio.run(main())
