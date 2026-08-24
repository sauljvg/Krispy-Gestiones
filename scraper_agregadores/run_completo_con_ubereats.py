"""Pasada completa de las 6 tiendas para los 3 agregadores (JustEat, Glovo,
Uber Eats) EN PRODUCCION -- como chequeo_completo() del scheduler, pero
Uber Eats incluido a mano (sigue fuera de config.AGREGADORES) y con un
corte automático: si su fallo técnico acumulado supera el 40% (con una
muestra mínima antes de evaluar, para no cortar por 1-2 fallos sueltos al
principio), se deja de comprobar Uber Eats en el resto de tiendas -- pero
JustEat y Glovo siguen normal en todas.
"""
import asyncio
import logging

import config
from main import chequear_tienda, SCRAPERS

logging.basicConfig(
    level=config.SCRAPER_LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/run_completo_con_ubereats.log", mode="a", encoding="utf-8")],
)
logger = logging.getLogger("completo_ubereats")

UBEREATS_MUESTRA_MINIMA = 10
UBEREATS_UMBRAL_FALLO = 0.40


class ContadorUberEats:
    def __init__(self):
        self.exitosos = 0
        self.fallidos = 0
        self.activo = True

    def registrar(self, fallo: bool):
        if fallo:
            self.fallidos += 1
        else:
            self.exitosos += 1

    @property
    def total(self):
        return self.exitosos + self.fallidos

    @property
    def tasa_fallo(self):
        return self.fallidos / self.total if self.total else 0.0

    def evaluar_corte(self):
        if self.activo and self.total >= UBEREATS_MUESTRA_MINIMA and self.tasa_fallo > UBEREATS_UMBRAL_FALLO:
            self.activo = False
            logger.warning(
                "UBER EATS DESACTIVADO para el resto de la pasada: %d/%d fallos técnicos (%.0f%%) -- por encima del %.0f%% umbral",
                self.fallidos, self.total, self.tasa_fallo * 100, UBEREATS_UMBRAL_FALLO * 100,
            )


async def chequear_ubereats_contado(tienda: str, contador: ContadorUberEats):
    """Como chequear_tienda, pero registrando cada resultado en el contador
    para poder evaluar el corte del 40% según se avanza, no solo al final."""
    from utils import api_client

    direcciones = await api_client.obtener_direcciones(tienda, cercano=False, agregador="ubereats")
    scraper = SCRAPERS["ubereats"](timeout_seg=config.SCRAPER_TIMEOUT, retry_max=config.SCRAPER_RETRY_MAX)

    for direccion in direcciones:
        if not contador.activo:
            logger.info("Uber Eats desactivado -- se saltan las %d direcciones restantes de %s", len(direcciones), tienda)
            break

        texto = direccion["direccion_text"]
        logger.info("Chequeando %s / ubereats @ %s", tienda, texto)
        resultado = await scraper.verificar_disponibilidad(tienda, texto)

        respuesta = await api_client.enviar_chequeo({
            "tienda": tienda, "agregador": "ubereats", "direccion_id": direccion["id"],
            "disponible": resultado.disponible, "tiempo_entrega_min": resultado.tiempo_entrega_min,
            "mensaje_bloqueo": resultado.mensaje_bloqueo, "error_texto": resultado.error_texto,
        })
        if resultado.url_captura:
            await api_client.subir_captura(respuesta["chequeo_id"], resultado.url_captura)

        logger.info("  -> disponible=%s error=%s", resultado.disponible, resultado.error_texto)
        contador.registrar(fallo=bool(resultado.error_texto))
        contador.evaluar_corte()

        await asyncio.sleep(config.DELAY_ENTRE_CHEQUEOS_SEG)


async def main():
    contador = ContadorUberEats()

    for tienda in config.TIENDAS_SCHEDULER:
        logger.info("=== %s ===", tienda)
        await chequear_tienda(tienda, "justeat", cercano=False, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG)
        await chequear_tienda(tienda, "glovo", cercano=False, delay_seg=config.DELAY_ENTRE_CHEQUEOS_SEG)

        if contador.activo:
            await chequear_ubereats_contado(tienda, contador)
        else:
            logger.info("Uber Eats sigue desactivado, se salta %s", tienda)

    logger.info(
        "=== RESUMEN FINAL: Uber Eats %d/%d fallos técnicos (%.0f%%), activo al final=%s ===",
        contador.fallidos, contador.total, contador.tasa_fallo * 100, contador.activo,
    )


if __name__ == "__main__":
    asyncio.run(main())
