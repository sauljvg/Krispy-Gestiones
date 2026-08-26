"""Pasada puntual: revalida de verdad (sin el atajo del polígono de cobertura ya
confirmado) los puntos de Uber Eats que el mapa real todavía marca "Sin datos" pero
que el scheduler normal se salta por caer dentro del polígono -- ver
ignorar_poligono en backend/agregadores.py::get_o_crear_direcciones. La regla del
polígono se queda intacta para el daemon de siempre (24/7): esto es solo un pase
manual puntual, no algo programado.

Reparte DIRECCIONES INDIVIDUALES entre los workers (no tiendas enteras, como hace
el daemon normal) -- con solo 6 tiendas, repartir por tienda desaprovecharía
cualquier worker por encima de 6.

Uso (varios procesos en paralelo):
    venv/Scripts/python revalidar_ubereats_sin_poligono.py --worker-index 0 --worker-count 10
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
logger = logging.getLogger("revalidar_ubereats")


async def _puntos_pendientes() -> list[dict]:
    pendientes = []
    for tienda in config.TIENDAS_SCHEDULER:
        direcciones = await api_client.obtener_direcciones(
            tienda, cercano=False, agregador="ubereats", solo_sin_datos=True, ignorar_poligono=True
        )
        for d in direcciones:
            d["tienda"] = tienda
            pendientes.append(d)
    pendientes.sort(key=lambda d: d["id"])
    return pendientes


async def main(worker_index: int, worker_count: int):
    if worker_count > 1:
        # Rejilla compartida con daemon.py/buscar_limite_cobertura.py -- evita que las
        # ventanas visibles de Uber Eats de varios workers queden apiladas. Con más de
        # 8 workers los slots se reparten (módulo 8, ver utils/ventana.py).
        posicion, tamano = calcular_posicion_ventana(worker_index)
        UberEatsScraper.posicion_ventana_visible = posicion
        UberEatsScraper.tamano_ventana_visible = tamano

    pendientes = await _puntos_pendientes()
    asignados = [p for i, p in enumerate(pendientes) if i % worker_count == worker_index]
    logger.info(
        "Worker %d/%d: %d puntos de %d totales pendientes (sin dato propio, ignorando polígono)",
        worker_index, worker_count, len(asignados), len(pendientes),
    )

    for i, direccion in enumerate(asignados):
        try:
            # radio_reuso_m=400 (no los 100m normales): estos puntos ya están dentro
            # del polígono de cobertura confirmado, así que un dato real algo más
            # lejos sigue siendo representativo -- pedido explícito del usuario 26/08
            # para esta pasada puntual en concreto.
            await chequear_tienda(
                direccion["tienda"], "ubereats", direcciones_override=[direccion], radio_reuso_m=400
            )
        except Exception as exc:
            logger.error("Fallo revalidando %s: %r", direccion.get("direccion_text"), exc)
        if i < len(asignados) - 1:
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    logger.info("Worker %d/%d terminado.", worker_index, worker_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.worker_index, args.worker_count))
