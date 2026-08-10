"""Scheduler APScheduler: dos velocidades de chequeo en horas punta.

No buscamos datos "en vivo" sino un informe de cuándo y dónde nos bloquean:
  - CERCANO (pocos puntos, 1 km): cada 10 min, reacción rápida a un bloqueo total real.
  - COMPLETO (48 puntos): cada 60 min, mapea la zona de cobertura sin machacar los sitios.

Los agregadores de una misma pasada corren en paralelo (sitios distintos, sin
rate-limit cruzado); dentro de cada agregador las direcciones van secuenciales con pausa.
Cada llamada a la API (POST /chequeo, etc.) usa su propia sesión HTTP — no hay estado
compartido entre tareas paralelas, así que aquí no hay nada equivalente a los líos de
concurrencia de SQLite que tuvimos cuando esto escribía a una DB local.

Cada pasada (cercano o completo) va en DOS fases: primero cubre los puntos SIN
DATOS de las 6 tiendas (crucen tienda o no), y solo después arranca el
recorrido completo normal tienda por tienda -- así un hueco se cubre esté
donde esté, sin depender de que le toque pronto por orden.
"""
import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
from main import chequear_tienda
from utils import api_client

logger = logging.getLogger("scheduler")


def es_horario_apertura(ahora: datetime = None) -> bool:
    ahora = ahora or datetime.now()
    return any(rango["inicio"] <= ahora.hour < rango["fin"] for rango in config.HORARIOS_APERTURA)


async def _chequear_agregador_aislado(
    tienda: str, agregador_nombre: str, cercano: bool, solo_sin_datos: bool = False
) -> bool:
    try:
        await chequear_tienda(
            tienda,
            agregador_nombre,
            cercano=cercano,
            delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG,
            solo_sin_datos=solo_sin_datos,
        )
        return True
    except Exception as exc:
        # repr() en vez de str(): algunas excepciones (asyncio.TimeoutError,
        # p.ej.) tienen str() vacío, y sin el nombre de la clase un fallo así
        # queda indistinguible de cualquier otro en el log.
        logger.error("Fallo chequeando %s / %s: %r", tienda, agregador_nombre, exc)
        await api_client.registrar_alerta(
            tipo="scraper_error",
            mensaje=f"{agregador_nombre}: excepción no controlada — {exc!r}",
            tienda=tienda,
        )
        return False


async def _calcular_total_planeado(cercano: bool) -> int | None:
    """Cuenta cuántos chequeos individuales (tienda x agregador x dirección)
    va a hacer la pasada completa (fase 2, la que domina el tiempo total --
    la fase 1 de "solo huecos" normalmente no añade nada una vez la
    cobertura está madura, ver _chequeo). Una llamada de conteo por tienda,
    reusando el mismo endpoint que ya usa chequear_tienda -- nada nuevo del
    lado del backend, solo se suma el tamaño de la lista que devuelve. Si
    falla, se sigue sin total (el dashboard mostrará "en curso" sin X/Y en
    vez de romper la pasada por esto)."""
    total = 0
    try:
        for tienda in config.TIENDAS_SCHEDULER:
            direcciones = await api_client.obtener_direcciones(tienda, cercano=cercano)
            total += len(direcciones) * len(config.AGREGADORES)
    except Exception as exc:
        logger.warning("No se pudo calcular el total planeado de la pasada: %r", exc)
        return None
    return total


async def _chequeo(modo: str, cercano: bool):
    if not config.SCRAPER_ENABLED:
        logger.info("SCRAPER_ENABLED=False — se omite el chequeo (%s).", modo)
        return
    if not es_horario_apertura():
        logger.debug("Fuera de horas punta — se omite el chequeo (%s).", modo)
        return

    total_planeado = await _calcular_total_planeado(cercano)

    try:
        sesion_id = await api_client.iniciar_sesion(modo, total_planeado)
    except Exception as exc:
        logger.error("No se pudo iniciar sesión en la API de KG (%s): %s", modo, exc)
        return

    exitosos = fallidos = 0
    estado_final = "completado"

    try:
        # Fase 1: cubrir primero los puntos SIN DATOS de cualquier tienda,
        # cruzando las 6 -- antes esto solo se priorizaba dentro de cada
        # tienda (los huecos de la última tienda del recorrido podían tardar
        # pasadas enteras en cubrirse si las anteriores iban bien). Ahora un
        # hueco se cubre esté donde esté antes de empezar el recorrido
        # completo normal. Con la cobertura ya completa esta fase no añade
        # apenas nada (0 direcciones por tienda, chequear_tienda no hace nada).
        for tienda in config.TIENDAS_SCHEDULER:
            resultados = await asyncio.gather(
                *(
                    _chequear_agregador_aislado(tienda, agregador_nombre, cercano, solo_sin_datos=True)
                    for agregador_nombre in config.AGREGADORES
                )
            )
            exitosos += sum(1 for r in resultados if r)
            fallidos += sum(1 for r in resultados if not r)

        # Fase 2: recorrido completo normal, tienda por tienda.
        for tienda in config.TIENDAS_SCHEDULER:
            resultados = await asyncio.gather(
                *(
                    _chequear_agregador_aislado(tienda, agregador_nombre, cercano)
                    for agregador_nombre in config.AGREGADORES
                )
            )
            exitosos += sum(1 for r in resultados if r)
            fallidos += sum(1 for r in resultados if not r)
    except Exception as exc:
        estado_final = "error"
        logger.error("Sesión de scraper (%s) fallida: %s", modo, exc)

    try:
        await api_client.cerrar_sesion(sesion_id, estado_final, exitosos, fallidos)
    except Exception as exc:
        logger.error("No se pudo cerrar sesión en la API de KG: %s", exc)

    logger.info("Chequeo %s terminado: %d ok, %d fallidos.", modo, exitosos, fallidos)


async def chequeo_cercano():
    await _chequeo("cercano", cercano=True)


async def chequeo_completo():
    await _chequeo("completo", cercano=False)


def crear_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        chequeo_cercano,
        trigger=IntervalTrigger(minutes=config.FRECUENCIA_CHEQUEO_CERCANO_MIN),
        id="chequeo-cercano",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        chequeo_completo,
        trigger=IntervalTrigger(minutes=config.FRECUENCIA_CHEQUEO_COMPLETO_MIN),
        id="chequeo-completo",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler
