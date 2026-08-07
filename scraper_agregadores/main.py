"""Entry point: ejecuta un chequeo (una tienda x direcciones x un agregador) y lo envía a
la API en vivo de KG. Sin DB local — ver utils/api_client.py."""
import asyncio
import logging
import re

import config
from scrapers.glovo import GlovoScraper
from scrapers.justeat import JustEatScraper
from scrapers.ubereats import UberEatsScraper
from utils import api_client

logging.basicConfig(level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

SCRAPERS = {
    "justeat": JustEatScraper,
    "glovo": GlovoScraper,
    "ubereats": UberEatsScraper,
}


async def chequear_tienda(
    tienda: str,
    agregador_nombre: str,
    cercano: bool = False,
    max_direcciones: int = None,
    delay_seg: int = 0,
):
    direcciones = await api_client.obtener_direcciones(tienda, cercano=cercano, agregador=agregador_nombre)
    if max_direcciones:
        direcciones = direcciones[:max_direcciones]

    scraper = SCRAPERS[agregador_nombre](
        timeout_seg=config.SCRAPER_TIMEOUT, retry_max=config.SCRAPER_RETRY_MAX
    )

    fallos_consecutivos = 0

    for i, direccion in enumerate(direcciones):
        # Muchos puntos del grid caen en autovías/polígonos donde Nominatim no devuelve
        # número de portal (ej. "Calle Puerto de Pajares, Poligono..." en vez de "15, Calle
        # ..."). Sin número, el autocompletado del agregador puede sugerir un punto distinto
        # al que realmente queremos comprobar -- se usan las coordenadas directamente en ese
        # caso (Google Places, que es lo que usan estos tres, las reconoce y apunta exacto).
        texto = direccion["direccion_text"]
        tiene_numero = bool(re.match(r"^\d", texto.strip()))
        # JustEat no reconoce coordenadas en bruto en su buscador de dirección
        # (confirmado: nunca aparece ninguna sugerencia, siempre timeout) --
        # a diferencia de Uber Eats/Glovo, que sí las resuelven bien. Para
        # JustEat se manda siempre el texto, aunque sea una vía sin número.
        usa_coordenadas = not tiene_numero and agregador_nombre != "justeat"
        consulta = f'{direccion["lat"]:.6f}, {direccion["lng"]:.6f}' if usa_coordenadas else texto

        logger.info("Chequeando %s / %s @ %s", tienda, agregador_nombre, texto)
        resultado = await scraper.verificar_disponibilidad(tienda, consulta)

        respuesta = await api_client.enviar_chequeo(
            {
                "tienda": tienda,
                "agregador": agregador_nombre,
                "direccion_id": direccion["id"],
                "disponible": resultado.disponible,
                "tiempo_entrega_min": resultado.tiempo_entrega_min,
                "mensaje_bloqueo": resultado.mensaje_bloqueo,
                "error_texto": resultado.error_texto,
            }
        )

        if respuesta.get("transicion") and resultado.url_captura:
            logger.warning(
                "%s: %s dejó de estar disponible (era disponible en el chequeo anterior) -- subiendo captura",
                agregador_nombre,
                texto,
            )
            await api_client.subir_captura(respuesta["chequeo_id"], resultado.url_captura)

        logger.info("  -> disponible=%s tiempo=%s min", resultado.disponible, resultado.tiempo_entrega_min)

        if resultado.error_texto:
            fallos_consecutivos += 1
        else:
            fallos_consecutivos = 0

        if delay_seg and i < len(direcciones) - 1:
            await asyncio.sleep(delay_seg)


async def main():
    # Chequeo manual de validación: solo 1 dirección (la propia tienda) por agregador.
    for tienda in config.TIENDAS_SCHEDULER:
        for agregador_nombre in SCRAPERS:
            await chequear_tienda(tienda, agregador_nombre, cercano=True, max_direcciones=1)


if __name__ == "__main__":
    asyncio.run(main())
