"""Entry point: ejecuta un chequeo (una tienda x direcciones x un agregador) y lo envía a
la API en vivo de KG. Sin DB local — ver utils/api_client.py."""
import asyncio
import logging

import config
from scrapers.base import MARCADOR_TIENDA_NO_CONFIRMADA
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
    solo_sin_datos: bool = False,
    direcciones_override: list = None,
    radio_reuso_m: float = 100,
):
    """direcciones_override: si se pasa, se usa esta lista tal cual en vez de pedirle
    una nueva a la API (cercano/solo_sin_datos se ignoran en ese caso) -- para pasadas
    puntuales que ya eligieron ellas mismas qué direcciones tocan (ver
    revalidar_ubereats_sin_poligono.py, que reparte direcciones individuales entre
    varios workers en vez de tiendas enteras).

    radio_reuso_m: radio para reutilizar un chequeo cercano en vez de scrapear (100m
    por defecto). Más amplio (p.ej. 400m) tiene sentido dentro de una zona cuyo
    polígono de cobertura ya está confirmado -- un dato algo más lejos sigue siendo
    representativo ahí."""
    if direcciones_override is not None:
        direcciones = direcciones_override
    else:
        direcciones = await api_client.obtener_direcciones(
            tienda, cercano=cercano, agregador=agregador_nombre, solo_sin_datos=solo_sin_datos
        )
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
        # siempre el texto, tenga número o no.
        texto = direccion["direccion_text"]
        consulta = texto

        # Antes de scrapear de verdad: ¿ya hay un chequeo real reciente de este
        # agregador a <100m de este punto, de CUALQUIER tienda? Los grids de tiendas
        # vecinas se solapan (confirmado: 114 pares de puntos a <150m entre tiendas
        # distintas, algunos literalmente la misma dirección) -- sin esto se scrapea
        # el mismo sitio real varias veces solo porque cada tienda tiene su propia
        # fila para él. buscar_limite_cobertura.py ya hace exactamente esto
        # (buscar_chequeo_cercano); aquí se reutiliza la misma función para que el
        # daemon normal también se beneficie.
        try:
            reuso = await api_client.buscar_chequeo_cercano(
                direccion["lat"], direccion["lng"], agregador_nombre, radio_m=radio_reuso_m
            )
        except Exception as exc:
            reuso = None
            logger.warning("  no se pudo consultar reuso de chequeo cercano: %r", exc)

        if reuso is not None:
            logger.info(
                "  [%s/%s] @ %s reutilizado de '%s' (%s) -- sin scrape real",
                tienda, agregador_nombre, texto, reuso["tienda_origen"],
                "disponible" if reuso["disponible"] else "no_disponible",
            )
            try:
                await api_client.enviar_chequeo(
                    {
                        "tienda": tienda,
                        "agregador": agregador_nombre,
                        "direccion_id": direccion["id"],
                        "disponible": reuso["disponible"],
                    }
                )
            except Exception as exc:
                logger.warning("  no se pudo subir el chequeo reutilizado a KG: %r", exc)
            fallos_consecutivos = 0
            continue  # sin scrape real -> también se salta la pausa anti-bot de este punto

        logger.info("Chequeando %s / %s @ %s", tienda, agregador_nombre, texto)
        resultado = await scraper.verificar_disponibilidad(tienda, consulta)

        # verificar_disponibilidad ya reintentó varias veces internamente (ver
        # scrapers/base.py) antes de darse por vencida -- si SIGUE fallando siempre
        # con "tienda no confirmada", no es un fallo técnico que vaya a arreglarse
        # solo: es una búsqueda válida que no encontró la tienda (misma señal que "no
        # disponible", confirmado a mano por el usuario 09/08 -- ver
        # buscar_limite_cobertura.py, que ya trataba esto así en SU propio flujo).
        # Sin esto, un punto así se queda con error_texto para siempre y
        # _con_datos_reales nunca lo cuenta como "visto" -- cada pasada (cada 10-60
        # min) lo reintenta desde cero sin avanzar nunca.
        if resultado.error_texto and MARCADOR_TIENDA_NO_CONFIRMADA in resultado.error_texto:
            logger.info("  [%s/%s] @ %s: tienda no confirmada de forma persistente -- se acepta como no_disponible real", tienda, agregador_nombre, texto)
            resultado.disponible = False
            resultado.error_texto = None

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
