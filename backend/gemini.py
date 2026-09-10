"""Cliente mínimo de Gemini, compartido por David (david.py) y la sugerencia
de variantes de nombre en Reseñas (personal.py).

Centraliza dos cosas:
- El modelo, en la variable de entorno GEMINI_MODEL (por defecto
  "gemini-3.5-flash"). Cambiarla NO necesita tocar código ni redeploy de
  imagen, solo reiniciar el servicio.
- Que un modelo mal configurado o una llamada lenta no rompan la función.
  Se prueban varias combinaciones en orden; se pasa a la siguiente si la
  respuesta es un 400 ("INVALID_ARGUMENT", típico de un campo que ese
  modelo no admite) o si la petición falla por red/timeout. El último
  intento es siempre el modelo por defecto, que sabemos bueno. Cualquier
  otro error (401/403/429/5xx) se devuelve tal cual: reintentar no ayuda.
"""
import os

import requests

MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MODELO_FALLBACK = "gemini-3.5-flash"
_TIMEOUT = 30
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


class GeminiError(Exception):
    pass


def _piensa(modelo: str) -> bool:
    """Los modelos "lite" no razonan por defecto y además llegaron a
    atascarse / rechazar el campo thinkingConfig -- a esos no se lo
    mandamos. Al resto sí, con thinkingBudget=0, para que no gasten parte
    de maxOutputTokens pensando y corten la respuesta a media frase."""
    return "lite" not in modelo.lower()


def generar(contents, *, system_instruction=None, temperature=0.3, max_output_tokens=1024):
    """Llama a generateContent y devuelve el JSON de respuesta (con la clave
    "candidates"). `contents` es la lista de turnos tal cual la espera la
    API. Lanza GeminiError si ningún intento devuelve un 200."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("Falta configurar GEMINI_API_KEY en el entorno del servidor")

    body_base = {"contents": contents}
    if system_instruction:
        body_base["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    # (modelo, incluir thinkingConfig), en orden de preferencia.
    intentos = [(MODELO, _piensa(MODELO))]
    if _piensa(MODELO):
        # Por si el modelo tiene nombre válido pero rechaza thinkingConfig.
        intentos.append((MODELO, False))
    if MODELO != MODELO_FALLBACK:
        intentos.append((MODELO_FALLBACK, _piensa(MODELO_FALLBACK)))

    ultimo_error = "Gemini no respondió"
    for modelo, con_thinking in intentos:
        generation_config = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        if con_thinking:
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
            # Timeout / corte de red: transitorio. Probar el siguiente
            # intento (que además suele ser el modelo de reserva).
            ultimo_error = f"No se pudo contactar con Gemini: {exc}"
            continue
        if resp.status_code == 200:
            return resp.json()
        ultimo_error = f"Gemini devolvió un error ({resp.status_code}): {resp.text[:300]}"
        if resp.status_code != 400:
            break  # 401/403/429/5xx: reintentar no ayuda

    raise GeminiError(ultimo_error)
