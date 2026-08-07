"""Fallback de último recurso: cuando los selectores deterministas fallan,
se pide a un modelo con visión que localice el elemento en un screenshot y
se hace click en esas coordenadas. Se invoca SOLO tras agotar los intentos
normales de cada scraper (ver scrapers/justeat.py y scrapers/glovo.py).

Usa Haiku en vez de un modelo más capaz porque la tarea (encontrar
coordenadas de un elemento visible) es simple y de bajo riesgo, y el coste
por intento debe mantenerse mínimo (uso esporádico, en background).
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_LOG = Path(__file__).resolve().parent.parent / "logs" / "ia_uso.jsonl"

_MODELO_IA = "claude-haiku-4-5"


def _cliente():
    try:
        import anthropic
    except ImportError:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _registrar_uso(
    agregador: str,
    descripcion: str,
    exito: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: str = None,
):
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        registro = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agregador": agregador,
            "descripcion": descripcion,
            "exito": exito,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "error": error,
        }
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("No se pudo registrar uso de IA", exc_info=True)


async def click_con_ia(page, descripcion: str, agregador: str) -> bool:
    """Intenta localizar y hacer click en el elemento descrito usando visión.

    Devuelve True si se hizo click, False si la IA no está disponible, no
    encontró el elemento, o falló por cualquier motivo (nunca lanza).
    """
    cliente = _cliente()
    if cliente is None:
        logger.info("IA fallback no disponible (falta ANTHROPIC_API_KEY o paquete anthropic)")
        return False

    try:
        captura = await page.screenshot()
    except Exception as exc:
        _registrar_uso(agregador, descripcion, exito=False, error=f"screenshot: {exc}")
        return False

    imagen_b64 = base64.standard_b64encode(captura).decode("utf-8")

    try:
        respuesta = cliente.messages.create(
            model=_MODELO_IA,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": imagen_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Esta es una captura de una página web de un agregador de "
                                f"delivery ({agregador}). Necesito hacer click en: {descripcion}. "
                                f'Responde ÚNICAMENTE con un JSON de una línea: '
                                f'{{"found": true, "x": <int>, "y": <int>}} si lo encuentras '
                                f"(coordenadas en píxeles de la imagen, origen arriba-izquierda), "
                                f'o {{"found": false}} si no está visible. Sin texto adicional.'
                            ),
                        },
                    ],
                }
            ],
        )
        texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
        if texto.startswith("```"):
            texto = texto.strip("`")
            if texto.startswith("json"):
                texto = texto[4:]
            texto = texto.strip()
        datos = json.loads(texto)

        _registrar_uso(
            agregador,
            descripcion,
            exito=bool(datos.get("found")),
            input_tokens=getattr(respuesta.usage, "input_tokens", 0),
            output_tokens=getattr(respuesta.usage, "output_tokens", 0),
        )

        if not datos.get("found"):
            return False

        await page.mouse.click(datos["x"], datos["y"])
        return True
    except Exception as exc:
        logger.warning("IA fallback falló para '%s' en %s: %s", descripcion, agregador, exc)
        _registrar_uso(agregador, descripcion, exito=False, error=str(exc))
        return False
