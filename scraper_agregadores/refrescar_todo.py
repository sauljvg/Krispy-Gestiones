"""Re-chequeo COMPLETO de todas las direcciones ya existentes (no solo las
sin datos) -- para refrescar el mapa de cobertura antes de una demo/reunión,
cuando lo que importa es que la disponibilidad mostrada sea reciente, no
descubrir puntos nuevos (ver scheduler.py, que desde el 10/08 solo cubre
sin_datos). Corre hasta terminar una vuelta completa de las 6 tiendas x 3
agregadores (o hasta Ctrl+C).

Un agregador detrás de otro (no en paralelo entre sí como antes) -- para
poder registrar cada agregador como una "ronda" propia (ver
api_client.iniciar_ronda/finalizar_ronda, el mismo mecanismo que usa
revalidar_completo.py) y que el progreso se vea en vivo en el "Dashboard
del scraper" de agregadores.html, en vez de solo en este log de consola.
Con un único worker (no reparte direcciones entre varios procesos, a
diferencia de revalidar_completo.py -- este script está pensado para
lanzarse una vez a mano antes de una demo, no como prueba de carga).

Usa su propio modo de sesión ("refresco_manual", ver agregadores_sesiones)
en vez de reutilizar "completo" -- ese es el modo del scheduler automático
24/7 (chequeo_completo en scheduler.py), y compartirlo podía cortar en
falso una pasada real del daemon si coincidían, además de mezclar sus
estadísticas en el panel "Estado" bajo el mismo indicador.

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

MODO_SESION = "refresco_manual"


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


async def _refrescar_agregador(agregador: str) -> tuple[int, int]:
    """Re-chequea las 6 tiendas para UN agregador, registrado como su propia
    ronda (worker_count=1) para que el Dashboard del scraper muestre
    progreso en vivo de esta pasada, igual que ya hace revalidar_completo.py."""
    try:
        await api_client.iniciar_ronda(agregador, len(config.TIENDAS_SCHEDULER), 1)
    except Exception as exc:
        logger.warning("No se pudo avisar del inicio de ronda para %s (sigue igual): %r", agregador, exc)

    exitosos = fallidos = 0
    for tienda in config.TIENDAS_SCHEDULER:
        logger.info("=== [%s] Tienda: %s ===", agregador, tienda)
        ok = await _chequear_agregador_aislado(tienda, agregador)
        exitosos += 1 if ok else 0
        fallidos += 0 if ok else 1

    try:
        await api_client.finalizar_ronda(agregador)
    except Exception as exc:
        logger.warning("No se pudo avisar del fin de ronda para %s (sigue igual): %r", agregador, exc)

    return exitosos, fallidos


async def main(agregadores: list[str]):
    if not config.KG_API_KEY:
        logger.warning("KG_API_KEY no configurada (.env) -- la API de KG rechazará todo.")

    logger.info(
        "Refresco COMPLETO iniciado contra %s -- las 6 tiendas x %s, re-chequeando "
        "TODO lo ya existente (no solo huecos). Puede tardar bastante, ~4s de pausa por chequeo.",
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
            e, f = await _refrescar_agregador(agregador)
            exitosos += e
            fallidos += f
            logger.info("Agregador %s terminado (%d ok, %d fallidos hasta ahora en total).", agregador, exitosos, fallidos)
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
