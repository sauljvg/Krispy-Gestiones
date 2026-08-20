import io
import os
import re
import unicodedata

# --- Extracción local del CV, puerto de localCvExtraction.ts ---
#
# Este módulo extraía candidatos con Gemini (IA en la nube) cuando había una
# GEMINI_API_KEY configurada, y solo caía al método local si Gemini fallaba
# o no había clave. Se quitó Gemini del todo: el plan gratuito tenía muy
# poco margen (10 peticiones/minuto, cupo diario) para el volumen real de
# lotes de decenas de candidatos, y una vez el extractor local aprendió a
# sacar también el historial estructurado (formacion_json/experiencia_json,
# no solo texto plano -- ver _parsear_formacion_local/_parsear_experiencia_local
# más abajo) daba resultados igual de buenos sin depender de un servicio
# externo con esas limitaciones. Ver el historial de git de este archivo si
# hace falta recuperar la integración con Gemini más adelante.

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+34[\s.-]?)?\b[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b")
DNI_RE = re.compile(r"\b(\d{8}[A-Za-z]|[XYZxyz]\d{7}[A-Za-z])\b")
DATE_RE = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b|\b\d{1,2}\s+de\s+[a-zA-Zé]+\s+de\s+\d{4}\b", re.IGNORECASE)
PAGE_MARKER_RE = re.compile(r"--\s*\d+\s*of\s*\d+\s*--", re.IGNORECASE)

# El ATS repite, en CADA página, un pie/cabecera con el nombre de la vacante
# a la que se apuntó (p.ej. "Dependiente/a Krispy Kreme") como PRIMERA línea
# de la página, y una marca tipo "N/M" (compatibilidad o página X de Y según
# el origen del PDF) al final de la ÚLTIMA línea. Ninguno de los dos es
# contenido real del CV -- ver _limpiar_pie_pagina_ats, que los recorta
# usando los límites de página reales (antes de unir todas las páginas en un
# solo texto) para no arriesgarse a comerse contenido real que caiga justo
# después, como pasaba con un intento anterior basado en buscar el patrón
# "N/M" en el texto ya unido sin saber dónde estaban esos límites.
PIE_PAGINA_SCORE_RE = re.compile(r"[ \t]*\d{1,3}\s*/\s*\d{1,3}\s*$")

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
    dentro de una frase, no.

    Además hace falta que justo después venga ":" (como en TODO chip real,
    "Autónomo: No") -- sin este requisito, un puesto de trabajo real que
    termine en una de estas palabras (p.ej. el puesto "Técnico de Estudios",
    con "Estudios" en mayúscula y precedido de espacio) se partía igual,
    convirtiéndolo en "Técnico de" + una falsa cabecera "Estudios" que luego
    _contenido_de_seccion tomaba como el principio de la sección Formación,
    tragándose de paso todo el contenido real de Experiencia."""
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
            fin_kw = idx + len(kw_norm)
            le_sigue_dos_puntos = texto_norm[fin_kw:].lstrip(" \t").startswith(":")
            if precedido_por_espacio and texto[idx].isupper() and le_sigue_dos_puntos:
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
        # 4000 tampoco bastaba para alguien con varios puestos largos y
        # detallados (un historial real de 5 experiencias con descripción
        # extensa ocupaba ~5900 caracteres) -- 10000 deja margen de sobra.
        limite = 10000 if campo in ("formacion", "experiencia") else 400
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


def _limpiar_pie_pagina_ats(textos_paginas: list[str]) -> list[str]:
    """Recorta de cada página el pie/cabecera del ATS descrito junto a
    PIE_PAGINA_SCORE_RE: la vacante repetida como primera línea, y la marca
    "N/M" al final de la última. La vacante se reconoce por REPETICIÓN (si
    el documento tiene 2+ páginas, la primera línea de página es idéntica en
    todas -- nada que un candidato escriba de verdad encabeza así, palabra
    por palabra, varias páginas seguidas) en vez de por su contenido, para
    no tener que conocer de antemano el nombre de la vacante. Con un
    documento de una sola página no hay repetición que detectar y esa
    primera línea se deja tal cual -- en la práctica no causa problemas
    porque nunca coincide con el patrón de nombre de _adivinar_nombre (trae
    una barra, "Dependiente/a")."""
    lineas_por_pagina = [[l for l in texto.split("\n") if l.strip()] for texto in textos_paginas]

    primeras = [lineas[0].strip() for lineas in lineas_por_pagina if lineas]
    conteo: dict[str, int] = {}
    for l in primeras:
        conteo[l] = conteo.get(l, 0) + 1
    cabecera_repetida = {l for l, n in conteo.items() if n >= 2}

    paginas_limpias = []
    for lineas in lineas_por_pagina:
        if lineas and lineas[0].strip() in cabecera_repetida:
            lineas = lineas[1:]
        if lineas:
            ultima = PIE_PAGINA_SCORE_RE.sub("", lineas[-1])
            lineas = lineas[:-1] + ([ultima] if ultima.strip() else [])
        paginas_limpias.append("\n".join(lineas))
    return paginas_limpias


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
    InfoJobs. Es algo más lento que pypdf, pero aquí no hay prisa."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        textos = [page.extract_text() or "" for page in pdf.pages]
    return _limpiar_pie_pagina_ats(textos)


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
    segmentación que el extractor local (ver _segmentar_paginas_por_candidato),
    para poder recortar el PDF físicamente y adjuntar a cada ficha solo sus
    páginas (ver /candidatos/adjuntar-pdf-lote)."""
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


def extraer_cv(pdf_bytes: bytes) -> list[dict]:
    """Extrae los candidatos de un PDF con el método local (sin IA externa).
    El PDF puede traer un único candidato o varios (hasta ~50) concatenados
    en el mismo archivo — se devuelve SIEMPRE una lista, de un elemento
    cuando es un solo candidato."""
    return _extraer_local(pdf_bytes)
