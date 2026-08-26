"""Busca el límite real de cobertura de una tienda, dirección por dirección
(ángulo alrededor de la tienda), mediante búsqueda adaptativa: expande hacia
fuera hasta encontrar un punto sin cobertura, luego binaria hasta +-500m.

Cada punto probado se crea de verdad en producción (POST /admin/direcciones/
calculada) y cada chequeo se sube igual que el daemon normal -- así queda
visible en el mapa de cobertura del dashboard, no es una simulación aparte.
"""
import argparse
import asyncio
import logging
from datetime import datetime

import config
from scrapers.glovo import GlovoScraper
from scrapers.justeat import JustEatScraper
from scrapers.ubereats import UberEatsScraper
from utils import api_client
from utils.ventana import calcular_posicion_ventana

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/buscar_limite_cobertura.log", mode="a", encoding="utf-8")],
)
logger = logging.getLogger("limite")

SCRAPERS = {"glovo": GlovoScraper, "justeat": JustEatScraper, "ubereats": UberEatsScraper}
PRECISION_KM = 0.5
# Si la geocodificación de dos distancias "mid" distintas cae en la MISMA
# dirección real (zona con pocas direcciones numeradas), seguir pidiendo
# puntos intermedios no sirve de nada -- red de seguridad contra bucle
# infinito real (visto en producción: 256 iteraciones seguidas sin converger).
PRECISION_MINIMA_KM = 0.02
MAX_ITERACIONES_BINARIA = 12
DISTANCIAS_EXPANSION = [2.5, 5.0, 7.0, 9.0]
# Si ni el primer punto de la expansión (2.5km) tiene cobertura, se prueban
# estas distancias (de más cerca a menos) como extremo "seguro" para afinar
# el límite hacia dentro en vez de quedarnos solo con "< 2.5km" -- una tienda
# grande (centro comercial) puede tener solo rondas/avenidas sin número justo
# alrededor, así que hace falta más de un intento.
BASELINE_CERCANO_ESCALERA_KM = [0.3, 0.6, 1.0]
MAX_REINTENTOS_TECNICO = 2
# Si la línea recta de un ángulo cae en una autovía/polígono sin direcciones
# reales, la búsqueda en espiral (radio máx 0.5km) puede agotarse sin
# encontrar nada válido -- probamos pequeños empujones de ángulo alrededor
# del pedido para esquivar ese tramo concreto, sin desviarnos de verdad de
# la dirección que se está sondeando.
JITTERS_ANGULO = [0, 4, -4, 8, -8]


async def _crear_direccion_con_reintento(tienda, distancia_km, angulo_grados, intentos=3):
    """Un timeout o corte de red puntual no debería tirar un proceso de
    horas por la borda -- reintenta unas pocas veces con pausa antes de
    dejar que el error suba de verdad."""
    for intento in range(intentos):
        try:
            return await api_client.crear_direccion_calculada(tienda, distancia_km, angulo_grados)
        except Exception as exc:
            if intento == intentos - 1:
                raise
            logger.warning("  fallo de red creando punto (intento %d/%d): %r -- reintentando", intento + 1, intentos, exc)
            await asyncio.sleep(5)


async def crear_punto_valido(tienda: str, distancia_km: float, angulo_grados: float):
    """Como api_client.crear_direccion_calculada, pero reintenta con pequeños
    empujones de ángulo si el punto cae en una autovía/zona sin direcciones
    reales (ver JITTERS_ANGULO). Devuelve None si ni con eso se encuentra
    nada válido -- ese paso se salta, no cuenta como dato real."""
    for jitter in JITTERS_ANGULO:
        punto = await _crear_direccion_con_reintento(tienda, distancia_km, (angulo_grados + jitter) % 360)
        if punto.get("direccion_valida", True):
            return punto
        logger.warning(
            "  punto inválido (%.2fkm, %.0f° con empuje %+d): %s -- borrando y probando otro empuje",
            punto["distancia_km"], angulo_grados, jitter, punto["direccion_text"],
        )
        try:
            await api_client.eliminar_direccion(punto["id"])
        except Exception as exc:
            logger.warning("  no se pudo dar de baja el punto inválido %s: %r", punto["id"], exc)
    return None


