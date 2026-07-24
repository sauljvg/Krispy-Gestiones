import base64
import io
import json
import os
import re
import unicodedata

import requests

from reclutamiento import CAMPOS

GEMINI_MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Campos que tiene sentido pedirle a la IA que extraiga de un CV — estado y
# notas no salen de un CV, los pone el reclutador.
EXTRACTION_FIELDS = [c for c in CAMPOS if c not in ("estado", "notas")]


class GeminiNoConfiguradoError(Exception):
    pass


class GeminiNoDisponibleError(Exception):
    pass


def _parsear_candidato_gemini(obj: dict) -> dict:
    extraido = {f: obj[f] for f in EXTRACTION_FIELDS if isinstance(obj.get(f), str) and obj[f].strip()}
    extra = {}
    if isinstance(obj.get("extra"), dict):
        for k, v in obj["extra"].items():
            if isinstance(v, str) and v.strip():
                extra[k] = v
    extraido["extra_fields"] = extra
    return extraido


def _extraer_con_gemini(pdf_bytes: bytes) -> list[dict]:
    """Pide a Gemini la lista de candidatos del PDF — puede ser un único CV o
    un PDF por lotes con varios CVs concatenados (hasta ~50), muy habitual
    cuando alguien junta varios currículums en un solo archivo antes de
    enviarlos. Siempre se pide un array, aunque solo haya un candidato, para
    no tener dos formatos de respuesta distintos que mantener."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiNoConfiguradoError(
            "No hay ninguna GEMINI_API_KEY configurada. Añádela como variable de entorno para activar la extracción por IA."
        )

    prompt = (
        "Eres un asistente de RRHH. Este PDF puede contener el CV de UN SOLO candidato o "
        "varios CVs de candidatos distintos concatenados en el mismo archivo (por ejemplo, "
        "hasta 50 currículums juntados en un solo PDF por lotes). Identifica cada candidato "
        "distinto que aparezca en el documento y extrae sus datos por separado.\n"
        "Devuelve SOLO un JSON: un array con un objeto por cada candidato encontrado, con esta forma exacta:\n"
        "[\n  {\n"
        + ",\n".join(f'    "{f}": "string o vacío"' for f in EXTRACTION_FIELDS)
        + ',\n    "extra": { "nombre_del_campo": "valor" }\n  }\n]\n'
        "Usa \"extra\" para cualquier dato relevante del CV que no encaje en los campos anteriores "
        "(idiomas, carnet de conducir, vehículo propio, redes sociales, certificaciones, etc.). "
        "No inventes datos que no aparezcan en el CV: si no encuentras un dato, deja el campo como cadena vacía. "
        "Si solo hay un candidato, devuelve igualmente un array con un único elemento."
    )

    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode("ascii")}},
                {"text": prompt},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    try:
        resp = requests.post(GEMINI_URL, params={"key": api_key}, json=body, timeout=90)
    except requests.RequestException as exc:
        raise GeminiNoDisponibleError(f"No se pudo contactar con Gemini: {exc}")

    if resp.status_code == 503:
        raise GeminiNoDisponibleError("Google Gemini está saturado ahora mismo (capa gratuita). Inténtalo de nuevo en unos minutos.")
    if resp.status_code == 429:
        raise GeminiNoDisponibleError("Se ha alcanzado el límite de uso gratuito de Gemini por ahora. Inténtalo de nuevo en unos minutos.")
    if resp.status_code != 200:
        raise GeminiNoDisponibleError(f"Gemini devolvió un error ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    try:
        texto = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(texto)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiNoDisponibleError(f"La IA no devolvió un JSON válido al leer el CV: {exc}")

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not parsed:
        raise GeminiNoDisponibleError("La IA no devolvió ningún candidato reconocible en el PDF")

    return [_parsear_candidato_gemini(obj) for obj in parsed if isinstance(obj, dict)]


# --- Extracción local (sin IA), puerto de localCvExtraction.ts ---

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+34[\s.-]?)?\b[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b")
DNI_RE = re.compile(r"\b(\d{8}[A-Za-z]|[XYZxyz]\d{7}[A-Za-z])\b")
DATE_RE = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b|\b\d{1,2}\s+de\s+[a-zA-Zé]+\s+de\s+\d{4}\b", re.IGNORECASE)
PAGE_MARKER_RE = re.compile(r"--\s*\d+\s*of\s*\d+\s*--", re.IGNORECASE)

SECTIONS = [
    ("experiencia", ["experiencia laboral", "experiencia profesional", "experiencia"], False),
    ("formacion", ["formación académica", "formacion academica", "formación", "formacion", "estudios", "educación", "educacion"], False),
    ("disponibilidad", ["disponibilidad"], False),
    ("direccion", ["dirección", "direccion", "domicilio"], True),
]

EXTRA_KEYWORDS = [
    ("Idiomas", ["idiomas"], True),
    ("Carnet de conducir", ["carnet de conducir", "carné de conducir"], True),
    ("Vehículo propio", ["vehículo propio", "vehiculo propio"], True),
    ("Certificaciones", ["certificaciones", "certificados"], True),
]

ALL_HEADER_KEYWORDS = [kw for _, kws, _ in SECTIONS for kw in kws] + [kw for _, kws, _ in EXTRA_KEYWORDS for kw in kws]


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def _adivinar_nombre(lineas: list[str]) -> str:
    patron = re.compile(r"^[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'-]*(\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'-]*){1,3}$")
    for linea in lineas[:8]:
        if patron.match(linea):
            return linea
    return ""


def _buscar_cerca(texto: str, keywords: list[str], patron: re.Pattern) -> str:
    texto_norm = _normalizar(texto)
    for kw in keywords:
        idx = texto_norm.find(_normalizar(kw))
        if idx == -1:
            continue
        ventana = texto[idx:idx + len(kw) + 120]
        match = patron.search(ventana)
        if match:
            return match.group(0)
    return ""


def _contenido_de_seccion(texto: str, keywords: list[str], una_linea: bool) -> str:
    texto_norm = _normalizar(texto)
    for kw in keywords:
        idx = texto_norm.find(_normalizar(kw))
        if idx == -1:
            continue
        inicio = idx + len(kw)
        fin = len(texto)
        for otra_kw in ALL_HEADER_KEYWORDS:
            if otra_kw in keywords:
                continue
            otra_idx = texto_norm.find(_normalizar(otra_kw), inicio)
            if otra_idx != -1 and otra_idx < fin:
                fin = otra_idx
        contenido = texto[inicio:min(fin, inicio + 400)]
        contenido = re.sub(r"^[:\s]+", "", contenido)
        if una_linea:
            nl = contenido.find("\n")
            if nl != -1:
                contenido = contenido[:nl]
        contenido = contenido.strip()
        if contenido:
            return contenido
    return ""


def _extraer_de_texto(texto_crudo: str) -> dict:
    texto = PAGE_MARKER_RE.sub("", texto_crudo)
    lineas = [l.strip() for l in re.split(r"\r?\n", texto) if l.strip()]

    extraido = {}
    extra = {}

    nombre = _adivinar_nombre(lineas)
    if nombre:
        extraido["nombre_completo"] = nombre

    email_match = EMAIL_RE.search(texto)
    if email_match:
        extraido["email"] = email_match.group(0)

    phone_match = PHONE_RE.search(texto)
    if phone_match:
        extraido["telefono"] = re.sub(r"[\s.-]", "", phone_match.group(0))

    dni_match = DNI_RE.search(texto)
    if dni_match:
        extraido["dni"] = dni_match.group(0).upper()

    nacimiento = _buscar_cerca(texto, ["nacimiento", "nacido", "fecha de nacimiento"], DATE_RE)
    if nacimiento:
        extraido["fecha_nacimiento"] = nacimiento

    for campo, keywords, una_linea in SECTIONS:
        contenido = _contenido_de_seccion(texto, keywords, una_linea)
        if contenido:
            extraido[campo] = contenido

    for nombre_extra, keywords, una_linea in EXTRA_KEYWORDS:
        contenido = _contenido_de_seccion(texto, keywords, una_linea)
        if contenido:
            extra[nombre_extra] = contenido[:200]

    extraido["extra_fields"] = extra
    return extraido


def _segmentar_paginas_por_candidato(reader) -> list[str]:
    """Sin IA no hay forma fiable de "entender" dónde termina un CV y
    empieza el siguiente en un PDF por lotes — se usa una heurística simple:
    cada página cuyas primeras líneas parecen un nombre propio (misma
    heurística que _adivinar_nombre) se trata como el inicio de un candidato
    nuevo; las páginas siguientes que NO empiecen con un nombre se asumen
    continuación del candidato anterior (un CV de 2 páginas, por ejemplo)."""
    segmentos = []
    actual = []
    for page in reader.pages:
        texto_pagina = page.extract_text() or ""
        primeras_lineas = [l.strip() for l in texto_pagina.split("\n") if l.strip()][:8]
        es_candidato_nuevo = bool(_adivinar_nombre(primeras_lineas))
        if es_candidato_nuevo and actual:
            segmentos.append("\n".join(actual))
            actual = [texto_pagina]
        else:
            actual.append(texto_pagina)
    if actual:
        segmentos.append("\n".join(actual))
    return segmentos


def _extraer_local(pdf_bytes: bytes) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    segmentos = _segmentar_paginas_por_candidato(reader)
    return [_extraer_de_texto(seg) for seg in segmentos]


def extraer_cv(pdf_bytes: bytes) -> tuple[list[dict], str]:
    """Intenta Gemini si hay API key configurada; si falla o no hay key, cae
    al método local sin IA. El PDF puede traer un único candidato o varios
    (hasta ~50) concatenados en el mismo archivo — se devuelve SIEMPRE una
    lista, de un elemento cuando es un solo candidato. Devuelve
    (lista_de_candidatos, metodo)."""
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _extraer_con_gemini(pdf_bytes), "gemini"
        except (GeminiNoConfiguradoError, GeminiNoDisponibleError):
            pass
    return _extraer_local(pdf_bytes), "local"
