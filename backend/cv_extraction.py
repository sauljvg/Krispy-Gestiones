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
# notas no salen de un CV, los pone el reclutador. formacion/experiencia se
# piden aparte como listas estructuradas (formacion_json/experiencia_json,
# ver _parsear_candidato_gemini) en vez de como texto plano.
EXTRACTION_FIELDS = [c for c in CAMPOS if c not in ("estado", "notas", "formacion", "experiencia")]

# Claves esperadas en cada entrada de formacion_json/experiencia_json -- si
# Gemini devuelve alguna con un valor que no sea texto (o directamente la
# omite), se descarta esa clave en vez de la entrada entera.
CLAVES_FORMACION = ("titulo", "centro", "fecha_inicio", "fecha_fin")
CLAVES_EXPERIENCIA = ("puesto", "empresa", "fecha_inicio", "fecha_fin", "descripcion")


class GeminiNoConfiguradoError(Exception):
    pass


class GeminiNoDisponibleError(Exception):
    pass


def _parsear_lista_estructurada(valor, claves) -> list[dict]:
    if not isinstance(valor, list):
        return []
    entradas = []
    for item in valor:
        if not isinstance(item, dict):
            continue
        entrada = {k: item[k] for k in claves if isinstance(item.get(k), str) and item[k].strip()}
        if entrada:
            entradas.append(entrada)
    return entradas


def _parsear_candidato_gemini(obj: dict) -> dict:
    extraido = {f: obj[f] for f in EXTRACTION_FIELDS if isinstance(obj.get(f), str) and obj[f].strip()}
    extraido["formacion_json"] = _parsear_lista_estructurada(obj.get("formacion_json"), CLAVES_FORMACION)
    extraido["experiencia_json"] = _parsear_lista_estructurada(obj.get("experiencia_json"), CLAVES_EXPERIENCIA)
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
        + ',\n    "formacion_json": [ { "titulo": "string", "centro": "string", "fecha_inicio": "string", "fecha_fin": "string" } ],\n'
        + '    "experiencia_json": [ { "puesto": "string", "empresa": "string", "fecha_inicio": "string", "fecha_fin": "string", "descripcion": "string" } ],\n'
        + '    "extra": { "nombre_del_campo": "valor" }\n  }\n]\n'
        "\"formacion_json\": UN OBJETO POR CADA formación reglada (grado, bachillerato, ESO, máster, curso...), "
        "en el mismo orden en que aparezcan en el CV (normalmente la más reciente primero). \"titulo\" es el "
        "nombre de la titulación, \"centro\" el nombre del centro/universidad, \"fecha_inicio\"/\"fecha_fin\" tal "
        "como aparezcan en el CV (p.ej. \"septiembre de 2020\", \"2023\"); si sigue en curso deja \"fecha_fin\" "
        "vacío o pon \"Actualmente\". Si no hay ninguna formación reglada, devuelve un array vacío.\n"
        "\"experiencia_json\": UN OBJETO POR CADA puesto de trabajo, en el mismo orden en que aparezcan (normalmente "
        "el más reciente primero). \"puesto\" es el cargo, \"empresa\" el nombre de la empresa, \"fecha_inicio\"/"
        "\"fecha_fin\" tal como aparezcan (vacío o \"Actualmente\" si sigue trabajando ahí), y \"descripcion\" un "
        "resumen breve de las tareas/funciones si el CV las detalla (vacío si no hay detalle). Si no hay ninguna "
        "experiencia laboral, devuelve un array vacío.\n"
        "Usa \"extra\" para cualquier dato relevante del CV que no encaje en los campos anteriores ni en "
        "formacion_json/experiencia_json. Muchos CVs vienen de portales de empleo (InfoJobs y similares) con "
        "secciones estructuradas -- captura estas SIEMPRE que aparezcan, cada una como un único campo de texto en "
        "\"extra\" (no las descartes ni las mezcles con los campos fijos de arriba):\n"
        "- \"Idiomas\": cada idioma con su nivel, separados por \" · \" (ej. \"Español: Nativo · Inglés: Intermedio\").\n"
        "- \"Conocimientos\": la lista de habilidades/etiquetas, separadas por \", \".\n"
        "- \"Situación laboral\": si está trabajando y si busca empleo activamente.\n"
        "- \"Preferencias laborales\": puesto(s) deseado(s), modalidad, provincia, tipo de contrato, jornada y "
        "salario mínimo, todo en una frase.\n"
        "- \"Disponibilidad para viajar\" y \"Disponibilidad para cambiar de residencia\": si aparecen como datos "
        "separados (aparte del campo general de disponibilidad).\n"
        "- \"Preguntas de selección\": si el documento trae un cuestionario tipo \"pregunta | puntuación | "
        "respuesta\" (AJENO a formación/experiencia -- normalmente son preguntas de la oferta, no del historial "
        "académico o laboral), únelas TODAS en un solo texto, una por línea con \" — \" entre pregunta, puntuación "
        "y respuesta (ej. \"¿Disponibilidad inmediata? — 10/10 — Sí, inmediata\"), y añade al final la nota total "
        "si aparece (ej. \"Nota: 50/50\"). Este bloque va SIEMPRE en \"extra\", nunca dentro de formacion_json ni "
        "experiencia_json.\n"
        "Además, cualquier otro dato suelto que no encaje en nada de lo anterior (carnet de conducir, si es "
        "autónomo, vehículo propio, redes sociales, certificaciones, etc.) también va en \"extra\", cada uno "
        "con su propia clave.\n"
        "No inventes datos que no aparezcan en el CV: si no encuentras un dato, deja el campo como cadena vacía "
        "o no lo incluyas en \"extra\". Si solo hay un candidato, devuelve igualmente un array con un único "
        "elemento."
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


