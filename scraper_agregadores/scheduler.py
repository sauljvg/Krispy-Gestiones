"""Scheduler APScheduler: descubrimiento de borde, dos velocidades.

Cambio de estrategia (10/08): con cientos de puntos ya confirmados por tienda
(el "límite" real añadido por buscar_limite_cobertura.py + los manuales), un
recorrido completo re-chequeando TODO lo ya conocido en cada pasada se había
vuelto enorme y dominaba el tiempo -- miles de chequeos redundantes cada 10-60
min, cuando lo que de verdad hace falta ahora es seguir empujando el
descubrimiento del borde. Por eso cada pasada (cercano y completo, dos
cadencias, mismo trabajo) ya SOLO cubre los puntos SIN DATOS de las 6 tiendas
(crucen tienda o no) -- nunca re-chequea un punto que ya tiene un resultado
real de ese agregador. Volver a vigilar puntos ya confirmados (para detectar
un bloqueo nuevo en una zona ya mapeada) es una necesidad de OTRA fase, una
vez el borde esté confirmado -- no de esta.

Los agregadores de una misma pasada corren en paralelo (sitios distintos, sin
rate-limit cruzado); dentro de cada agregador las direcciones van secuenciales con pausa.
Cada llamada a la API (POST /chequeo, etc.) usa su propia sesión HTTP — no hay estado
compartido entre tareas paralelas, así que aquí no hay nada equivalente a los líos de
concurrencia de SQLite que tuvimos cuando esto escribía a una DB local.

Reparto entre varios procesos (worker_index/worker_count, ver daemon.py --worker-index):
pensado para cuando el ordenador personal (OP) se enciende como "boost" en paralelo al
portátil de trabajo (OT), que corre 24/7 con un solo worker. El trabajo se reparte por
par (tienda, agregador) -- ver _pares_asignados -- no por tienda entera, para poder usar
cualquier cantidad de workers razonable (no solo divisores de 6). Con worker_count=1
(el caso normal, valor por defecto) el reparto es el conjunto completo de pares: mismo
comportamiento que antes de que existiera esto.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
import reenviar_cola
from main import chequear_tienda
from utils import api_client

logger = logging.getLogger("scheduler")

_worker_index = 0
_worker_count = 1


def _pares_asignados() -> list[tuple[str, str]]:
    """(tienda, agregador) que le tocan a ESTE worker -- reparto por índice módulo
    worker_count sobre la lista aplanada de todos los pares, para que dos workers nunca
    se pisen y cualquier N reparta el trabajo razonablemente parejo.

    Orden AGREGADOR-major (todas las tiendas de justeat, luego todas las de glovo,
    luego todas las de ubereats), no tienda-major -- pedido explícito del usuario
    26/08: al repartir por índice módulo N, esto agrupa el trabajo real pendiente de
    un mismo agregador en workers consecutivos en vez de desperdigarlo, así que un
    agregador con mucho por revalidar (p.ej. Uber Eats tras un bloqueo) tiende a
    acaparar varios workers en vez de competir por turno con tiendas que ya están
    completas en otro agregador."""
    todos = [(tienda, agregador) for agregador in config.AGREGADORES for tienda in config.TIENDAS_SCHEDULER]
    return [par for i, par in enumerate(todos) if i % _worker_count == _worker_index]


def _agregadores_por_tienda() -> dict[str, list[str]]:
    agrupado: dict[str, list[str]] = defaultdict(list)
    for tienda, agregador in _pares_asignados():
        agrupado[tienda].append(agregador)
    return agrupado


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
    """Cuenta cuántos chequeos individuales (tienda x agregador x dirección
    SIN DATOS de ese agregador) va a hacer la pasada -- el mismo conjunto que
    _chequeo recorre de verdad, ahora que ya no hay fase de recorrido
    completo. El "sin datos" es distinto por agregador (cada uno tiene su
    propio hueco de cobertura, ver _con_datos_reales en backend), así que no
    vale un solo conteo por tienda como antes -- hace falta uno por
    (tienda, agregador), y solo de los pares que le tocan a ESTE worker (ver
    _pares_asignados). Sigue siendo barato: son las mismas llamadas que ya
    hace chequear_tienda, solo que aquí únicamente se cuenta la longitud. Si
    falla, se sigue sin total (el dashboard mostrará "en curso" sin X/Y en
    vez de romper la pasada por esto)."""
    total = 0
    try:
        for tienda, agregador_nombre in _pares_asignados():
            direcciones = await api_client.obtener_direcciones(
                tienda, cercano=cercano, agregador=agregador_nombre, solo_sin_datos=True
            )
            total += len(direcciones)
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
        # Cubrir los puntos SIN DATOS de cualquier tienda, cruzando las 6 --
        # antes esto solo se priorizaba dentro de cada tienda (los huecos de
        # la última tienda del recorrido podían tardar pasadas enteras en
        # cubrirse si las anteriores iban bien). Ya NO hay recorrido completo
        # después (ver docstring del módulo): un punto que ya tiene dato real
        # de este agregador no se vuelve a tocar aquí. Cada worker solo
        # recorre las tiendas para las que tiene al menos un agregador
        # asignado (ver _agregadores_por_tienda) -- con worker_count=1 esto
        # son las 6 tiendas y los 3 agregadores de siempre.
        for tienda, agregadores_asignados in _agregadores_por_tienda().items():
            await api_client.actualizar_tienda_actual(sesion_id, tienda)
            resultados = await asyncio.gather(
                *(
                    _chequear_agregador_aislado(tienda, agregador_nombre, cercano, solo_sin_datos=True)
                    for agregador_nombre in agregadores_asignados
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


async def reintentar_cola_local():
    """Si el backend estuvo caído/rechazando peticiones durante algún
    chequeo, el dato real ya scrapeado queda guardado en disco (ver
    utils/cola_local.py) hasta que alguien ejecute reenviar_cola.py A MANO --
    sin este job, esos chequeos reales podían quedarse varados para siempre
    si nadie se acordaba. reenviar_cola.main() ya es seguro de llamar aunque
    la cola esté vacía (no hace nada) o el backend siga caído (cada archivo
    se deja para el siguiente intento, no se pierde nada)."""
    try:
        await reenviar_cola.main()
    except Exception as exc:
        logger.warning("Fallo reintentando la cola local de chequeos pendientes: %r", exc)


def crear_scheduler(worker_index: int = 0, worker_count: int = 1) -> AsyncIOScheduler:
    global _worker_index, _worker_count
    _worker_index = worker_index
    _worker_count = worker_count

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
    # No depende de horario de apertura (a diferencia de los dos chequeos de
    # arriba) -- si el backend estuvo caído de madrugada, mejor reenviar la
    # cola en cuanto se pueda que esperar a que abra la primera tienda.
    scheduler.add_job(
        reintentar_cola_local,
        trigger=IntervalTrigger(minutes=15),
        id="reintentar-cola-local",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler
