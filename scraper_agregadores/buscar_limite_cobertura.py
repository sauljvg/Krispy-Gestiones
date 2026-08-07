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

import config
from scrapers.glovo import GlovoScraper
from scrapers.justeat import JustEatScraper
from utils import api_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/buscar_limite_cobertura.log", mode="a", encoding="utf-8")],
)
logger = logging.getLogger("limite")

SCRAPERS = {"glovo": GlovoScraper, "justeat": JustEatScraper}
PRECISION_KM = 0.5
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
            "  punto inválido (%.2fkm, %.0f° con empuje %+d): %s -- probando otro empuje",
            punto["distancia_km"], angulo_grados, jitter, punto["direccion_text"],
        )
    return None


async def chequear_punto(scraper, tienda, direccion_id, direccion_text, agregador) -> str:
    """Devuelve 'disponible', 'no_disponible' o 'error' (fallo técnico
    persistente tras reintentar) -- y sube cada intento a producción igual
    que el flujo normal del daemon."""
    for intento in range(MAX_REINTENTOS_TECNICO + 1):
        resultado = await scraper.verificar_disponibilidad(tienda, direccion_text)
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
    return "error"


async def buscar_limite_direccion(tienda: str, angulo: float, agregador: str) -> dict:
    scraper = SCRAPERS[agregador](timeout_seg=config.SCRAPER_TIMEOUT, retry_max=config.SCRAPER_RETRY_MAX)
    lo = hi = None

    for d in DISTANCIAS_EXPANSION:
        punto = await crear_punto_valido(tienda, d, angulo)
        if punto is None:
            logger.warning("[%s/%s/%.0f°] %.2fkm -- sin dirección real cerca (autovía/polígono), se salta este paso", tienda, agregador, angulo, d)
            await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)
            continue
        resultado = await chequear_punto(scraper, tienda, punto["id"], punto["direccion_text"], agregador)
        d_real = punto["distancia_km"]
        logger.info(
            "[%s/%s/%.0f°] expansión %.2fkm -> %s (%s)",
            tienda, agregador, angulo, d_real, resultado, punto["direccion_text"],
        )
        if resultado == "disponible":
            lo = d_real
        elif resultado == "no_disponible":
            hi = d_real
            break
        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    if hi is None:
        nota = f">= {lo}km (no se encontró el borde dentro del rango probado)" if lo else "sin datos (todo falló)"
        return {"angulo": angulo, "limite_km": None, "nota": nota}
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
            return {"angulo": angulo, "limite_km": None, "nota": f"< {hi}km (sin dirección real cerca de la tienda en esta dirección, ni hasta {BASELINE_CERCANO_ESCALERA_KM[-1]}km)"}
        resultado_base = await chequear_punto(scraper, tienda, punto_base["id"], punto_base["direccion_text"], agregador)
        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)
        if resultado_base != "disponible":
            return {
                "angulo": angulo, "limite_km": None,
                "nota": f"no disponible incluso a {punto_base['distancia_km']}km de la tienda -- puede que esta dirección esté fuera de zona por completo",
            }
        lo = punto_base["distancia_km"]

    while (hi - lo) > PRECISION_KM:
        mid = round((lo + hi) / 2, 2)
        punto = await crear_punto_valido(tienda, mid, angulo)
        if punto is None:
            logger.warning("[%s/%s/%.0f°] %.2fkm -- sin dirección real cerca, se para la binaria aquí", tienda, agregador, angulo, mid)
            break
        resultado = await chequear_punto(scraper, tienda, punto["id"], punto["direccion_text"], agregador)
        d_real = punto["distancia_km"]
        logger.info(
            "[%s/%s/%.0f°] binaria %.2fkm -> %s (%s)",
            tienda, agregador, angulo, d_real, resultado, punto["direccion_text"],
        )
        if resultado == "disponible":
            lo = d_real
        elif resultado == "no_disponible":
            hi = d_real
        else:
            logger.warning("  fallo técnico persistente en la binaria, se para aquí con lo que hay")
            break
        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)

    return {"angulo": angulo, "limite_km": round((lo + hi) / 2, 2), "nota": None}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tienda", default="parquesur")
    parser.add_argument("--agregadores", nargs="+", default=["glovo", "justeat"])
    parser.add_argument("--angulos", nargs="+", type=float, default=[0, 45, 90, 135, 180, 225, 270, 315])
    args = parser.parse_args()

    resultados = {}
    for agregador in args.agregadores:
        resultados[agregador] = []
        for angulo in args.angulos:
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

    logger.info("=== RESUMEN FINAL (%s) ===", args.tienda)
    for agregador, lista in resultados.items():
        logger.info("%s: %s", agregador, lista)


if __name__ == "__main__":
    asyncio.run(main())