# Muchos ATS (InfoJobs, Bizneo...) exportan cada candidato de una búsqueda
# con una línea "Nombre Apellido NN%" (el % de encaje con la vacante) justo
# debajo del encabezado de página, que además se REPITE IDÉNTICO en todas
# las páginas del PDF (es el título de la búsqueda, no el candidato). Buscar
# solo "líneas con palabras en mayúscula" confundía ese encabezado repetido,
# o el nombre de una empresa anterior en el CV, con el nombre real — esta
# marca es mucho más específica y fiable cuando aparece, así que se
# comprueba primero.
_MARCADOR_PORCENTAJE_RE = re.compile(r"^(.+?)\s+\d{1,3}\s*%\s*$")


def _nombre_por_marcador_porcentaje(lineas: list[str]) -> str:
    for linea in lineas[:10]:
        m = _MARCADOR_PORCENTAJE_RE.match(linea)
        if m:
            nombre = m.group(1).strip()
            if nombre and len(nombre) <= 60:
                return nombre
    return ""


def _adivinar_nombre(lineas: list[str]) -> str:
    nombre = _nombre_por_marcador_porcentaje(lineas)
    if nombre:
        return nombre
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


def _segmentar_paginas_por_candidato(reader) -> list[dict]:
    """Sin IA no hay forma fiable de "entender" dónde termina un CV y
    empieza el siguiente en un PDF por lotes. Primero se comprueba si el
    documento entero usa la marca "Nombre NN%" de exportaciones de ATS (ver
    _nombre_por_marcador_porcentaje) en varias páginas — si es así, se usa
    ESA marca en exclusiva para decidir dónde empieza cada candidato: mezclarla
    con la heurística genérica de "línea con mayúsculas" da falsos positivos
    con nombres de empresas anteriores dentro del propio CV de un candidato
    (p.ej. un CV de varias páginas con un largo historial laboral). Solo si
    el documento NO trae esa marca en ninguna página se usa la heurística
    genérica como respaldo (para PDFs de un único CV suelto, sin esa marca)."""
    textos_paginas = [page.extract_text() or "" for page in reader.pages]
    primeras_lineas_por_pagina = [
        [l.strip() for l in texto.split("\n") if l.strip()][:10] for texto in textos_paginas
    ]
    marcadores_por_pagina = [_nombre_por_marcador_porcentaje(lineas) for lineas in primeras_lineas_por_pagina]
    usar_solo_marcador = sum(1 for m in marcadores_por_pagina if m) >= 2

    segmentos = []
    actual = []
    actual_inicio = 0
    for i, (texto_pagina, lineas, marcador) in enumerate(zip(textos_paginas, primeras_lineas_por_pagina, marcadores_por_pagina)):
        es_candidato_nuevo = bool(marcador) if usar_solo_marcador else bool(_adivinar_nombre(lineas[:8]))
        if es_candidato_nuevo and actual:
            # Páginas 1-indexadas (para hablar con el usuario, no con el
            # propio pypdf) -- pagina_fin es la última página INCLUIDA.
            segmentos.append({"texto": "\n".join(actual), "pagina_inicio": actual_inicio + 1, "pagina_fin": i})
            actual = [texto_pagina]
            actual_inicio = i
        else:
            actual.append(texto_pagina)
    if actual:
        segmentos.append({"texto": "\n".join(actual), "pagina_inicio": actual_inicio + 1, "pagina_fin": len(textos_paginas)})
    return segmentos


