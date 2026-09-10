"""Cliente mínimo de Gemini, compartido por David (david.py) y la sugerencia
de variantes de nombre en Reseñas (personal.py).

Centraliza dos cosas:
- El modelo, en la variable de entorno GEMINI_MODEL (por defecto
  "gemini-3.5-flash"). Cambiarla NO necesita tocar código ni redeploy de
  imagen, solo reiniciar el servicio.
- Que un modelo mal configurado no rompa la función. Si la petición vuelve
  con 400 ("INVALID_ARGUMENT") se reintenta:
    1. sin "thinkingConfig" (no todos los modelos aceptan ese campo), y
    2. como último recurso, con el modelo por defecto que sabemos bueno.
  Cualquier otro error (401/403/429/5xx) se devuelve tal cual: reintentar
  no ayudaría.
"""
import os

import requests

MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MODELO_FALLBACK = "gemini-3.5-flash"
_TIMEOUT = 20
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


class GeminiError(Exception):
    pass


def generar(contents, *, system_instruction=None, temperature=0.3, max_output_tokens=1024):
    """Llama a generateContent y devuelve el JSON de respuesta (con la clave
    "candidates"). `contents` es la lista de turnos tal cual la espera la
    API. Lanza GeminiError si no hay forma de obtener un 200."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("Falta configurar GEMINI_API_KEY en el entorno del servidor")

    body_base = {"contents": contents}
    if system_instruction:
        body_base["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    # (modelo, incluir thinkingConfig). El orden es el de preferencia:
    #   1. el modelo configurado, tal cual;
    #   2. el mismo modelo pero sin thinkingConfig (algún modelo lo rechaza);
    #   3. el modelo por defecto, en su configuración buena conocida.
    intentos = [(MODELO, True), (MODELO, False)]
    if MODELO != MODELO_FALLBACK:
        intentos.append((MODELO_FALLBACK, True))

    resp = None
    for modelo, con_thinking in intentos:
        generation_config = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        if con_thinking:
            # thinkingBudget=0 desactiva el "razonamiento" interno del modelo.
            # Sin esto, los modelos que piensan gastan parte de
            # maxOutputTokens razonando y la respuesta visible se corta a
            # media frase. Para explicar botones del portal no hace falta.
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {**body_base, "generationConfig": generation_config}
        try:
            resp = requests.post(
                _ENDPOINT.format(modelo=modelo),
                params={"key": api_key},
                json=payload,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GeminiError(f"No se pudo contactar con Gemini: {exc}") from exc
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code != 400:
            break

    detalle = resp.text[:300] if resp is not None else "sin respuesta"
    codigo = resp.status_code if resp is not None else "?"
    raise GeminiError(f"Gemini devolvió un error ({codigo}): {detalle}")