async def resultado_punto(scraper, tienda, punto, agregador, avisos: list) -> str:
    """Como chequear_punto, pero si el punto cae más cerca de OTRA sucursal
    (ver crear_punto_calculado / tienda_mas_cercana) el resultado NO se usa
    como límite de ESTA tienda -- con varias tiendas relativamente próximas
    (ej. Princesa-Caleido a 6km), un "disponible" ahí PODRÍA deberse a que
    responde la otra tienda, porque los agregadores solo buscan por marca
    "Krispy Kreme" y no distinguen sucursal. Antes esto era solo un aviso
    informativo y la búsqueda seguía expandiéndose igual -- confirmado en
    vivo 09/08 que eso producía picos falsos de +9km en el polígono que en
    realidad eran cobertura de OTRA tienda. Se devuelve 'contaminado' para
    que la búsqueda pare ahí en esa dirección; si el resultado real es
    "disponible", se reasigna como punto suelto a la tienda a la que de
    verdad pertenece en vez de perder el dato (pedido explícito del
    usuario 09/08)."""
    # ¿Ya hay un chequeo real reciente de este agregador a menos de 100m de
    # este punto exacto (de cualquier tienda)? Se reutiliza en vez de
    # scrapear otra vez -- evita repetir la misma dirección real cuando dos
    # tiendas vecinas con zonas de solape (o rondas sucesivas 8->16->32)
    # acaban probando prácticamente el mismo sitio (pedido explícito del
    # usuario 09/08).
    try:
        reuso = await api_client.buscar_chequeo_cercano(punto["lat"], punto["lng"], agregador)
    except Exception as exc:
        reuso = None
        logger.warning("  no se pudo consultar reuso de chequeo cercano: %r", exc)
    if reuso is not None:
        logger.info(
            "  [%s/%s] reutilizado de '%s' (%.3fkm, %s) -> %s",
            tienda, agregador, reuso["tienda_origen"], reuso["distancia_km"], reuso["direccion_text"],
            "disponible" if reuso["disponible"] else "no_disponible",
        )
        try:
            await api_client.enviar_chequeo({
                "tienda": tienda, "agregador": agregador, "direccion_id": punto["id"],
                "disponible": reuso["disponible"],
            })
        except Exception as exc:
            logger.warning("  no se pudo subir el chequeo reutilizado a KG: %r", exc)
        return "disponible" if reuso["disponible"] else "no_disponible"

    otra = punto.get("tienda_mas_cercana")
    if otra and otra != tienda:
        logger.warning(
            "  %.2fkm cae más cerca de '%s' que de '%s' -- se comprueba pero no se usa como límite de esta tienda",
            punto["distancia_km"], otra, tienda,
        )
        avisos.append(punto["distancia_km"])
        resultado = await chequear_punto(scraper, tienda, punto["id"], punto["direccion_text"], agregador)
        if resultado == "disponible":
            # No se tira el dato -- se guarda como punto suelto de la
            # tienda a la que de verdad pertenece (pedido explícito del
            # usuario 09/08: "si dice cerrado que en realidad es la otra
            # sucursal, asignémoslo a la tienda correcta en vez de
            # descartarlo"). Solo para "disponible": un "no_disponible"
            # cerca de otra tienda no aporta nada útil para ninguna de
            # las dos.
            try:
                direccion = await api_client.reasignar_punto_otra_tienda(
                    otra, punto["lat"], punto["lng"], punto["direccion_text"],
                )
                await api_client.enviar_chequeo({
                    "tienda": otra,
                    "agregador": agregador,
                    "direccion_id": direccion["id"],
                    "disponible": True,
                })
                logger.info("  punto reasignado a '%s' (más cerca que '%s')", otra, tienda)
            except Exception as exc:
                logger.warning("  no se pudo reasignar el punto a '%s': %r", otra, exc)
        return "contaminado"
    return await chequear_punto(scraper, tienda, punto["id"], punto["direccion_text"], agregador)


