"""Re-chequeo COMPLETO de todas las direcciones ya existentes (no solo las
sin datos) -- para refrescar el mapa de cobertura antes de una demo/reunión,
cuando lo que importa es que la disponibilidad mostrada sea reciente, no
descubrir puntos nuevos (ver scheduler.py, que desde el 10/08 solo cubre
sin_datos). Corre indefinidamente hasta Ctrl+C o hasta terminar una vuelta
completa de las 6 tiendas x 3 agregadores.

Uso:
    venv/Scripts/python refrescar_todo.py
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
logger = logging.getLogger("refrescar_todo")


async def _chequear_agregador_aislado(tienda: str, agregador_nombre: str) -> bool:
    try:
        await chequear_tienda(
            tienda, agregador_nombre,
            cercano=False, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG,
            solo_sin_datos=False,  # re-chequea TODO, no solo lo que falta
            # permitir_reuso=False: nunca reutiliza un chequeo cercano ya
            # existente, siempre scrapea de verdad -- si no, "refrescar antes
            # de una demo" podría acabar copiando un chequeo de hasta 24h y
            # mostrarlo como recién comprobado (mismo motivo que
            # revalidar_completo.py).
            permitir_reuso=False,
        )
        return True
    except Exception as exc:
        logger.error("Fallo re-chequeando %s / %s: %r", tienda, agregador_nombre, exc)
        await api_client.registrar_alerta(
            tipo="scraper_error",
            mensaje=f"{agregador_nombre}: excepción no controlada (refresco completo) — {exc!r}",
            tienda=tienda,
        )
        return False


async def main(agregadores: list[str]):
    if not config.KG_API_KEY:
        logger.warning("KG_API_KEY no configurada (.env) -- la API de KG rechazará todo.")

    logger.info(
        "Refresco COMPLETO iniciado contra %s -- las 6 tiendas x %s, re-chequeando "
        "TODO lo ya existente (no solo huecos). Puede tardar bastante, ~4s de pausa por chequeo.",
        config.KG_API_BASE_URL, agregadores,
    )

    total_planeado = None
    try:
        sesion_id = await api_client.iniciar_sesion("completo", total_planeado)
    except Exception as exc:
        logger.error("No se pudo iniciar sesión en la API de KG: %s", exc)
        return

    exitosos = fallidos = 0
    estado_final = "completado"
    try:
        for tienda in config.TIENDAS_SCHEDULER:
            logger.info("=== Tienda: %s ===", tienda)
            await api_client.actualizar_tienda_actual(sesion_id, tienda)
            resultados = await asyncio.gather(
                *(_chequear_agregador_aislado(tienda, agregador_nombre) for agregador_nombre in agregadores)
            )
            exitosos += sum(1 for r in resultados if r)
            fallidos += sum(1 for r in resultados if not r)
            logger.info("Tienda %s terminada (%d ok, %d fallidos hasta ahora).", tienda, exitosos, fallidos)
    except (KeyboardInterrupt, asyncio.CancelledError):
        estado_final = "cancelado"
        logger.info("Refresco interrumpido por el usuario.")
    except Exception as exc:
        estado_final = "error"
        logger.error("Refresco completo fallido: %s", exc)

    try:
        await api_client.cerrar_sesion(sesion_id, estado_final, exitosos, fallidos)
    except Exception as exc:
        logger.error("No se pudo cerrar sesión en la API de KG: %s", exc)

    logger.info("Refresco completo terminado (%s): %d ok, %d fallidos.", estado_final, exitosos, fallidos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agregadores", type=str, default=None,
        help="Lista separada por comas (ej. justeat,glovo) -- por defecto los 3 de config.AGREGADORES.",
    )
    args = parser.parse_args()
    agregadores = args.agregadores.split(",") if args.agregadores else config.AGREGADORES
    asyncio.run(main(agregadores))
