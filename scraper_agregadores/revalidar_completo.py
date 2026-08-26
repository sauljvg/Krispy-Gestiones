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

Uso (un agregador por tanda, varios procesos):
    venv/Scripts/python revalidar_completo.py --agregador ubereats --worker-index 0 --worker-count 20
"""
import argparse
import asyncio
import logging

import config
from main import SCRAPERS, chequear_tienda
from utils import api_client
from utils.ventana import calcular_posicion_ventana

logging.basicConfig(level=config.SCRAPER_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("revalidar_completo")


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
    permitir_imagenes: bool = False, visible: bool = False,
):
    if permitir_imagenes:
        # Prueba puntual 26/08: comprobar si bloquear imágenes/media es lo que
        # dispara la página de error genérica de Glovo bajo carga ("Oh, no! It
        # looks like there's a problem") -- hipótesis del usuario, sin confirmar.
        # Solo para este proceso (atributo de CLASE, pero cada worker es su propio
        # proceso Python aparte, así que no se pisa entre workers).
        SCRAPERS[agregador].bloquear_recursos = False
        logger.info("Worker %d/%d (%s): imágenes/media SIN bloquear (prueba puntual)", worker_index, worker_count, agregador)

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
    asignados = [p for i, p in enumerate(puntos) if i % worker_count == worker_index]
    logger.info(
        "Worker %d/%d (%s): %d puntos de %d totales -- vuelta completa REAL, sin reuso",
        worker_index, worker_count, agregador, len(asignados), len(puntos),
    )

    try:
        # Todos los workers llaman a esto -- idempotente del lado del backend (ver
        # backend/agregadores.py::iniciar_ronda), así que no hace falta coordinarse
        # entre sí ni que solo lo haga el worker 0. Da el total REAL (len(puntos),
        # antes de repartir entre workers) para que el "Dashboard del scraper" pueda
        # mostrar progreso en vivo (hechos/faltan) de esta vuelta completa.
        await api_client.iniciar_ronda(agregador, len(puntos), worker_count)
    except Exception as exc:
        logger.warning("No se pudo avisar del inicio de ronda (sigue igual): %r", exc)

    fallidos = []
    for i, direccion in enumerate(asignados):
        try:
            # permitir_reuso=False: nunca reutiliza, siempre scrapea de verdad -- es una
            # prueba de carga real. radio_reuso_m=0 NO basta (el punto se encuentra a sí
            # mismo a 0m si ya tenía chequeo, confirmado en vivo 26/08).
            await chequear_tienda(
                direccion["tienda"], agregador, direcciones_override=[direccion], permitir_reuso=False
            )
        except Exception as exc:
            # No se descarta sin más -- si esto fue un fallo de CONEXIÓN a nuestro
            # propio backend (confirmado en vivo 26/08: ClientConnectorError por
            # saturación de sockets con muchos workers a la vez, agotó hasta los
            # reintentos de api_client._solicitar), el punto queda sin dato para
            # siempre si no se reintenta -- se encola para un segundo/tercer intento
            # al final de la pasada, cuando ya haya menos contención.
            logger.error("Fallo revalidando %s (se reintentará al final): %r", direccion.get("direccion_text"), exc)
            fallidos.append(direccion)
        if i < len(asignados) - 1:
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

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
                    direccion["tienda"], agregador, direcciones_override=[direccion], permitir_reuso=False
                )
            except Exception as exc:
                logger.error("Sigue fallando %s (intento extra %d/3): %r", direccion.get("direccion_text"), intentos_extra, exc)
                siguen_fallando.append(direccion)
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)
        fallidos = siguen_fallando

    if fallidos:
        logger.error(
            "Worker %d/%d (%s): %d punto(s) NUNCA se pudieron subir tras 3 reintentos extra: %s",
            worker_index, worker_count, agregador, len(fallidos),
            [d.get("direccion_text") for d in fallidos],
        )

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
    args = parser.parse_args()
    asyncio.run(main(args.agregador, args.worker_index, args.worker_count, args.permitir_imagenes, args.visible))