# Frase EXACTA (idéntica en glovo.py, justeat.py y ubereats.py) que se lanza
# cuando la búsqueda de la tienda se completó de verdad (sin challenge, sin
# fallo de red) pero Krispy Kreme sencillamente no salió en los resultados.
# Confirmado a mano por el usuario 09/08 (comprobación manual real en Uber
# Eats): esto NO es un fallo técnico nuestro -- es una búsqueda válida que
# no encontró la tienda, exactamente la misma señal que "no disponible".
MARCADOR_TIENDA_NO_CONFIRMADA = "tienda no confirmada en resultados de búsqueda"


async def chequear_punto(scraper, tienda, direccion_id, direccion_text, agregador) -> str:
    """Devuelve 'disponible', 'no_disponible' o 'error' (fallo técnico
    persistente tras reintentar) -- y sube cada intento a producción igual
    que el flujo normal del daemon.

    Nota (aclarado por el usuario 08/08): cuando Uber Eats muestra la tienda
    cerrada pero permite PROGRAMAR la entrega, el propio scraper
    (ubereats.py::_leer_disponibilidad) ya lo traduce a disponible=True --
    eso en sí es la prueba de que la dirección está dentro de la zona de
    reparto, aunque la tienda no esté operando ahora mismo. No hace falta
    tratarlo aparte aquí."""
    ultimo_resultado = None
    for intento in range(MAX_REINTENTOS_TECNICO + 1):
        resultado = await scraper.verificar_disponibilidad(tienda, direccion_text)
        ultimo_resultado = resultado
        try:
            await api_client.enviar_chequeo(
                {
                    "tienda": tienda,
                    "agregador": agregador,
                    "direccion_id": direccion_id,
                    "disponible": resultado.disponible,
                    "tiempo_entrega_min": resultado.tiempo_entrega_min,
                    "mensaje_bloqueo": resultado.mensaje_bloqueo,
                    "error_texto": resultado.error_texto,
                }
            )
        except Exception as exc:
            logger.warning("No se pudo subir el chequeo a KG: %r", exc)
        if resultado.error_texto:
            logger.warning("  fallo técnico (intento %d/%d): %s", intento + 1, MAX_REINTENTOS_TECNICO + 1, resultado.error_texto)
            continue
        return "disponible" if resultado.disponible else "no_disponible"

    if ultimo_resultado and ultimo_resultado.error_texto and MARCADOR_TIENDA_NO_CONFIRMADA in ultimo_resultado.error_texto:
        # Reintentado el máximo de veces y SIEMPRE la misma búsqueda válida
        # sin encontrar la tienda -- se acepta como "no disponible" real en
        # vez de dejarlo como fallo técnico inconcluso.
        logger.info("  tienda no confirmada de forma persistente -- se acepta como no_disponible real, no como fallo técnico")
        return "no_disponible"
    return "error"


