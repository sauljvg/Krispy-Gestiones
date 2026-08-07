"""Entry point: ejecuta un chequeo (una tienda x direcciones x un agregador) y lo envía a
la API en vivo de KG. Sin DB local — ver utils/api_client.py."""
import asyncio
import logging

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
        # Antes se mandaban las coordenadas en bruto ("lat, lng") cuando la
        # dirección no tenía número de portal, asumiendo que el autocompletado
        # de Google Places las reconocía y apuntaba exacto. Confirmado que es
        # falso: el autocompletado de Google Places busca por TEXTO (nombres
        # de sitio/dirección), no geocodifica coordenadas -- probado en vivo
        # con un punto real de Glovo ("Anillo Verde Ciclista"): las
        # coordenadas devolvían de forma consistente y repetible una
        # sugerencia de otro sitio ("Puente Castilla, 1054", a varios km),
        # mientras que el mismo texto sin número resolvía perfecto. Se manda
        # siempre el texto, tenga número o no (ver investigar_glovo_direccion.py).
        texto = direccion["direccion_text"]
        consulta = texto

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

        # Se sube la captura de CADA chequeo, no solo de las transiciones --
        # confirmado un caso real donde un resultado se dio con confianza
        # total pero sobre la dirección equivocada (bug de coordenadas en
        # bruto ya arreglado arriba); sin poder ver la captura desde el
        # dashboard no había forma de detectarlo.
        if resultado.url_captura:
            if respuesta.get("transicion"):
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
