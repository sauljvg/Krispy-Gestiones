"""Revalidación diaria de "solo verdes": re-chequea únicamente los puntos cuyo último
resultado real fue disponible, para detectar cuándo una zona que estaba libre deja de
estarlo (pedido explícito del usuario 15/09). A diferencia de refrescar_todo.py (que
re-chequea TODO, verde y rojo -- pensado para la vuelta semanal completa de los
sábados), esto se salta los puntos sin datos y los ya confirmados como no_disponible:
esos siguen siendo trabajo de chequeo_cercano/completo (descubrimiento de borde) y de
la vuelta semanal, no de esta pasada diaria.

Mismo patrón que refrescar_todo.py: un agregador detrás de otro, registrado como su
propia "ronda" (ver api_client.iniciar_ronda/finalizar_ronda) para que el progreso se
vea en vivo en el Dashboard del scraper. DENTRO de cada agregador, las direcciones se
reparten en paralelo entre varias tareas asyncio (hasta config.MAX_WORKERS_POR_AGREGADOR,
distinto por agregador -- ver config.py). Pensado para correr dentro del daemon (ver
scheduler.py) o lanzarse a mano.

Uso:
    venv/Scripts/python revalidar_disponibles.py
"""
import argparse
import asyncio
import logging

import config
from main import chequear_tienda
from utils import api_client

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("revalidar_disponibles")

MODO_SESION = "revalidar_disponibles"


async def _puntos_disponibles(agregador: str) -> list[dict]:
    """Todas las direcciones DISPONIBLES (ver solo_disponibles) de las 6
    tiendas para este agregador, cada una anotada con su tienda. El total
    (len de esto) es lo que se pasa como total_objetivo de la ronda -- ver
    refrescar_todo.py::_puntos_todos, mismo motivo (bug confirmado en vivo
    15/09, pasar len(TIENDAS_SCHEDULER) mostraba un progreso sin relación
    con el real)."""
    puntos = []
    for tienda in config.TIENDAS_SCHEDULER:
        direcciones = await api_client.obtener_direcciones(
            tienda, cercano=False, agregador=agregador, solo_disponibles=True
        )
        for d in direcciones:
            d["tienda"] = tienda
            puntos.append(d)
    return puntos


async def _chequear_punto_aislado(punto: dict, agregador_nombre: str, ventana_slot: int | None = None) -> bool:
    """Chequea UNA dirección suelta -- ver refrescar_todo.py::_chequear_punto_aislado,
    mismo motivo (cada llamada crea su propio scraper con su propia sesión,
    seguro de lanzar varias a la vez)."""
    tienda = punto["tienda"]
    try:
        await chequear_tienda(
            tienda, agregador_nombre,
            direcciones_override=[punto],
            # permitir_reuso=False: mismo motivo que refrescar_todo.py/revalidar_completo.py
            # -- si no, podría reportar como "recién comprobado" un dato de hasta 24h.
            permitir_reuso=False,
            ventana_slot=ventana_slot,
        )
        return True
    except Exception as exc:
        logger.error("Fallo revalidando disponible %s / %s @ %s: %r", tienda, agregador_nombre, punto.get("direccion_text"), exc)
        await api_client.registrar_alerta(
            tipo="scraper_error",
            mensaje=f"{agregador_nombre}: excepción no controlada (revalidación de disponibles) — {exc!r}",
            tienda=tienda,
        )
        return False


async def _revalidar_agregador(agregador: str) -> tuple[int, int]:
    """Re-chequea las direcciones DISPONIBLES de las 6 tiendas para UN
    agregador, registrado como su propia ronda para que el Dashboard del
    scraper muestre progreso en vivo.

    Direcciones sueltas repartidas entre hasta config.MAX_WORKERS_POR_AGREGADOR
    tareas asyncio en paralelo -- ver refrescar_todo.py, mismo patrón y
    mismo motivo (Glovo secuencial a propósito, bloqueo por IP documentado)."""
    puntos = await _puntos_disponibles(agregador)
    try:
        await api_client.iniciar_ronda(agregador, len(puntos), 1)
    except Exception as exc:
        logger.warning("No se pudo avisar del inicio de ronda para %s (sigue igual): %r", agregador, exc)

    max_paralelo = config.MAX_WORKERS_POR_AGREGADOR.get(agregador, config.MAX_TIENDAS_PARALELO)
    semaforo = asyncio.Semaphore(max_paralelo)
    slot_ubereats_counter = {"n": 0}

    async def _punto(punto: dict) -> bool:
        async with semaforo:
            slot = None
            if agregador == "ubereats":
                slot = slot_ubereats_counter["n"]
                slot_ubereats_counter["n"] += 1
            return await _chequear_punto_aislado(punto, agregador, ventana_slot=slot)

    logger.info("[%s] %d direcciones disponibles repartidas entre hasta %d a la vez.", agregador, len(puntos), max_paralelo)
    resultados = await asyncio.gather(*(_punto(p) for p in puntos))
    exitosos = sum(1 for r in resultados if r)
    fallidos = sum(1 for r in resultados if not r)

    try:
        await api_client.finalizar_ronda(agregador)
    except Exception as exc:
        logger.warning("No se pudo avisar del fin de ronda para %s (sigue igual): %r", agregador, exc)

    return exitosos, fallidos


async def main(agregadores: list[str]):
    if not config.KG_API_KEY:
        logger.warning("KG_API_KEY no configurada (.env) -- la API de KG rechazará todo.")

    logger.info(
        "Revalidación de disponibles iniciada contra %s -- las 6 tiendas x %s, "
        "re-chequeando SOLO los puntos que la última vez salieron disponibles.",
        config.KG_API_BASE_URL, agregadores,
    )

    try:
        sesion_id = await api_client.iniciar_sesion(MODO_SESION, None)
    except Exception as exc:
        logger.error("No se pudo iniciar sesión en la API de KG: %s", exc)
        return

    exitosos = fallidos = 0
    estado_final = "completado"
    try:
        for agregador in agregadores:
            await api_client.actualizar_tienda_actual(sesion_id, f"({agregador})")
            e, f = await _revalidar_agregador(agregador)
            exitosos += e
            fallidos += f
            logger.info("Agregador %s terminado (%d ok, %d fallidos hasta ahora en total).", agregador, exitosos, fallidos)
    except (KeyboardInterrupt, asyncio.CancelledError):
        estado_final = "cancelado"
        logger.info("Revalidación de disponibles interrumpida por el usuario.")
    except Exception as exc:
        estado_final = "error"
        logger.error("Revalidación de disponibles fallida: %s", exc)

    try:
        await api_client.cerrar_sesion(sesion_id, estado_final, exitosos, fallidos)
    except Exception as exc:
        logger.error("No se pudo cerrar sesión en la API de KG: %s", exc)

    logger.info("Revalidación de disponibles terminada (%s): %d ok, %d fallidos.", estado_final, exitosos, fallidos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agregadores", type=str, default=None,
        help="Lista separada por comas (ej. justeat,glovo) -- por defecto los 3 de config.AGREGADORES.",
    )
    args = parser.parse_args()
    agregadores = args.agregadores.split(",") if args.agregadores else config.AGREGADORES
    asyncio.run(main(agregadores))