async def buscar_limite_direccion(tienda: str, angulo: float, agregador: str) -> dict:
    scraper = SCRAPERS[agregador](timeout_seg=config.SCRAPER_TIMEOUT, retry_max=config.SCRAPER_RETRY_MAX)
    lo = hi = None
    # El punto REAL (lat/lng/direccion_text) del último "disponible"
    # confirmado -- se guarda junto al límite para que el dashboard dibuje
    # el vértice donde de verdad se probó la entrega, no en la recta
    # geométrica centro-ángulo-distancia (que puede caer en medio de un
    # parque sin ninguna calle real, confirmado en vivo 09/08).
    punto_lo = None
    avisos_otra_tienda = []
    parado_por_contaminacion = False

    for d in DISTANCIAS_EXPANSION:
        punto = await crear_punto_valido(tienda, d, angulo)
        if punto is None:
            logger.warning("[%s/%s/%.0f°] %.2fkm -- sin dirección real cerca (autovía/polígono), se salta este paso", tienda, agregador, angulo, d)
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)
            continue
        resultado = await resultado_punto(scraper, tienda, punto, agregador, avisos_otra_tienda)
        d_real = punto["distancia_km"]
        logger.info(
            "[%s/%s/%.0f°] expansión %.2fkm -> %s (%s)",
            tienda, agregador, angulo, d_real, resultado, punto["direccion_text"],
        )
        if resultado == "disponible":
            lo = d_real
            punto_lo = punto
        elif resultado == "no_disponible":
            hi = d_real
            break
        elif resultado == "contaminado":
            # A partir de aquí los "disponible" podrían ser en realidad de
            # otra sucursal -- no tiene sentido seguir expandiendo, el dato
            # ya no se puede atribuir con fiabilidad a esta tienda.
            parado_por_contaminacion = True
            break
        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    def _con_aviso(resultado: dict) -> dict:
        if avisos_otra_tienda:
            aviso = f"ojo: desde ~{min(avisos_otra_tienda)}km en esta dirección hay puntos más cerca de otra sucursal (el 'disponible' ahí podría ser de esa tienda, no de {tienda})"
            resultado["nota"] = f"{resultado['nota']} -- {aviso}" if resultado["nota"] else aviso
        return resultado

    def _con_punto(resultado: dict) -> dict:
        resultado["lat"] = punto_lo["lat"] if punto_lo else None
        resultado["lng"] = punto_lo["lng"] if punto_lo else None
        resultado["direccion_text"] = punto_lo["direccion_text"] if punto_lo else None
        return resultado

    if hi is None:
        if parado_por_contaminacion:
            nota = f">= {lo}km (no se pudo seguir: más allá cae más cerca de otra sucursal)" if lo else "sin datos (cae más cerca de otra sucursal desde el primer punto probado)"
        else:
            nota = f">= {lo}km (no se encontró el borde dentro del rango probado)" if lo else "sin datos (todo falló)"
        return _con_punto(_con_aviso({"angulo": angulo, "limite_km": None, "nota": nota}))
    if lo is None:
        # Ni el primer punto probado (el más cercano de la expansión) tenía
        # cobertura -- en vez de conformarnos con "< X", afinamos hacia
        # dentro igual que la binaria normal, partiendo de un punto muy
        # cercano a la tienda (BASELINE_CERCANO) que casi seguro sí tiene
        # cobertura real (si ni eso, no hay límite que buscar en esta
        # dirección: se marca aparte).
        punto_base = None
        for baseline in BASELINE_CERCANO_ESCALERA_KM:
            punto_base = await crear_punto_valido(tienda, baseline, angulo)
            if punto_base is not None:
                break
        if punto_base is None:
            return _con_punto(_con_aviso({"angulo": angulo, "limite_km": None, "nota": f"< {hi}km (sin dirección real cerca de la tienda en esta dirección, ni hasta {BASELINE_CERCANO_ESCALERA_KM[-1]}km)"}))
        resultado_base = await resultado_punto(scraper, tienda, punto_base, agregador, avisos_otra_tienda)
        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)
        if resultado_base == "contaminado":
            # Incluso el punto más cercano posible cae más cerca de otra
            # sucursal -- no se puede decir nada fiable de esta dirección
            # para esta tienda (caso raro, pero mejor esto que inventar un
            # "no disponible" que en realidad es solo contaminación).
            return _con_punto(_con_aviso({
                "angulo": angulo, "limite_km": None,
                "nota": f"no se pudo determinar -- incluso a {punto_base['distancia_km']}km de la tienda cae más cerca de otra sucursal",
            }))
        if resultado_base != "disponible":
            return _con_punto(_con_aviso({
                "angulo": angulo, "limite_km": None,
                "nota": f"no disponible incluso a {punto_base['distancia_km']}km de la tienda -- puede que esta dirección esté fuera de zona por completo",
            }))
        lo = punto_base["distancia_km"]
        punto_lo = punto_base

    iteraciones = 0
    while (hi - lo) > PRECISION_KM:
        iteraciones += 1
        if iteraciones > MAX_ITERACIONES_BINARIA:
            logger.warning("[%s/%s/%.0f°] %d iteraciones sin converger, se para la binaria con lo que hay", tienda, agregador, angulo, iteraciones)
            break
        mid = round((lo + hi) / 2, 2)
        punto = await crear_punto_valido(tienda, mid, angulo)
        if punto is None:
            logger.warning("[%s/%s/%.0f°] %.2fkm -- sin dirección real cerca, se para la binaria aquí", tienda, agregador, angulo, mid)
            break
        d_real = punto["distancia_km"]
        if abs(d_real - lo) < PRECISION_MINIMA_KM or abs(d_real - hi) < PRECISION_MINIMA_KM:
            # La búsqueda en espiral geocodificó al MISMO punto real ya
            # probado (la zona no tiene más direcciones numeradas entre lo y
            # hi) -- pedir un mid distinto no sirve de nada, siempre cae
            # aquí. Sin esto, hi/lo nunca se mueven y (hi - lo) no baja
            # nunca de PRECISION_KM: bucle infinito real, confirmado en vivo
            # (256 iteraciones seguidas en el mismo punto antes de este fix).
            logger.warning(
                "[%s/%s/%.0f°] %.2fkm geocodifica al mismo punto ya probado (%s) -- no hay más direcciones numeradas por aquí, se para la binaria",
                tienda, agregador, angulo, mid, punto["direccion_text"],
            )
            break
        resultado = await resultado_punto(scraper, tienda, punto, agregador, avisos_otra_tienda)
        logger.info(
            "[%s/%s/%.0f°] binaria %.2fkm -> %s (%s)",
            tienda, agregador, angulo, d_real, resultado, punto["direccion_text"],
        )
        if resultado == "disponible":
            lo = d_real
            punto_lo = punto
        elif resultado == "no_disponible":
            hi = d_real
        elif resultado == "contaminado":
            # A partir de aquí no se puede afinar más con datos fiables --
            # se queda con el rango [lo, hi] ya confirmado hasta ahora.
            logger.warning("  punto en zona de otra sucursal, se para la binaria aquí con lo que hay")
            break
        else:
            logger.warning("  fallo técnico persistente en la binaria, se para aquí con lo que hay")
            break
        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    return _con_punto(_con_aviso({"angulo": angulo, "limite_km": round((lo + hi) / 2, 2), "nota": None}))


