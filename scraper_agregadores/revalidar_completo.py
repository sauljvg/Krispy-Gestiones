"""Vuelta completa REAL: re-verifica cada punto activo de un agregador, tenga o no
dato ya confirmado -- a diferencia del daemon normal (que nunca retoca un punto con
dato real, ver scheduler.py) y de revalidar_ubereats_sin_poligono.py (que solo tocaba
los nunca comprobados). Sin reutilizar chequeos cercanos (radio_reuso_m=0): cada punto
se scrapea de verdad, para que la prueba de carga sea real, no una copia de datos ya
conocidos.

Pensado como prueba puntual de escalado (20+ workers por agregador, varios procesos a
la vez), no para correr en bucle sin más -- ver "cada cuánto una vuelta completa" en
ESTADO_PROYECTO.md 26/08.

Reparte DIRECCIONES INDIVIDUALES entre los workers (no tiendas enteras -- con solo 6
tiendas, cualquier worker por encima de 6 se quedaría sin nada que hacer).

Reanudable (27/08, pedido explícito del usuario): si el proceso se corta a mitad
(servidor caído, matado a mano, etc.) y se relanza con el MISMO agregador antes de
cerrar la ronda a la fuerza, cada worker se salta los puntos que esta ronda ya cubrió
-- ver api_client.ronda_hechos_ids. Importante: si quieres reanudar, NO llames a
POST /admin/rondas/finalizar?forzar=true antes de relanzar -- eso abandona la ronda
del todo (el próximo relanzamiento empezaría una ronda nueva desde cero).

Los fallos TÉCNICOS de scraper (bloqueo/timeout tras agotar los 3 reintentos internos
de cada punto, ver scrapers/base.py) se reintentan una SEGUNDA pasada completa (3
intentos más) al final, después de que el worker termine con el resto de su lista --
también pedido explícito del usuario 27/08, para ver si un bloqueo puntual de Glovo se
resuelve solo dándole más tiempo. Distinto de `fallidos` (fallos de CONEXIÓN a nuestro
propio backend, ya poco frecuentes desde que existe la cola local -- ver
utils/cola_local.py): ese dato ya es real, no hace falta volver a scrapearlo.

Subida por LOTES, no punto a punto (27/08, pedido explícito del usuario tras
confirmar en vivo que subir de uno en uno con 20+ workers a la vez saturaba la
escritura de SQLite -- p50 de latencia de la web subió a >10s con CPU/memoria
normales, no era falta de recursos, era la cola de commits). Cada TAMANO_LOTE
puntos se suben juntos en un solo POST/commit (ver main.py::flush_buffer_subida).
Efecto secundario esperado: el progreso "hechos" del dashboard avanza a saltos de
TAMANO_LOTE en vez de de uno en uno -- aceptable, ya no es tiempo real estricto a
cambio de no tumbar la web con la carga de escritura.

Uso (un agregador por tanda, varios procesos):
    venv/Scripts/python revalidar_completo.py --agregador ubereats --worker-index 0 --worker-count 20
"""
import argparse
import asyncio
import logging
import time

import config
from main import SCRAPERS, chequear_tienda, flush_buffer_subida
from utils import api_client
from utils.ventana import calcular_posicion_ventana

