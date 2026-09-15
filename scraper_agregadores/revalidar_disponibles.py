"""Revalidación diaria de "solo verdes": re-chequea únicamente los puntos cuyo último
resultado real fue disponible, para detectar cuándo una zona que estaba libre deja de
estarlo (pedido explícito del usuario 15/09). A diferencia de refrescar_todo.py (que
re-chequea TODO, verde y rojo -- pensado para la vuelta semanal completa de los
sábados), esto se salta los puntos sin datos y los ya confirmados como no_disponible:
esos siguen siendo trabajo de chequeo_cercano/completo (descubrimiento de borde) y de
la vuelta semanal, no de esta pasada diaria.

Mismo patrón que refrescar_todo.py: un agregador detrás de otro, registrado como su
propia "ronda" (ver api_client.iniciar_ronda/finalizar_ronda) para que el progreso se
vea en vivo en el Dashboard del scraper. Un único worker -- pensado para correr dentro
del daemon (ver scheduler.py) o lanzarse a mano.

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


async def _chequear_agregador_aislado(tienda: str, agregador_nombre: str, ventana_slot: int | None = None) -> bool:
    try:
        await chequear_tienda(
            tienda, agregador_nombre,
            cercano=False, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG,
            solo_sin_datos=False,
            solo_disponibles=True,  # solo los puntos cuyo último dato real fue disponible
            # permitir_reuso=False: mismo motivo que refrescar_todo.py/revalidar_completo.py
            # -- si no, podría reportar como "recién comprobado" un dato de hasta 24h.
            permitir_reuso=False,
            ventana_slot=ventana_slot,
        )
        return True
    except Exception as exc:
        logger.error("Fallo revalidando disponible %s / %s: %r", tienda, agregador_nombre, exc)
        await api_client.registrar_alerta(
            tipo="scraper_error",
            mensaje=f"{agregador_nombre}: excepción no controlada (revalidación de disponibles) — {exc!r}",
            tienda=tienda,
        )
        return False


async def _total_puntos_disponibles(agregador: str) -> int:
    """Cuenta las direcciones DISPONIBLES (ver solo_disponibles) de las 6
    tiendas para este agregador -- para que total_objetivo case con
    "hechos" (direcciones distintas chequeadas, ver
    agregadores.py::get_ronda_actual). Mismo bug que refrescar_todo.py
    (confirmado en vivo 15/09, pasar len(TIENDAS_SCHEDULER) ahí mostraba un
    progreso sin relación con el real) -- corregido aquí desde el principio."""
    total = 0
    for tienda in config.TIENDAS_SCHEDULER:
        direcciones = await api_client.obtener_direcciones(
            tienda, cercano=False, agregador=agregador, solo_disponibles=True
        )
        total += len(direcciones)
    return total


async def _revalidar_agregador(agregador: str) -> tuple[int, int]:
    """Re-chequea las 6 tiendas para UN agregador, registrado como su propia
    ronda para que el Dashboard del scraper muestre progreso en vivo.

    Tiendas en paralelo (hasta config.MAX_TIENDAS_PARALELO a la vez), igual
    que el daemon normal y que refrescar_todo.py -- ver ahí el mismo
    comentario (confirmado en vivo 15/09 que la versión secuencial no
    coincidía con la estimación de tiempos dada al usuario)."""
    try:
        total_objetivo = await _total_puntos_disponibles(agregador)
        await api_client.iniciar_ronda(agregador, total_objetivo, 1)
    except Exception as exc:
        logger.warning("No se pudo avisar del inicio de ronda para %s (sigue igual): %r", agregador, exc)

    semaforo_tiendas = asyncio.Semaphore(config.MAX_TIENDAS_PARALELO)
    slot_ubereats_counter = {"n": 0}

    async def _tienda(tienda: str) -> bool:
        async with semaforo_tiendas:
            logger.info("=== [%s] Tienda: %s ===", agregador, tienda)
            slot = None
            if agregador == "ubereats":
                slot = slot_ubereats_counter["n"]
                slot_ubereats_counter["n"] += 1
            return await _chequear_agregador_aislado(tienda, agregador, ventana_slot=slot)

    resultados = await asyncio.gather(*(_tienda(tienda) for tienda in config.TIENDAS_SCHEDULER))
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