def _tienda_cerrada(tienda: str) -> bool:
    cierre = config.HORARIOS_CIERRE_TIENDAS.get(tienda)
    if cierre is None:
        return False
    ahora = datetime.now()
    hora_decimal = ahora.hour + ahora.minute / 60
    return hora_decimal >= cierre


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tienda", default="parquesur")
    parser.add_argument("--agregadores", nargs="+", default=["glovo", "justeat"])
    parser.add_argument("--angulos", nargs="+", type=float, default=[0, 45, 90, 135, 180, 225, 270, 315])
    parser.add_argument(
        "--avisar-challenge", action="store_true",
        help="Notificación + navegador visible SOLO cuando se detecte un challenge anti-bot real (90s para resolverlo a mano); silencioso el resto del tiempo.",
    )
    parser.add_argument(
        "--reintentar-completados", action="store_true",
        help="Rehacer también los ángulos que ya tienen un resultado guardado (por defecto se saltan).",
    )
    parser.add_argument(
        "--ventana-slot", type=int, default=None,
        help="Cuando se corren varios procesos en paralelo (p.ej. una tienda partida en 2 "
        "sub-procesos), asigna a cada uno una celda distinta (0-5) de una rejilla 3x2 en el "
        "segundo monitor para que sus ventanas visibles de Uber Eats no queden apiladas en el "
        "mismo punto -- si dos procesos comparten posición, solo la ventana que quede encima "
        "es visible/resoluble ante un challenge real.",
    )
    args = parser.parse_args()

    if args.avisar_challenge:
        for scraper_cls in SCRAPERS.values():
            scraper_cls.permitir_resolucion_manual = True

    if args.ventana_slot is not None:
        # Rejilla compartida con daemon.py (--worker-index) -- ver utils/ventana.py.
        # OJO: los procesos ya lanzados con la rejilla vieja (3x2, celdas
        # 640x516) siguen con esas posiciones hasta que terminen -- no hay hueco
        # libre para 2 ventanas más sin encoger la rejilla entera, así que los
        # slots 6-7 pueden solaparse visualmente con los slots 4-5 viejos
        # mientras ambas tandas coexistan. Solo importa si a las dos les toca
        # un challenge real de Uber Eats a la vez (no visto hasta ahora).
        posicion, tamano = calcular_posicion_ventana(args.ventana_slot)
        for scraper_cls in SCRAPERS.values():
            scraper_cls.posicion_ventana_visible = posicion
            scraper_cls.tamano_ventana_visible = tamano

    resultados = {}
    for agregador in args.agregadores:
        resultados[agregador] = []

        # Confirmado en vivo 08/08: cada vez que se relanza el script (p.ej. tras
        # un fix), volvía a empezar desde el primer ángulo, rehaciendo minutos
        # de trabajo ya hecho -- se consulta qué ángulos ya tienen un resultado
        # guardado y se saltan, a menos que se pida explícitamente rehacerlos.
        angulos_completados = set()
        if not args.reintentar_completados:
            try:
                guardados = await api_client.obtener_limites(args.tienda, agregador)
                # El backend redondea angulo_grados a ENTERO al guardar (ver
                # guardar_limite/eliminar_limite en agregadores.py), no a 2
                # decimales -- comparar con round(x, 2) nunca coincidía para
                # los ángulos fraccionarios de la campaña de 32 (11.25°,
                # 22.5°...), así que el skip-logic los rehacía enteros en
                # cada relanzamiento (confirmado en vivo 10/08 con
                # parquesur/glovo/11.25°). Hay que redondear igual que el
                # backend en los dos lados de la comparación.
                angulos_completados = {int(round(float(fila["angulo_grados"]))) for fila in guardados}
            except Exception as exc:
                logger.warning("No se pudo consultar ángulos ya completados (se procesan todos): %r", exc)

        for angulo in args.angulos:
            if int(round(float(angulo))) in angulos_completados:
                logger.info("[%s/%s/%s°] ya tiene resultado guardado -- se salta", args.tienda, agregador, angulo)
                continue

            # NOTA (aclarado por el usuario 08/08): ya NO se para por horario de
            # cierre -- "cerrado pero permite programar" ahora cuenta como
            # disponible=True (confirma zona de reparto igual, ver
            # ubereats.py::_leer_disponibilidad), así que correr con la tienda
            # cerrada ya no corrompe el límite. _tienda_cerrada() se deja
            # definida por si hace falta retomar este comportamiento.

            # Un fallo puntual (red, sitio caído un momento) en UNA dirección
            # no debe tirar por la borda las horas de progreso en el resto --
            # se registra como fallo y se sigue con la siguiente.
            try:
                r = await buscar_limite_direccion(args.tienda, angulo, agregador)
            except Exception as exc:
                logger.error("[%s/%s/%s°] fallo irrecuperable, se salta esta dirección: %r", args.tienda, agregador, angulo, exc)
                r = {"angulo": angulo, "limite_km": None, "nota": f"fallo del script: {exc!r}"}
            resultados[agregador].append(r)
            logger.info("RESULTADO %s / %s / %s°: %s", args.tienda, agregador, angulo, r)
            try:
                await api_client.guardar_limite(
                    args.tienda, agregador, angulo, r["limite_km"], r["nota"],
                    lat=r.get("lat"), lng=r.get("lng"), direccion_text=r.get("direccion_text"),
                )
            except Exception as exc:
                logger.warning("No se pudo guardar el límite en KG: %r", exc)

    logger.info("=== RESUMEN FINAL (%s) ===", args.tienda)
    for agregador, lista in resultados.items():
        logger.info("%s: %s", agregador, lista)


if __name__ == "__main__":
    asyncio.run(main())
