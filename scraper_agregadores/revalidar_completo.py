"""Vuelta completa REAL: re-verifica cada punto activo de un agregador, tenga o no
dato ya confirmado -- a diferencia del daemon normal (que nunca retoca un punto con
dato real, ver scheduler.py) y de revalidar_ubereats_sin_poligono.py (que solo tocaba
los nunca comprobados). Sin reutilizar chequeos cercanos (radio_reuso_m=0): cada punto
se scrapea de verdad, para que la prueba de carga sea real, no una copia de datos ya
conocidos.

Pensado como prueba puntual de escalado (20+ workers por agregador, varios procesos a
la vez), no para correr en bucle sin más -- ver "cada cuánto una vuelta completa" en
ESTADO_PROYECTO.md 26/08.

Reparte DIRECCIONES INDIVIDUALES entre los workers (no tiendas enteras -- con solo 6
tiendas, cualquier worker por encima de 6 se quedaría sin nada que hacer).

Uso (un agregador por tanda, varios procesos):
    venv/Scripts/python revalidar_completo.py --agregador ubereats --worker-index 0 --worker-count 20
"""
import argparse
import asyncio
import logging

import config
from main import chequear_tienda
from scrapers.ubereats import UberEatsScraper
from utils import api_client
from utils.ventana import calcular_posicion_ventana

logging.basicConfig(level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("revalidar_completo")


async def _puntos_todos(agregador: str) -> list[dict]:
    puntos = []
    for tienda in config.TIENDAS_SCHEDULER:
        direcciones = await api_client.obtener_direcciones(tienda, cercano=False, agregador=agregador)
        for d in direcciones:
            d["tienda"] = tienda
            puntos.append(d)
    puntos.sort(key=lambda d: d["id"])
    return puntos


async def main(agregador: str, worker_index: int, worker_count: int):
    if agregador == "ubereats" and worker_count > 1:
        # Rejilla de ventanas visibles (módulo 8, ver utils/ventana.py) -- solo
        # importa para Uber Eats, JustEat/Glovo corren headless.
        posicion, tamano = calcular_posicion_ventana(worker_index)
        UberEatsScraper.posicion_ventana_visible = posicion
        UberEatsScraper.tamano_ventana_visible = tamano

    puntos = await _puntos_todos(agregador)
    asignados = [p for i, p in enumerate(puntos) if i % worker_count == worker_index]
    logger.info(
        "Worker %d/%d (%s): %d puntos de %d totales -- vuelta completa REAL, sin reuso",
        worker_index, worker_count, agregador, len(asignados), len(puntos),
    )

    for i, direccion in enumerate(asignados):
        try:
            # permitir_reuso=False: nunca reutiliza, siempre scrapea de verdad -- es una
            # prueba de carga real. radio_reuso_m=0 NO basta (el punto se encuentra a sí
            # mismo a 0m si ya tenía chequeo, confirmado en vivo 26/08).
            await chequear_tienda(
                direccion["tienda"], agregador, direcciones_override=[direccion], permitir_reuso=False
            )
        except Exception as exc:
            logger.error("Fallo revalidando %s: %r", direccion.get("direccion_text"), exc)
        if i < len(asignados) - 1:
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    logger.info("Worker %d/%d (%s) terminado.", worker_index, worker_count, agregador)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agregador", required=True, choices=["justeat", "glovo", "ubereats"])
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.agregador, args.worker_index, args.worker_count))