def extraer_foto(pdf_bytes: bytes) -> tuple[bytes, str] | None:
    """Busca una foto de candidato en la PRIMERA página del PDF -- los CVs de
    portales de empleo (InfoJobs, LinkedIn...) casi siempre la ponen ahí. Se
    queda con la imagen más grande que tenga proporciones de retrato
    razonables (ni una franja apaisada tipo banner, ni rarísima) -- no es
    infalible (podría coger un logo grande en vez de la cara), pero evita
    los casos más obvios de foto equivocada. Solo tiene sentido llamarla
    cuando el PDF trae UN SOLO candidato (ver extraer_cv) -- en un PDF por
    lotes no hay forma fiable de saber de qué página es la foto de quién."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return None
        mejor = None
        mejor_area = 0
        for img in reader.pages[0].images:
            try:
                ancho, alto = img.image.size
            except Exception:
                continue
            if ancho < 80 or alto < 80:
                continue
            ratio = ancho / alto
            if ratio < 0.55 or ratio > 1.8:
                continue
            area = ancho * alto
            if area > mejor_area:
                ext = os.path.splitext(img.name)[1].lower() or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png"):
                    ext = ".jpg"
                mejor_area = area
                mejor = (img.data, ext)
        return mejor
    except Exception:
        return None


def _extraer_local(pdf_bytes: bytes) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    segmentos = _segmentar_paginas_por_candidato(reader)
    return [_extraer_de_texto(seg["texto"]) for seg in segmentos]


def detectar_paginas_por_candidato(pdf_bytes: bytes) -> list[tuple[int, int]]:
    """Rangos de página (1-indexado, ambos extremos incluidos) de cada
    candidato detectado en un PDF por lotes -- usa la misma heurística de
    segmentación que el extractor local (ver _segmentar_paginas_por_candidato)
    sin importar si el nombre/campos de cada uno se sacaron con Gemini o en
    local, para poder recortar el PDF físicamente y adjuntar a cada ficha
    solo sus páginas (ver /candidatos/adjuntar-pdf-lote)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    segmentos = _segmentar_paginas_por_candidato(reader)
    return [(s["pagina_inicio"], s["pagina_fin"]) for s in segmentos]


def recortar_pdf(pdf_bytes: bytes, pagina_inicio: int, pagina_fin: int) -> bytes:
    """Extrae un rango de páginas (1-indexado, ambos extremos incluidos) del
    PDF como un PDF nuevo e independiente -- usado para separar el CV de un
    candidato concreto dentro de un PDF por lotes en vez de adjuntarle el
    lote entero (ver /candidatos/adjuntar-pdf-lote/confirmar)."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for pagina in reader.pages[pagina_inicio - 1:pagina_fin]:
        writer.add_page(pagina)
    salida = io.BytesIO()
    writer.write(salida)
    return salida.getvalue()


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
