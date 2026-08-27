"""Reenvía a KG los chequeos que quedaron en cola_pendiente/ porque el backend
estaba caído/rechazando peticiones en el momento del scrape (ver
utils/cola_local.py). El dato real YA se obtuvo -- esto solo reintenta la
SUBIDA, nunca vuelve a scrapear nada.

Uso:
    venv/Scripts/python reenviar_cola.py

Seguro de ejecutar varias veces o en bucle: cada archivo se borra solo tras
subirse con éxito, así que reintentar los que ya quedan no hace nada raro.
"""
import asyncio
import json
import logging
import os

from utils import api_client, cola_local

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reenviar_cola")


async def main():
    pendientes = cola_local.listar_pendientes()
    if not pendientes:
        print("Cola vacía -- nada pendiente de subir.")
        return

    print(f"{len(pendientes)} chequeo(s) pendientes de subir a KG.")
    subidos = fallidos = 0
    for ruta in pendientes:
        with open(ruta, encoding="utf-8") as f:
            payload = json.load(f)
        try:
            respuesta = await api_client.enviar_chequeo(payload["data"])
            url_captura = payload.get("url_captura")
            if url_captura and os.path.exists(url_captura):
                try:
                    await api_client.subir_captura(respuesta["chequeo_id"], url_captura)
                except Exception as exc:
                    logger.warning("  %s: dato subido pero falló la captura: %r", os.path.basename(ruta), exc)
            os.remove(ruta)
            subidos += 1
            logger.info("  subido: %s", payload["data"].get("direccion_id"))
        except Exception as exc:
            logger.warning("  sigue fallando %s: %r", os.path.basename(ruta), exc)
            fallidos += 1

    print(f"Subidos: {subidos}. Siguen pendientes: {fallidos}.")


if __name__ == "__main__":
    asyncio.run(main())
