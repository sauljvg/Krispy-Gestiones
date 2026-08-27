"""Cola de reintento local para chequeos que no se pudieron subir a KG (27/08:
pedido explícito del usuario tras confirmar que la caída del servidor -- ver
db.py, disk I/O error bajo carga -- perdía datos ya scrapeados de verdad).

El scraper corre en local: cuando ya tenemos el resultado real (disponible/no
disponible/tiempo de entrega), NUNCA debe perderse solo porque el backend esté
caído en ese instante -- se guarda aquí en disco y se reenvía después con
reenviar_cola.py, sin volver a scrapear nada."""
import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

COLA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cola_pendiente")


def encolar(data: dict, url_captura: str | None = None) -> str:
    """Guarda un chequeo que falló al subirse, para reenviar más tarde. `data` es
    exactamente el dict que se le habría pasado a api_client.enviar_chequeo."""
    os.makedirs(COLA_DIR, exist_ok=True)
    payload = {"data": data, "url_captura": url_captura, "encolado_en": time.time()}
    ruta = os.path.join(COLA_DIR, f"{uuid.uuid4().hex}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    logger.warning("  encolado en local (%s) -- se reenviará con reenviar_cola.py", os.path.basename(ruta))
    return ruta


def listar_pendientes() -> list[str]:
    if not os.path.isdir(COLA_DIR):
        return []
    return sorted(
        os.path.join(COLA_DIR, nombre) for nombre in os.listdir(COLA_DIR) if nombre.endswith(".json")
    )
