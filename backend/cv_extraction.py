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


class GeminiLimiteTemporalError(GeminiNoDisponibleError):
    """429 por límite de peticiones/minuto (RPM), a diferencia de un 429 por
    cupo diario agotado -- este se libera solo con esperar unos segundos, así
    que merece la pena reintentar en vez de rendirse con Gemini para el resto
    del lote (ver retry_after_segundos y _rellenar_huecos_en_segundo_plano en
    reclutamiento_routes.py)."""

    def __init__(self, mensaje, retry_after_segundos):
        super().__init__(mensaje)
        self.retry_after_segundos = retry_after_segundos


def _extraer_retry_delay(resp) -> int | None:
    """Cuando Gemini devuelve 429, suele incluir en el propio cuerpo del
    error cuánto esperar antes de reintentar (RetryInfo.retryDelay, p.ej.
    "18s") -- mucho más fiable que adivinar un tiempo de espera fijo, y es la
    señal de que el 429 es por RPM (temporal) y no por cupo diario agotado."""
    try:
        detalles = resp.json().get("error", {}).get("details", [])
    except Exception:
        return None
    for d in detalles:
        if str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.match(r"(\d+(?:\.\d+)?)s?$", str(d.get("retryDelay", "")).strip())
            if m:
                return int(float(m.group(1))) + 1
    return None


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


def extraer_con_gemini(pdf_bytes: bytes) -> list[dict]:
    """Pide a Gemini la lista de candidatos del PDF — puede ser un único CV o
    un PDF por lotes con varios CVs concatenados (hasta ~50), muy habitual
    cuando alguien junta varios currículums en un solo archivo antes de
    enviarlos. Siempre se pide un array, aunque solo haya un candidato, para
    no tener dos formatos de respuesta distintos que mantener.

    Pública (a diferencia del resto de _funciones de este módulo) porque
    reclutamiento_routes.py la llama directamente cuando quiere manejar sus
    propios reintentos con espera (ver GeminiLimiteTemporalError) en vez de
    caer automáticamente al método local en el primer fallo, que es lo que
    hace extraer_cv() más abajo."""
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
        "- Si el documento trae un cuestionario tipo \"pregunta | puntuación | respuesta\" (AJENO a formación/"
        "experiencia -- normalmente son preguntas de la oferta, no del historial académico o laboral), NO lo "
        "juntes en un solo bloque de texto: añade CADA PREGUNTA como su propia clave dentro de \"extra\", usando "
        "el texto de la pregunta tal cual como clave (recórtalo a unos 80 caracteres si es muy largo) y "
        "\"Puntuación: X — respuesta\" como valor (ej. clave \"¿Disponibilidad inmediata para trabajar?\", valor "
        "\"Puntuación: 10 — Sí, inmediata\"). Si aparece una nota total del cuestionario, añádela aparte con "
        "clave \"Nota del cuestionario\" (ej. \"45/50\"). Estas preguntas van SIEMPRE en \"extra\", nunca dentro "
        "de formacion_json ni experiencia_json.\n"
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
        # 25s en vez de 90s -- con Gemini saturado, encadenar muchas llamadas
        # (p.ej. al re-extraer un lote de 37 personas) a 90s cada una podía
        # bloquear el proceso durante casi una hora y tumbar el resto del
        # sitio para todo el mundo (ver adjuntar_pdf_lote_confirmar_route).
        resp = requests.post(GEMINI_URL, params={"key": api_key}, json=body, timeout=25)
    except requests.RequestException as exc:
        raise GeminiNoDisponibleError(f"No se pudo contactar con Gemini: {exc}")

    if resp.status_code == 503:
        raise GeminiNoDisponibleError("Google Gemini está saturado ahora mismo (capa gratuita). Inténtalo de nuevo en unos minutos.")
    if resp.status_code == 429:
        reintento_en = _extraer_retry_delay(resp)
        # Si Google indica un retryDelay corto es el límite de peticiones
        # POR MINUTO (se libera solo con esperar); sin ese dato, o con un
        # valor largo, se trata como cupo DIARIO agotado (no vale la pena
        # reintentar en la misma tanda) -- ver GeminiLimiteTemporalError.
        if reintento_en is not None and reintento_en <= 90:
            raise GeminiLimiteTemporalError(
                f"Límite de peticiones por minuto de Gemini alcanzado, reintentando en {reintento_en}s.",
                reintento_en,
            )
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