logging.basicConfig(level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("revalidar_completo")

# Cuántos chequeos se acumulan antes de subirlos juntos en un solo lote (ver
# docstring del módulo). Subido de 5 a 10 el 27/08 (pedido explícito del
# usuario, para bajar aún más la carga de escritura sobre Railway) -- no se
# sube más porque el cuello de botella real de hoy resultó ser el bloqueo del
# event loop por las capturas a Drive (ya arreglado, ver run_in_threadpool en
# agregadores_routes.py), no tanto los commits de SQLite en sí; subir más el
# lote ya no baja mucho más esa carga, pero sí aumenta linealmente cuánto
# trabajo hay que repetir si un worker se corta a mitad de lote (con 10, como
# mucho se re-scrapean 10 puntos por worker al reanudar, ver ronda_hechos_ids).
TAMANO_LOTE = 10

# El lote es POR WORKER (cada proceso tiene su propio buffer_subida en memoria --
# no hay forma barata de compartirlo entre procesos de Windows separados sin memoria
# compartida/IPC, complejidad que no compensa aquí). Con pocos workers eso no se
# nota (cada uno acumula 10 rápido), pero con muchos workers y una tasa de fallo
# alta (confirmado en vivo 27/08 con Glovo a 10 workers: ninguno individualmente
# llegaba a 10 aciertos en varios minutos) el progreso se ve "congelado" en el
# dashboard aunque el scraping siga avanzando de verdad. FLUSH_INTERVALO_SEG pone
# un tope de tiempo además del tope de cantidad -- sube lo que lleve un worker
# (aunque sean 3, o 1) si ya pasó este tiempo desde su último envío, así el
# dashboard nunca se queda más de esto sin novedades por worker (pedido explícito
# del usuario 27/08).
FLUSH_INTERVALO_SEG = 60


def _debe_flush(buffer_subida: list, ultimo_flush: float) -> bool:
    if not buffer_subida:
        return False
    return len(buffer_subida) >= TAMANO_LOTE or (time.monotonic() - ultimo_flush) >= FLUSH_INTERVALO_SEG


async def _puntos_todos(agregador: str) -> list[dict]:
    puntos = []
    for tienda in config.TIENDAS_SCHEDULER:
        direcciones = await api_client.obtener_direcciones(tienda, cercano=False, agregador=agregador)
        for d in direcciones:
            d["tienda"] = tienda
            puntos.append(d)
    puntos.sort(key=lambda d: d["id"])
    return puntos


async def main(
    agregador: str, worker_index: int, worker_count: int,
    permitir_imagenes: bool = False, visible: bool = False, proxy_index: int | None = None,
):
    if permitir_imagenes:
        # Prueba puntual 26/08: comprobar si bloquear imágenes/media es lo que
        # dispara la página de error genérica de Glovo bajo carga ("Oh, no! It
        # looks like there's a problem") -- hipótesis del usuario, sin confirmar.
        # Solo para este proceso (atributo de CLASE, pero cada worker es su propio
        # proceso Python aparte, así que no se pisa entre workers).
        SCRAPERS[agregador].bloquear_recursos = False
        logger.info("Worker %d/%d (%s): imágenes/media SIN bloquear (prueba puntual)", worker_index, worker_count, agregador)

    if proxy_index is not None:
        # Experimento 27/08 (rotación de IP gratis, ver config.PROXIES): este
        # worker en concreto sale por un proxy en vez de la IP propia -- pensado
        # para dejar unos workers con proxy y otros sin él en la MISMA vuelta, y
        # comparar la tasa de bloqueo entre ambos grupos.
        if proxy_index >= len(config.PROXIES):
            logger.error(
                "Worker %d/%d (%s): --proxy-index %d fuera de rango (solo hay %d proxies en SCRAPER_PROXIES) -- sigue sin proxy",
                worker_index, worker_count, agregador, proxy_index, len(config.PROXIES),
            )
        else:
            SCRAPERS[agregador].proxy = config.PROXIES[proxy_index]
            logger.info("Worker %d/%d (%s): usando proxy #%d (%s)", worker_index, worker_count, agregador, proxy_index, config.PROXIES[proxy_index]["server"])

    if visible:
        # Prueba puntual 26/08: correr Glovo con ventana genuinamente visible, igual
        # que Uber Eats (que SÍ la necesita por Cloudflare) -- por si el bloqueo/
        # limitación de Glovo bajo carga también está fijándose en la señal de
        # "headless" (navigator.webdriver, fingerprint de Chromium sin cabeza, etc.),
        # no solo en volumen de peticiones. mantener_visible=True es necesario
        # además de iniciar_headless=False -- confirmado en vivo 08/08 con Uber Eats
        # que "no headless" con ventana fuera de pantalla seguía detectándose casi
        # siempre (ver comentario en scrapers/base.py).
        SCRAPERS[agregador].iniciar_headless = False
        SCRAPERS[agregador].mantener_visible = True
        logger.info("Worker %d/%d (%s): ventana visible (prueba puntual, como Uber Eats)", worker_index, worker_count, agregador)

    if worker_count > 1:
        # Escalonar el arranque: sin esto, N workers lanzados a la vez disparan N
        # peticiones GET casi simultáneas en _puntos_todos() -- confirmado en vivo
        # 26/08 que una ráfaga de ~360 peticiones (60 workers x 6 tiendas) tumbó la
        # única réplica de Railway con 502 en cadena. 0.5s de separación por worker
        # reparte esa ráfaga en el tiempo sin alargar la pasada de forma notable.
        await asyncio.sleep(worker_index * 0.5)

    if (agregador == "ubereats" or visible) and worker_count > 1:
        # Rejilla de ventanas visibles (módulo 8, ver utils/ventana.py) -- de normal
        # solo importa para Uber Eats (JustEat/Glovo corren headless), pero con
        # --visible cualquier agregador necesita la misma rejilla para no apilar
        # las ventanas todas en el mismo sitio.
        posicion, tamano = calcular_posicion_ventana(worker_index)
        SCRAPERS[agregador].posicion_ventana_visible = posicion
        SCRAPERS[agregador].tamano_ventana_visible = tamano

    puntos = await _puntos_todos(agregador)
    asignados_totales = [p for i, p in enumerate(puntos) if i % worker_count == worker_index]

    try:
        # Todos los workers llaman a esto -- idempotente del lado del backend (ver
        # backend/agregadores.py::iniciar_ronda), así que no hace falta coordinarse
        # entre sí ni que solo lo haga el worker 0. Da el total REAL (len(puntos),
        # antes de repartir entre workers) para que el "Dashboard del scraper" pueda
        # mostrar progreso en vivo (hechos/faltan) de esta vuelta completa. Si ya
        # había una ronda en curso para este agregador (no cerrada a la fuerza),
        # esto NO crea una nueva -- devuelve la existente tal cual, con su
        # iniciada_en original, que es justo lo que hace falta para reanudar.
        await api_client.iniciar_ronda(agregador, len(puntos), worker_count)
    except Exception as exc:
        logger.warning("No se pudo avisar del inicio de ronda (sigue igual): %r", exc)

    try:
        hechos_ids = set(await api_client.ronda_hechos_ids(agregador))
    except Exception as exc:
        hechos_ids = set()
        logger.warning("No se pudo consultar qué puntos ya cubrió esta ronda (se scrapea todo): %r", exc)

    asignados = [p for p in asignados_totales if p["id"] not in hechos_ids]
    saltados = len(asignados_totales) - len(asignados)
    logger.info(
        "Worker %d/%d (%s): %d puntos de %d totales -- vuelta completa REAL, sin reuso%s",
        worker_index, worker_count, agregador, len(asignados), len(puntos),
        f" ({saltados} ya cubiertos por esta ronda -- reanudando)" if saltados else "",
    )

    buffer_subida: list = []
    ultimo_flush = time.monotonic()

    fallidos = []
    fallos_tecnicos = []
    for i, direccion in enumerate(asignados):
        try:
            # permitir_reuso=False: nunca reutiliza, siempre scrapea de verdad -- es una
            # prueba de carga real. radio_reuso_m=0 NO basta (el punto se encuentra a sí
            # mismo a 0m si ya tenía chequeo, confirmado en vivo 26/08).
            resultados = await chequear_tienda(
                direccion["tienda"], agregador, direcciones_override=[direccion], permitir_reuso=False,
                buffer_subida=buffer_subida,
            )
            if resultados and resultados[0]["error_tecnico"]:
                fallos_tecnicos.append(direccion)
        except Exception as exc:
            # No se descarta sin más -- si esto fue un fallo de CONEXIÓN a nuestro
            # propio backend, el punto queda sin dato para siempre si no se
            # reintenta -- se encola para un segundo/tercer intento al final de la
            # pasada, cuando ya haya menos contención. Cada vez más raro desde que
            # existe la cola local (ver utils/cola_local.py): esto ahora solo salta
            # con un fallo de verdad inesperado, no con la caída del backend (esa ya
            # se encola sola dentro de chequear_tienda sin llegar a propagar aquí).
            logger.error("Fallo revalidando %s (se reintentará al final): %r", direccion.get("direccion_text"), exc)
            fallidos.append(direccion)
        if _debe_flush(buffer_subida, ultimo_flush):
            await flush_buffer_subida(buffer_subida)
            ultimo_flush = time.monotonic()
        if i < len(asignados) - 1:
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    await flush_buffer_subida(buffer_subida)  # lo que quede sin llegar a TAMANO_LOTE

    intentos_extra = 0
    while fallidos and intentos_extra < 3:
        intentos_extra += 1
        logger.info(
            "Worker %d/%d (%s): reintentando %d punto(s) que fallaron del todo (intento extra %d/3)",
            worker_index, worker_count, agregador, len(fallidos), intentos_extra,
        )
        siguen_fallando = []
        for direccion in fallidos:
            try:
                await chequear_tienda(
                    direccion["tienda"], agregador, direcciones_override=[direccion], permitir_reuso=False,
                    buffer_subida=buffer_subida,
                )
            except Exception as exc:
                logger.error("Sigue fallando %s (intento extra %d/3): %r", direccion.get("direccion_text"), intentos_extra, exc)
                siguen_fallando.append(direccion)
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)
        fallidos = siguen_fallando
        await flush_buffer_subida(buffer_subida)

    if fallidos:
        logger.error(
            "Worker %d/%d (%s): %d punto(s) NUNCA se pudieron subir tras 3 reintentos extra: %s",
            worker_index, worker_count, agregador, len(fallidos),
            [d.get("direccion_text") for d in fallidos],
        )

    # Segunda pasada para los fallos TÉCNICOS de scraper (bloqueo/timeout real,
    # tras agotar los 3 reintentos internos de scrapers/base.py) -- pedido
    # explícito del usuario 27/08: dado que la inmensa mayoría de los bloqueos de
    # Glovo se resuelven solos con un navegador nuevo (confirmado en vivo: 304
    # reintentos internos sobre 429 puntos, pero solo 20 fallos definitivos),
    # merece la pena darle a los que sí agotaron sus 3 intentos una SEGUNDA tanda
    # completa al final, cuando ya ha pasado tiempo y quizás el bloqueo puntual se
    # disipó. Cada llamada a chequear_tienda ya hace sus propios 3 intentos
    # internos, así que esto ya es "una segunda pasada de 3 intentos" tal cual.
    if fallos_tecnicos:
        logger.info(
            "Worker %d/%d (%s): %d punto(s) con fallo TÉCNICO de scraper -- segunda pasada completa",
            worker_index, worker_count, agregador, len(fallos_tecnicos),
        )
        siguen_fallando_tecnico = []
        for direccion in fallos_tecnicos:
            try:
                resultados = await chequear_tienda(
                    direccion["tienda"], agregador, direcciones_override=[direccion], permitir_reuso=False,
                    buffer_subida=buffer_subida,
                )
                if resultados and resultados[0]["error_tecnico"]:
                    siguen_fallando_tecnico.append(direccion)
                else:
                    logger.info("  [%s] se recuperó en la segunda pasada", direccion.get("direccion_text"))
            except Exception as exc:
                logger.error(
                    "  [%s] fallo de conexión durante la segunda pasada (se deja para la próxima vuelta): %r",
                    direccion.get("direccion_text"), exc,
                )
                siguen_fallando_tecnico.append(direccion)
            if _debe_flush(buffer_subida, ultimo_flush):
                await flush_buffer_subida(buffer_subida)
                ultimo_flush = time.monotonic()
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

        await flush_buffer_subida(buffer_subida)

        if siguen_fallando_tecnico:
            logger.warning(
                "Worker %d/%d (%s): %d punto(s) siguen con fallo técnico tras la segunda pasada -- "
                "se quedan con el último dato real conocido (o sin datos), la próxima vuelta lo reintenta: %s",
                worker_index, worker_count, agregador, len(siguen_fallando_tecnico),
                [d.get("direccion_text") for d in siguen_fallando_tecnico],
            )
        else:
            logger.info(
                "Worker %d/%d (%s): todos los fallos técnicos se recuperaron en la segunda pasada.",
                worker_index, worker_count, agregador,
            )

    # Red de seguridad: no debería quedar nada sin subir a estas alturas (cada
    # bucle ya hace su propio flush), pero por si acaso -- nunca cerrar la ronda
    # con datos reales todavía en memoria sin subir.
    await flush_buffer_subida(buffer_subida)

    logger.info("Worker %d/%d (%s) terminado.", worker_index, worker_count, agregador)

    try:
        # Idempotente igual que iniciar_ronda -- el primer worker en terminar cierra
        # la ronda, los demás son no-ops. Si un worker se cae a mitad y nunca llega
        # aquí, la ronda se queda "activa" para siempre en el dashboard -- aceptable
        # para una prueba puntual (no es un problema de datos, solo visual).
        await api_client.finalizar_ronda(agregador)
    except Exception as exc:
        logger.warning("No se pudo avisar del fin de ronda (sigue igual): %r", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agregador", required=True, choices=["justeat", "glovo", "ubereats"])
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument(
        "--permitir-imagenes", action="store_true",
        help="Prueba puntual: no bloquear imágenes/media (por defecto SÍ se bloquean) -- para comparar tasa de fallos.",
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Prueba puntual: correr con ventana genuinamente visible, igual que Uber Eats (por defecto JustEat/Glovo corren headless).",
    )
    parser.add_argument(
        "--proxy-index", type=int, default=None,
        help="Experimento de rotación de IP: índice (0-based) dentro de config.PROXIES (ver SCRAPER_PROXIES en .env) para que ESTE worker salga por ese proxy en vez de la IP propia. Sin esto, sale por la IP propia como siempre.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.agregador, args.worker_index, args.worker_count, args.permitir_imagenes, args.visible, args.proxy_index))
