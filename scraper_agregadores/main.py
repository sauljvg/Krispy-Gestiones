"""Entry point: ejecuta un chequeo (una tienda x direcciones x un agregador) y lo envía a
la API en vivo de KG. Sin DB local — ver utils/api_client.py."""
import asyncio
import logging

import config
from scrapers.base import MARCADOR_TIENDA_NO_CONFIRMADA
from scrapers.glovo import GlovoScraper
from scrapers.justeat import JustEatScraper
from scrapers.ubereats import UberEatsScraper
from utils import api_client, cola_local

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
    permitir_reuso: bool = True,
    buffer_subida: list | None = None,
) -> list[dict]:
    """direcciones_override: si se pasa, se usa esta lista tal cual en vez de pedirle
    una nueva a la API (cercano/solo_sin_datos se ignoran en ese caso) -- para pasadas
    puntuales que ya eligieron ellas mismas qué direcciones tocan (ver
    revalidar_ubereats_sin_poligono.py, que reparte direcciones individuales entre
    varios workers en vez de tiendas enteras).

    radio_reuso_m: radio para reutilizar un chequeo cercano en vez de scrapear (100m
    por defecto). Más amplio (p.ej. 400m) tiene sentido dentro de una zona cuyo
    polígono de cobertura ya está confirmado -- un dato algo más lejos sigue siendo
    representativo ahí.

    permitir_reuso: False fuerza un scrape real siempre, sin ni siquiera consultar
    buscar_chequeo_cercano. radio_reuso_m=0 NO basta para esto -- si el propio punto
    ya tiene un chequeo previo, se encuentra a sí mismo a 0m de distancia y "reutiliza"
    su propio dato viejo igualmente (confirmado en vivo 26/08 con
    revalidar_completo.py). Necesario para una prueba de carga real.

    buffer_subida: si se pasa una lista (normalmente vacía al principio), los
    chequeos NO se suben uno a uno -- se acumulan ahí (ver flush_buffer_subida) para
    que el CALLER decida cuándo subirlos juntos en un solo lote. Pedido explícito
    del usuario 27/08: con 20+ workers subiendo de uno en uno, cada punto disparaba
    su propio commit en SQLite y la escritura se convirtió en el cuello de botella
    real bajo carga (p50 de latencia >10s con CPU/memoria normales -- no era falta
    de recursos). Por defecto (None) el comportamiento es EXACTAMENTE el de
    siempre (sube cada punto al momento) -- esto es opt-in, no afecta al daemon
    normal (scheduler.py) ni a ningún otro uso existente de esta función.

    Devuelve una lista con un dict por dirección procesada:
    {"direccion_id", "error_tecnico"} -- error_tecnico=True solo cuando el SCRAPER
    en sí falló de verdad (bloqueo/timeout tras agotar sus reintentos internos, ver
    scrapers/base.py), no cuando el punto reutilizó un chequeo cercano ni cuando el
    dato se scrapeó bien pero falló la SUBIDA a KG (eso se encola aparte, ver
    utils/cola_local.py -- no es un problema del scraper, no tiene sentido volver a
    scrapear por eso). Pensado para que revalidar_completo.py pueda reintentar en
    una segunda pasada SOLO los fallos técnicos de verdad (pedido explícito del
    usuario 27/08)."""
    resultados_por_punto: list[dict] = []
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
        reuso = None
        if permitir_reuso:
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
            datos_reuso = {
                "tienda": tienda,
                "agregador": agregador_nombre,
                "direccion_id": direccion["id"],
                "disponible": reuso["disponible"],
            }
            if buffer_subida is not None:
                buffer_subida.append(
                    {"datos": datos_reuso, "url_captura": None, "agregador": agregador_nombre, "texto": texto}
                )
            else:
                try:
                    await api_client.enviar_chequeo(datos_reuso)
                except Exception as exc:
                    logger.warning("  no se pudo subir el chequeo reutilizado a KG (%r) -- encolado en local", exc)
                    cola_local.encolar(datos_reuso)
            fallos_consecutivos = 0
            resultados_por_punto.append({"direccion_id": direccion["id"], "error_tecnico": False})
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

        datos_chequeo = {
            "tienda": tienda,
            "agregador": agregador_nombre,
            "direccion_id": direccion["id"],
            "disponible": resultado.disponible,
            "tiempo_entrega_min": resultado.tiempo_entrega_min,
            "mensaje_bloqueo": resultado.mensaje_bloqueo,
            "error_texto": resultado.error_texto,
        }
        if buffer_subida is not None:
            # No se sube nada aquí -- se acumula y el CALLER lo sube en lote (ver
            # flush_buffer_subida). Los fallos de subida y las capturas también se
            # gestionan ahí, en el momento del flush -- no tiene sentido duplicar
            # esa lógica aquí.
            buffer_subida.append(
                {
                    "datos": datos_chequeo,
                    "url_captura": resultado.url_captura,
                    "agregador": agregador_nombre,
                    "texto": texto,
                }
            )
        else:
            try:
                respuesta = await api_client.enviar_chequeo(datos_chequeo)
            except Exception as exc:
                # El dato YA es real (el scrape en sí funcionó) -- si esto falla es el
                # BACKEND el que está caído/rechazando (confirmado en vivo 27/08: disk
                # I/O error de SQLite bajo carga tumbaba la web entera durante ratos
                # largos). Antes esto se perdía del todo si los 3 reintentos extra de
                # revalidar_completo.py al FINAL de la pasada coincidían con el
                # servidor aún caído -- ahora se encola en local y se reenvía después
                # (ver reenviar_cola.py) sin volver a scrapear nada.
                logger.error(
                    "  [%s/%s] @ %s: no se pudo subir a KG (%r) -- encolado en local, se reenviará solo",
                    tienda, agregador_nombre, texto, exc,
                )
                cola_local.encolar(datos_chequeo, resultado.url_captura)
                fallos_consecutivos = 0
                # error_tecnico=False: el scraper SÍ funcionó, el dato es real -- lo
                # único que falló fue subirlo, y ya queda encolado para reenviarse solo.
                # No tiene sentido volver a scrapear esto en una segunda pasada.
                resultados_por_punto.append({"direccion_id": direccion["id"], "error_tecnico": False})
                if delay_seg and i < len(direcciones) - 1:
                    await asyncio.sleep(delay_seg)
                continue

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
                try:
                    await api_client.subir_captura(respuesta["chequeo_id"], resultado.url_captura)
                except Exception as exc:
                    # El chequeo principal ya se subió bien (arriba) -- perder solo la
                    # captura no debe tumbar el punto entero ni perder el dato real.
                    logger.warning("  captura no subida (dato principal sí subió): %r", exc)

        logger.info("  -> disponible=%s tiempo=%s min", resultado.disponible, resultado.tiempo_entrega_min)

        # error_tecnico=True solo si resultado.error_texto sigue puesto AQUÍ -- ya
        # pasó por la corrección de "tienda no confirmada persistente" de arriba
        # (esa se limpia a None porque es un no_disponible real, no un fallo). Lo
        # que quede es un bloqueo/timeout de verdad del scraper (ver
        # scrapers/base.py: fallo definitivo verificando).
        resultados_por_punto.append(
            {"direccion_id": direccion["id"], "error_tecnico": bool(resultado.error_texto)}
        )

        if resultado.error_texto:
            fallos_consecutivos += 1
        else:
            fallos_consecutivos = 0

        if delay_seg and i < len(direcciones) - 1:
            await asyncio.sleep(delay_seg)

    return resultados_por_punto