# El ATS repite, en cada salto de página, un pie/cabecera de página tipo
# "N/M" (visto como "37/10" en un CV exportado desde nuestra propia
# herramienta y como "1/4" -- página 1 de 4 -- en uno descargado directo de
# InfoJobs, así que el significado exacto de N/M varía según el origen)
# seguido del nombre de la vacante a la que se apuntó (p.ej. "Dependiente/a
# Krispy Kreme"). No es contenido del CV -- es texto que pdfplumber intercala
# igual que el resto, allí donde caiga el salto de página (a veces a media
# línea de contenido real, otras veces en su propia línea). Como los números
# cambian en cada página no sirve detectarlos por repetición; se reconoce por
# el patrón "N/M" (ambos números cortos -- así no coincide con una fecha tipo
# "01/2020", con año de 4 cifras) seguido de un salto de línea, y se descarta
# también esa línea siguiente entera (el nombre de la vacante), sea cual sea
# su contenido -- así no hace falta conocer de antemano el nombre de la
# vacante para reconocerlo.
PIE_PAGINA_VACANTE_RE = re.compile(r"[ \t]*\d{1,3}\s*/\s*\d{1,3}[ \t]*\n[^\n]*\n?")

SECTIONS = [
    ("experiencia", ["experiencia laboral", "experiencia profesional", "experiencia"], False),
    ("formacion", ["formación académica", "formacion academica", "formación", "formacion", "estudios", "educación", "educacion"], False),
    ("disponibilidad", ["disponibilidad"], False),
    ("direccion", ["dirección", "direccion", "domicilio"], True),
]

EXTRA_KEYWORDS = [
    # Idiomas casi siempre ocupa más de una línea (un idioma por línea, o
    # dos por línea) -- una_linea=False dejar coger todo el bloque hasta la
    # siguiente cabecera (p.ej. Conocimientos) en vez de cortar en la
    # primera línea y perder los demás idiomas.
    ("Idiomas", ["idiomas"], False),
    ("Carnet de conducir", ["carnet de conducir", "carné de conducir"], True),
    ("Vehículo propio", ["vehículo propio", "vehiculo propio"], True),
    ("Autónomo", ["autónomo", "autonomo"], True),
    ("Certificaciones", ["certificaciones", "certificados"], True),
]

# Cabeceras de sección que SÍ aparecen en los PDF de ATS (InfoJobs, Bizneo...)
# pero que no se extraen como campo propio -- solo sirven de "muro" para que
# _contenido_de_seccion sepa dónde para el contenido de otra sección. Sin
# esto, "Idiomas" (una_linea=True, ver EXTRA_KEYWORDS) podía comerse el
# título de la sección siguiente como si fuera su valor (p.ej. quedaba
# "Idiomas: Conocimientos" en vez de la lista real de idiomas) cuando el
# orden del texto que saca pypdf del PDF no coincide con el orden visual
# (habitual en diseños de columnas/chips como los de InfoJobs).
BOUNDARY_ONLY_KEYWORDS = [
    "conocimientos", "preferencias laborales", "puestos deseados", "modalidad",
    "provincia deseada", "jornada", "preguntas de selección", "preguntas de seleccion",
    "nota del cuestionario",
]

ALL_HEADER_KEYWORDS = (
    [kw for _, kws, _ in SECTIONS for kw in kws]
    + [kw for _, kws, _ in EXTRA_KEYWORDS for kw in kws]
    + BOUNDARY_ONLY_KEYWORDS
)


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


def _pagina_parece_inicio_de_candidato(lineas: list[str]) -> bool:
    """Usado SOLO para decidir si una página (sin marcador "NN%") empieza un
    candidato nuevo dentro de un PDF por lotes -- a diferencia de
    _adivinar_nombre a secas (que solo mira si hay una línea con pinta de
    nombre propio), aquí además se exige un email o teléfono cerca, que es
    como de verdad se ve el principio de un CV. Sin este segundo requisito,
    el nombre de una empresa o de un curso en una página de CONTINUACIÓN del
    mismo candidato (p.ej. "Muy Mucho", "Máster Comunicación") también
    parece "una línea con mayúsculas" y se confundía con un candidato
    nuevo, partiendo el CV de una sola persona en varios "candidatos" falsos."""
    if not _adivinar_nombre(lineas):
        return False
    inicio = "\n".join(lineas)
    return bool(EMAIL_RE.search(inicio) or PHONE_RE.search(inicio))


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


def _indice_de_cabecera(texto_norm: str, kw_norm: str, desde: int = 0) -> int:
    """Solo cuenta la aparición de kw que empieza una línea (así es como se
    ve de verdad una cabecera de sección en el PDF) Y que además ocupa (casi)
    toda esa línea -- una aparición a media frase NO cuenta, ni siquiera a
    falta de otra cosa: por ejemplo "certificaciones" dentro de "Otros
    títulos, certificaciones y carnés" (el título de OTRA sección), o
    "formación" dentro de una pregunta de selección tipo "La formación son 2
    semanas..." (que no tiene nada que ver con la sección Formación/
    Estudios). El segundo requisito (ocupar casi toda la línea) hace falta
    porque una etiqueta de habilidad como "Formación de personal" (dentro de
    una nube de etiquetas de Experiencia) SÍ puede caer justo al principio
    de su propia línea y aun así no ser la cabecera real -- una cabecera de
    verdad es corta y sola ("Idiomas") o, como mucho, con un valor corto
    detrás de dos puntos ("Carnet de conducir: B"), nunca sigue en
    minúsculas como una frase. Devolver -1 en vez de conformarse con esa
    aparición deja que el llamador siga probando el resto de sinónimos de
    la lista (ver SECTIONS/EXTRA_KEYWORDS) en vez de quedarse con contenido
    de otra parte del CV que no tiene nada que ver. También se usa para
    encontrar dónde ACABA una sección (buscando la cabecera de la
    siguiente) -- ahí importa todavía más: "Formación de personal" es una
    etiqueta de habilidad dentro de Experiencia, no una cabecera real, y sin
    esta misma exigencia cortaba la sección de Experiencia por la mitad."""
    pos = desde
    while True:
        idx = texto_norm.find(kw_norm, pos)
        if idx == -1:
            return -1
        empieza_linea = idx == 0 or texto_norm[idx - 1] == "\n"
        fin_kw = idx + len(kw_norm)
        resto_linea = texto_norm[fin_kw:texto_norm.find("\n", fin_kw) if texto_norm.find("\n", fin_kw) != -1 else len(texto_norm)]
        ocupa_la_linea = resto_linea.strip() == "" or resto_linea.lstrip().startswith(":")
        if empieza_linea and ocupa_la_linea:
            return idx
        pos = idx + 1


def _separar_cabeceras_pegadas(texto: str) -> str:
    """Varios "chips" de datos cortos a veces quedan en la MISMA línea del
    PDF -- p.ej. "Carnet de conducir: B Autónomo: No Vehículo propio: No" --
    y _indice_de_cabecera exige que cada cabecera empiece línea (para no
    confundirla con una mención a media frase, ver su docstring). En vez de
    relajar esa exigencia, aquí se inserta un salto de línea delante de cada
    cabecera reconocida que no lo tenga ya, para que las tres cuenten igual.

    Para no reintroducir el problema que _indice_de_cabecera evita
    (confundir "certificaciones" dentro de "...títulos, certificaciones y
    carnés", o "formación" dentro de "La formación son 2 semanas...", con
    una cabecera de verdad), solo se separa cuando la letra encontrada está
    en MAYÚSCULA en el texto original -- un chip de verdad siempre empieza
    con mayúscula ("Autónomo", "Vehículo propio"); una mención de paso
    dentro de una frase, no."""
    texto_norm = _normalizar(texto)
    posiciones = set()
    for kw in ALL_HEADER_KEYWORDS:
        kw_norm = _normalizar(kw)
        pos = 0
        while True:
            idx = texto_norm.find(kw_norm, pos)
            if idx == -1:
                break
            precedido_por_espacio = idx > 0 and texto[idx - 1] in " \t"
            if precedido_por_espacio and texto[idx].isupper():
                posiciones.add(idx)
            pos = idx + 1
    if not posiciones:
        return texto
    partes = []
    anterior = 0
    for idx in sorted(posiciones):
        partes.append(texto[anterior:idx])
        partes.append("\n")
        anterior = idx
    partes.append(texto[anterior:])
    return "".join(partes)


