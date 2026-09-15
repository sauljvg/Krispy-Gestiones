"""Re-chequeo COMPLETO de todas las direcciones ya existentes (no solo las
sin datos) -- para refrescar el mapa de cobertura antes de una demo/reunión,
cuando lo que importa es que la disponibilidad mostrada sea reciente, no
descubrir puntos nuevos (ver scheduler.py, que desde el 10/08 solo cubre
sin_datos). Corre hasta terminar una vuelta completa de las 6 tiendas x 3
agregadores (o hasta Ctrl+C).

Un agregador detrás de otro (no en paralelo entre sí) -- para poder
registrar cada agregador como una "ronda" propia (ver
api_client.iniciar_ronda/finalizar_ronda, el mismo mecanismo que usa
revalidar_completo.py) y que el progreso se vea en vivo en el "Dashboard
del scraper" de agregadores.html, en vez de solo en este log de consola.

DENTRO de cada agregador, las direcciones SÍ se reparten en paralelo entre
varias tareas asyncio (hasta config.MAX_WORKERS_POR_AGREGADOR a la vez,
distinto por agregador -- ver config.py) -- mismo reparto por dirección
que revalidar_completo.py (--worker-count), pero como tareas dentro de un
único proceso en vez de procesos separados (pedido explícito del usuario
15/09, antes esto era estrictamente secuencial).

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


async def _puntos_todos(agregador: str) -> list[dict]:
    """Todas las direcciones activas reales de las 6 tiendas para este
    agregador, cada una anotada con su tienda -- mismo cálculo que
    revalidar_completo.py::_puntos_todos. El total (len de esto) es lo que
    se pasa como total_objetivo de la ronda para que case con "hechos" (que
    el backend cuenta como direcciones DISTINTAS chequeadas, ver
    agregadores.py::get_ronda_actual) -- pasar len(TIENDAS_SCHEDULER) ahí
    (bug confirmado en vivo 15/09: mostraba "81/10" a mitad de una pasada
    real) hacía que el progreso mostrado no tuviera ninguna relación con el
    real."""
    puntos = []
    for tienda in config.TIENDAS_SCHEDULER:
        direcciones = await api_client.obtener_direcciones(tienda, cercano=False, agregador=agregador)
        for d in direcciones:
            d["tienda"] = tienda
            puntos.append(d)
    return puntos


async def _chequear_punto_aislado(punto: dict, agregador_nombre: str, ventana_slot: int | None = None) -> bool:
    """Chequea UNA dirección suelta (no una tienda entera) -- cada llamada
    crea su propio scraper con su propia sesión de navegador (ver
    main.py::chequear_tienda, scraper=None por defecto), así que es seguro
    lanzar varias de estas a la vez con asyncio.gather sin que se pisen
    entre sí (a diferencia de compartir un único scraper entre tareas
    paralelas)."""
    tienda = punto["tienda"]
    try:
        await chequear_tienda(
            tienda, agregador_nombre,
            direcciones_override=[punto],
            # permitir_reuso=False: nunca reutiliza un chequeo cercano ya
            # existente, siempre scrapea de verdad -- si no, "refrescar antes
            # de una demo" podría acabar copiando un chequeo de hasta 24h y
            # mostrarlo como recién comprobado (mismo motivo que
            # revalidar_completo.py).
            permitir_reuso=False,
            ventana_slot=ventana_slot,
        )
        return True
    except Exception as exc:
        logger.error("Fallo re-chequeando %s / %s @ %s: %r", tienda, agregador_nombre, punto.get("direccion_text"), exc)
        await api_client.registrar_alerta(
            tipo="scraper_error",
            mensaje=f"{agregador_nombre}: excepción no controlada (refresco completo) — {exc!r}",
            tienda=tienda,
        )
        return False


async def _refrescar_agregador(agregador: str) -> tuple[int, int]:
    """Re-chequea TODAS las direcciones de las 6 tiendas para UN agregador,
    registrado como su propia ronda (worker_count=1) para que el Dashboard
    del scraper muestre progreso en vivo, igual que ya hace
    revalidar_completo.py.

    Direcciones sueltas repartidas entre hasta config.MAX_WORKERS_POR_AGREGADOR
    tareas asyncio en paralelo (ver ahí el porqué de cada número -- Glovo se
    queda en 1/secuencial a propósito, tiene un bloqueo por IP documentado y
    confirmado en vivo a cualquier concurrencia alta, ver ESTADO_PROYECTO.md
    26/08). Mismo reparto por dirección que revalidar_completo.py
    (--worker-count), pero dentro de un único proceso. Cada worker con Uber
    Eats asignado pide un slot de la rejilla compartida (utils/ventana.py)
    para que sus ventanas visibles no se apilen -- Glovo/JustEat son
    headless, no lo necesitan."""
    puntos = await _puntos_todos(agregador)
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

    logger.info("[%s] %d direcciones repartidas entre hasta %d a la vez.", agregador, len(puntos), max_paralelo)
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
        "Refresco COMPLETO iniciado contra %s -- las 6 tiendas x %s, re-chequeando "
        "TODO lo ya existente (no solo huecos), con paralelismo por dirección "
        "(ver config.MAX_WORKERS_POR_AGREGADOR).",
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