async def flush_buffer_subida(buffer_subida: list) -> None:
    """Sube en UN solo lote (ver api_client.enviar_chequeos_batch) todo lo
    acumulado por chequear_tienda(..., buffer_subida=...), y vacía la lista in-place.
    Pensado para llamarse periódicamente (cada N puntos, ver revalidar_completo.py)
    -- no ocurre solo dentro de chequear_tienda, así el caller decide el ritmo."""
    if not buffer_subida:
        return

    items = [b["datos"] for b in buffer_subida]
    try:
        resultados = await api_client.enviar_chequeos_batch(items)
    except Exception as exc:
        # Mismo tratamiento que un fallo de subida individual -- el dato ya es
        # real, se encola en local para reenviarse después sin volver a scrapear.
        logger.error("Fallo subiendo lote de %d chequeo(s) (%r) -- encolados en local", len(buffer_subida), exc)
        for b in buffer_subida:
            cola_local.encolar(b["datos"], b["url_captura"])
        buffer_subida.clear()
        return

    for b, resultado in zip(buffer_subida, resultados):
        if b["url_captura"]:
            if resultado.get("transicion"):
                logger.warning(
                    "%s: %s dejó de estar disponible (era disponible en el chequeo anterior) -- subiendo captura",
                    b["agregador"], b["texto"],
                )
            try:
                await api_client.subir_captura(resultado["chequeo_id"], b["url_captura"])
            except Exception as exc:
                logger.warning("  captura no subida (dato principal sí subió): %r", exc)

    buffer_subida.clear()


async def main():
    # Chequeo manual de validación: solo 1 dirección (la propia tienda) por agregador.
    for tienda in config.TIENDAS_SCHEDULER:
        for agregador_nombre in SCRAPERS:
            await chequear_tienda(tienda, agregador_nombre, cercano=True, max_direcciones=1)


if __name__ == "__main__":
    asyncio.run(main())