def _contenido_de_seccion(texto: str, keywords: list[str], una_linea: bool, limite_max: int = 400) -> str:
    texto_norm = _normalizar(texto)
    for kw in keywords:
        idx = _indice_de_cabecera(texto_norm, _normalizar(kw))
        if idx == -1:
            continue
        inicio = idx + len(kw)
        fin = len(texto)
        for otra_kw in ALL_HEADER_KEYWORDS:
            if otra_kw in keywords:
                continue
            otra_idx = _indice_de_cabecera(texto_norm, _normalizar(otra_kw), inicio)
            if otra_idx != -1 and otra_idx < fin:
                fin = otra_idx
        contenido = texto[inicio:min(fin, inicio + limite_max)]
        contenido = re.sub(r"^[:\s]+", "", contenido)
        if una_linea:
            nl = contenido.find("\n")
            if nl != -1:
                contenido = contenido[:nl]
        contenido = contenido.strip()
        if contenido:
            return contenido
    return ""


# Rango de fechas tal como lo exportan estos CV -- "octubre de 2025 - abril
# de 2026  (6 meses)", "septiembre de 2023 - agosto de 2025  (1 año y 11
# meses)". Se usa como "ancla" para partir el bloque de Formación/
# Experiencia en entradas sueltas (ver _parsear_entradas_fechadas): cada
# entrada real termina en una de estas líneas, así que sirve tanto para
# saber dónde acaba una entrada como para sacar sus fechas.
RANGO_FECHAS_RE = re.compile(
    r"(?P<inicio>\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}|[a-záéíóúñ]+\s+de\s+\d{4})"
    r"\s*-\s*"
    r"(?P<fin>\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}|[a-záéíóúñ]+\s+de\s+\d{4}|actualidad|actualmente|actual)",
    re.IGNORECASE,
)


def _parsear_entradas_fechadas(lineas: list[str], n_lineas_contexto: int) -> list[dict]:
    """Encuentra cada línea que ES un rango de fechas (no una fecha suelta
    mencionada de pasada dentro de una frase larga -- por eso se exige que
    el match cubra al menos la mitad de la línea) y devuelve, para cada una,
    las n_lineas_contexto líneas que la preceden -- en los CV de InfoJobs
    tanto Formación (tipo/título/centro, 3 líneas) como Experiencia (puesto/
    empresa, 2 líneas) tienen siempre ese mismo número fijo de líneas justo
    antes de la fecha, así que sirve para las dos con solo cambiar ese
    número. Común a _parsear_formacion_local/_parsear_experiencia_local."""
    entradas = []
    for i, linea in enumerate(lineas):
        m = RANGO_FECHAS_RE.search(linea)
        if not m or len(m.group(0)) < len(linea) * 0.5:
            continue
        entradas.append({
            "idx": i,
            "contexto": lineas[max(0, i - n_lineas_contexto):i],
            "fecha_inicio": m.group("inicio").strip(),
            "fecha_fin": m.group("fin").strip(),
        })
    return entradas


def _parsear_formacion_local(texto_seccion: str) -> list[dict]:
    """Formación estructurada (título/centro/fechas) a partir del texto ya
    extraído de la sección -- incluso sin Gemini, el patrón de estos CV es
    lo bastante fijo (tipo de título, título concreto, centro, fechas) como
    para sacarlo con reglas. Si una entrada no trae las 3 líneas de contexto
    completas (CV con un formato distinto al esperado) se descarta esa
    entrada en vez de inventar datos a medias -- mejor la ficha se quede sin
    historial estructurado (con el texto libre de siempre) que con una
    entrada mal cortada."""
    lineas = [l.strip() for l in texto_seccion.split("\n") if l.strip()]
    resultado = []
    for e in _parsear_entradas_fechadas(lineas, 3):
        tipo, especifico, centro = e["contexto"] if len(e["contexto"]) == 3 else (None, None, None)
        if not centro:
            continue
        if not especifico or especifico.lower() == (tipo or "").lower():
            titulo = tipo or especifico
        else:
            titulo = f"{tipo} {especifico}" if tipo else especifico
        resultado.append({
            "titulo": titulo, "centro": centro,
            "fecha_inicio": e["fecha_inicio"], "fecha_fin": e["fecha_fin"],
        })
    return resultado


def _parsear_experiencia_local(texto_seccion: str) -> list[dict]:
    """Experiencia estructurada (puesto/empresa/fechas/descripción) -- mismo
    razonamiento que _parsear_formacion_local, pero aquí el patrón fijo son
    2 líneas (puesto, empresa) antes de la fecha. La descripción se toma de
    todo lo que queda entre el final de esta entrada y el principio de la
    siguiente (o el final del bloque si es la última)."""
    lineas = [l.strip() for l in texto_seccion.split("\n") if l.strip()]
    entradas = _parsear_entradas_fechadas(lineas, 2)
    resultado = []
    for j, e in enumerate(entradas):
        if len(e["contexto"]) < 2:
            continue
        puesto, empresa = e["contexto"][-2], e["contexto"][-1]
        fin_bloque = entradas[j + 1]["idx"] - 2 if j + 1 < len(entradas) else len(lineas)
        descripcion = " ".join(lineas[e["idx"] + 1:max(e["idx"] + 1, fin_bloque)]).strip()
        resultado.append({
            "puesto": puesto, "empresa": empresa,
            "fecha_inicio": e["fecha_inicio"], "fecha_fin": e["fecha_fin"],
            "descripcion": descripcion[:600],
        })
    return resultado


def _extraer_de_texto(texto_crudo: str) -> dict:
    texto = PAGE_MARKER_RE.sub("", texto_crudo)
    texto = PIE_PAGINA_VACANTE_RE.sub("\n", texto)
    texto = _separar_cabeceras_pegadas(texto)
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
        # Formación/Experiencia necesitan mucho más que 400 caracteres --
        # ese límite pensado para un campo corto (Disponibilidad, Dirección)
        # cortaba a la mitad de la segunda entrada de quien tenía varios
        # estudios o trabajos, y _parsear_formacion_local/
        # _parsear_experiencia_local (justo debajo) necesitan el bloque
        # completo para reconocer todas las entradas, no solo la primera.
        limite = 4000 if campo in ("formacion", "experiencia") else 400
        contenido = _contenido_de_seccion(texto, keywords, una_linea, limite)
        if contenido:
            extraido[campo] = contenido

    if extraido.get("formacion"):
        formacion_json = _parsear_formacion_local(extraido["formacion"])
        if formacion_json:
            extraido["formacion_json"] = formacion_json
    if extraido.get("experiencia"):
        experiencia_json = _parsear_experiencia_local(extraido["experiencia"])
        if experiencia_json:
            extraido["experiencia_json"] = experiencia_json

    for nombre_extra, keywords, una_linea in EXTRA_KEYWORDS:
        contenido = _contenido_de_seccion(texto, keywords, una_linea)
        if contenido:
            extra[nombre_extra] = contenido[:200]

    extraido["extra_fields"] = extra
    return extraido


def _extraer_texto_paginas(pdf_bytes: bytes) -> list[str]:
    """pypdf.extract_text() lee el texto en el orden en que quedó escrito en
    el propio stream del PDF, que en los CVs exportados por ATS (InfoJobs...)
    no tiene por qué coincidir con el orden visual -- en la práctica, los
    títulos de varias secciones ("Idiomas", "Conocimientos"...) salían todos
    juntos y su contenido real aparecía mucho más abajo, sin ninguna relación
    ya con su título (ver _contenido_de_seccion). pdfplumber sí reconstruye
    el orden de lectura real a partir de la posición de cada palabra en la
    página, así que el mismo PDF sale ya bien ordenado sin tener que aplicar
    ninguna heurística de columnas aparte -- comprobado con CVs reales de
    InfoJobs. Es algo más lento que pypdf, pero aquí no hay prisa (esto solo
    corre cuando Gemini no está disponible)."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _segmentar_paginas_por_candidato(pdf_bytes: bytes) -> list[dict]:
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
    textos_paginas = _extraer_texto_paginas(pdf_bytes)
    primeras_lineas_por_pagina = [
        [l.strip() for l in texto.split("\n") if l.strip()][:10] for texto in textos_paginas
    ]
    marcadores_por_pagina = [_nombre_por_marcador_porcentaje(lineas) for lineas in primeras_lineas_por_pagina]
    usar_solo_marcador = sum(1 for m in marcadores_por_pagina if m) >= 2

    segmentos = []
    actual = []
    actual_inicio = 0
    for i, (texto_pagina, lineas, marcador) in enumerate(zip(textos_paginas, primeras_lineas_por_pagina, marcadores_por_pagina)):
        es_candidato_nuevo = bool(marcador) if usar_solo_marcador else _pagina_parece_inicio_de_candidato(lineas)
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
    segmentos = _segmentar_paginas_por_candidato(pdf_bytes)
    return [_extraer_de_texto(seg["texto"]) for seg in segmentos]


def detectar_paginas_por_candidato(pdf_bytes: bytes) -> list[tuple[int, int]]:
    """Rangos de página (1-indexado, ambos extremos incluidos) de cada
    candidato detectado en un PDF por lotes -- usa la misma heurística de
    segmentación que el extractor local (ver _segmentar_paginas_por_candidato)
    sin importar si el nombre/campos de cada uno se sacaron con Gemini o en
    local, para poder recortar el PDF físicamente y adjuntar a cada ficha
    solo sus páginas (ver /candidatos/adjuntar-pdf-lote)."""
    segmentos = _segmentar_paginas_por_candidato(pdf_bytes)
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


def extraer_cv(pdf_bytes: bytes, intentar_gemini: bool = True) -> tuple[list[dict], str, str | None]:
    """Intenta Gemini si hay API key configurada; si falla o no hay key, cae
    al método local sin IA. El PDF puede traer un único candidato o varios
    (hasta ~50) concatenados en el mismo archivo — se devuelve SIEMPRE una
    lista, de un elemento cuando es un solo candidato. Devuelve
    (lista_de_candidatos, metodo, motivo) -- motivo es None si se usó Gemini,
    o el mensaje de por qué falló (cuota agotada, saturado, clave inválida...)
    si se cayó al método local, para poder enseñárselo a quien subió el PDF
    en vez de solo dejarlo en los logs.

    intentar_gemini=False salta directamente al método local sin llamar a la
    API -- para cuando quien llama ya sabe que Gemini está caído en esta
    misma tanda (ver adjuntar_pdf_lote_confirmar_route) y no tiene sentido
    esperar el timeout de nuevo por cada persona."""
    if intentar_gemini and os.environ.get("GEMINI_API_KEY"):
        try:
            return extraer_con_gemini(pdf_bytes), "gemini", None
        except (GeminiNoConfiguradoError, GeminiNoDisponibleError) as exc:
            # Antes esto se tragaba en silencio -- no quedaba ningún rastro
            # de por qué se cayó al método local, así que un fallo real
            # (clave inválida, cuota agotada) era indistinguible de uno
            # transitorio (Gemini saturado un momento).
            print(f"[cv_extraction] Gemini falló, usando extracción local: {exc}")
            return _extraer_local(pdf_bytes), "local", str(exc)
    motivo = None if intentar_gemini else "Gemini ya había fallado antes en esta misma tanda."
    if intentar_gemini and not os.environ.get("GEMINI_API_KEY"):
        motivo = "No hay ninguna clave de Gemini configurada en el servidor."
    return _extraer_local(pdf_bytes), "local", motivo
