import hashlib
import io
import json
import re

from openpyxl import load_workbook

from db import get_connection

LIKERT_ORDEN = ["Totalmente de acuerdo", "De acuerdo", "Neutral", "En desacuerdo", "Totalmente en desacuerdo"]

METADATA_HINTS = {
    "id": "id",
    "hora de inicio": "hora_inicio",
    "hora de finalizacion": "hora_fin",
    "hora de finalización": "hora_fin",
    "correo electronico": "correo",
    "correo electrónico": "correo",
    "nombre": "nombre",
}

STOPWORDS = {
    # artículos, preposiciones, conjunciones
    "de", "la", "el", "en", "que", "y", "a", "los", "las", "un", "una", "mi", "me", "se", "por", "con",
    "es", "lo", "del", "al", "su", "sus", "para", "mas", "más", "esta", "este", "estas", "estos", "esa",
    "ese", "esos", "esas", "eso", "esto", "aquello", "aquel", "aquella", "aquellos", "aquellas",
    "hay", "no", "si", "sí", "o", "unos", "unas", "le", "les", "nos", "os", "ya", "todo", "toda", "todos",
    "todas", "como", "pero", "tambien", "también", "porque", "cuando", "donde", "sobre", "entre", "sin",
    "desde", "hasta", "hacia", "durante", "mediante", "según", "segun", "sino", "pues", "aunque",
    "mientras", "e", "u", "ni", "tan", "tanto", "tanta", "tantos", "tantas",
    # pronombres
    "yo", "tu", "tú", "él", "ella", "ellos", "ellas", "nosotros", "nosotras", "vosotros", "vosotras",
    "usted", "ustedes", "cual", "cuales", "quien", "quienes", "cuyo", "cuya", "cuyos", "cuyas",
    "mismo", "misma", "mismos", "mismas", "otro", "otra", "otros", "otras", "algo", "alguien",
    "alguna", "algunas", "alguno", "algunos", "nada", "nadie", "algún", "ningún", "ninguno", "ninguna",
    # verbos comunes (ser/estar/haber/tener/poder/deber/hacer/querer) en formas frecuentes
    "ser", "estar", "hacer", "tener", "poder", "deber", "querer", "creo", "considero", "creemos",
    "sea", "son", "soy", "eres", "somos", "sois", "fue", "fueron", "era", "eran", "siendo", "sido",
    "esta", "estan", "están", "estamos", "estoy", "estaba", "estaban", "estuvo",
    "hace", "hacen", "hacemos", "hago", "haciendo", "hecho",
    "tiene", "tienen", "tenemos", "tengo", "tenía", "tenia",
    "puede", "pueden", "podemos", "puedo", "podría", "podria", "podrían", "podrian",
    "debe", "deben", "debemos", "debería", "deberia", "deberían", "deberian",
    "quiere", "quieren", "queremos", "quiero", "quisiera",
    "seguir", "sigue", "siguen", "seguimos", "sigo",
    # adverbios/cuantificadores genéricos poco informativos
    "poco", "pocos", "poca", "pocas", "mucho", "muchos", "mucha", "muchas", "cada", "vez", "veces",
    "bien", "mal", "solo", "sólo", "así", "asi", "aquí", "aqui", "allí", "alli", "ahí", "ahi",
    "uno", "dos", "tres", "junta", "llega", "cosa", "cosas",
}

CV_DIR = None  # no aplica aquí

# Une cada centro de Clima Laboral con su tienda equivalente en el sistema de
# Reseñas (Google), para poder mostrar la satisfacción real de cliente junto
# al engagement. Oficinas no tiene tienda física de cara al público, así que
# se queda fuera (None). ParqueSur Fábrica/Tienda comparten la misma ficha de
# Google (una sola ubicación), así que ambas apuntan a "ParqueSur".
_CENTRO_A_TIENDAS = {
    "caleido": ["Caleido"],
    "gran plaza 2": ["Gran Plaza 2"],
    "la gavia": ["La Gavia"],
    "parquesur fabrica": ["ParqueSur"],
    "parquesur tienda": ["ParqueSur"],
    "princesa": ["Princesa"],
    "plenilunio": ["Plenilunio"],
}


def ensure_clima_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clima_oleadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            etiqueta TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clima_respuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            oleada_id INTEGER NOT NULL REFERENCES clima_oleadas(id),
            centro TEXT NOT NULL,
            fila_hash TEXT NOT NULL,
            datos_json TEXT NOT NULL,
            creado_en TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(oleada_id, fila_hash)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clima_plantilla (
            oleada_id INTEGER NOT NULL REFERENCES clima_oleadas(id),
            centro TEXT NOT NULL,
            empleados INTEGER NOT NULL,
            PRIMARY KEY (oleada_id, centro)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clima_importaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            oleada_id INTEGER NOT NULL REFERENCES clima_oleadas(id),
            archivo_nombre TEXT,
            subido_por TEXT,
            subido_en TEXT NOT NULL DEFAULT (datetime('now')),
            nuevas INTEGER NOT NULL DEFAULT 0,
            ya_existian INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _normaliza_header(h):
    return (h or "").strip().lower().replace("í", "i").replace("ó", "o").replace("á", "a").replace(
        "é", "e"
    ).replace("ú", "u")


def _hash_fila(fila):
    blob = json.dumps(fila, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_sheet_rows(ws):
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return []
    filas = []
    for row in rows_iter:
        if row is None or all(v is None for v in row):
            continue
        datos = {}
        for i, key in enumerate(header):
            if not key:
                continue
            value = row[i] if i < len(row) else None
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            datos[key] = value
        if datos:
            filas.append(datos)
    return filas


def _column_roles(headers):
    """Clasifica cada columna sin depender del texto exacto de la pregunta:
    metadata conocida, preguntas Likert ("Categoria.Pregunta") en el orden en
    que aparecen, y preguntas abiertas (sin punto, no metadata)."""
    centro_col = None
    metadata_cols = {}
    likert = []  # lista de (header, categoria, pregunta) en orden
    abiertas = []
    categorias_orden = []

    for h in headers:
        norm = _normaliza_header(h)
        if "centro" in norm:
            centro_col = h
            continue
        matched_meta = False
        for hint, campo in METADATA_HINTS.items():
            if norm == hint:
                metadata_cols[campo] = h
                matched_meta = True
                break
        if matched_meta:
            continue
        if "." in h:
            categoria, _, pregunta = h.partition(".")
            categoria = categoria.strip()
            pregunta = pregunta.strip()
            if categoria not in categorias_orden:
                categorias_orden.append(categoria)
            likert.append((h, categoria, pregunta))
        else:
            abiertas.append(h)

    return {
        "centro_col": centro_col,
        "metadata": metadata_cols,
        "likert": likert,
        "abiertas": abiertas,
        "categorias_orden": categorias_orden,
    }


def _parse_plantilla(wb):
    if "Plantilla" not in wb.sheetnames:
        return {}
    ws = wb["Plantilla"]
    filas = _read_sheet_rows(ws)
    resultado = {}
    for fila in filas:
        centro = None
        empleados = None
        for k, v in fila.items():
            kn = _normaliza_header(k)
            if kn == "tienda" or "centro" in kn:
                centro = v
            elif "emplead" in kn:
                empleados = v
        if centro and empleados is not None and str(centro).strip().lower() != "total":
            try:
                resultado[str(centro).strip()] = int(empleados)
            except (TypeError, ValueError):
                continue
    return resultado


def get_or_create_oleada(nueva, etiqueta=None):
    conn = get_connection()
    if not nueva:
        row = conn.execute("SELECT id FROM clima_oleadas ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            oleada_id = row[0]
            conn.close()
            return oleada_id
    cur = conn.execute("INSERT INTO clima_oleadas (etiqueta) VALUES (?)", (etiqueta,))
    conn.commit()
    oleada_id = cur.lastrowid
    conn.close()
    return oleada_id


def import_excel(file_bytes, archivo_nombre, subido_por, nueva_oleada=False):
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as e:
        raise ValueError(f"No se pudo leer el archivo Excel: {e}")

    if "Respuestas" not in wb.sheetnames:
        raise ValueError("El Excel debe tener una hoja llamada 'Respuestas'")

    filas = _read_sheet_rows(wb["Respuestas"])
    if not filas:
        raise ValueError("La hoja 'Respuestas' no tiene filas de datos")

    roles = _column_roles(list(filas[0].keys()))
    if roles["centro_col"] is None:
        raise ValueError("No se encontró una columna de centro de trabajo (p.ej. '¿Cuál es tu centro de trabajo?')")

    plantilla = _parse_plantilla(wb)

    oleada_id = get_or_create_oleada(nueva_oleada)

    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO clima_importaciones (oleada_id, archivo_nombre, subido_por) VALUES (?, ?, ?)",
        (oleada_id, archivo_nombre, subido_por),
    )
    importacion_id = cur.lastrowid

    nuevas = 0
    ya_existian = 0
    for fila in filas:
        centro = fila.get(roles["centro_col"])
        if not centro:
            continue
        fila_hash = _hash_fila(fila)
        existe = conn.execute(
            "SELECT id FROM clima_respuestas WHERE oleada_id = ? AND fila_hash = ?", (oleada_id, fila_hash)
        ).fetchone()
        if existe:
            ya_existian += 1
            continue
        datos_json = json.dumps(fila, ensure_ascii=False, default=str)
        conn.execute(
            "INSERT INTO clima_respuestas (oleada_id, centro, fila_hash, datos_json) VALUES (?, ?, ?, ?)",
            (oleada_id, str(centro).strip(), fila_hash, datos_json),
        )
        nuevas += 1

    for centro, empleados in plantilla.items():
        conn.execute(
            "INSERT INTO clima_plantilla (oleada_id, centro, empleados) VALUES (?, ?, ?) "
            "ON CONFLICT(oleada_id, centro) DO UPDATE SET empleados = excluded.empleados",
            (oleada_id, centro, empleados),
        )

    conn.execute(
        "UPDATE clima_importaciones SET nuevas = ?, ya_existian = ? WHERE id = ?",
        (nuevas, ya_existian, importacion_id),
    )
    conn.commit()
    conn.close()
    return {"oleada_id": oleada_id, "nuevas": nuevas, "ya_existian": ya_existian, "total_en_excel": len(filas)}


def list_oleadas():
    conn = get_connection()
    rows = conn.execute("""
        SELECT o.id, o.etiqueta, o.creado_en, COUNT(r.id) AS num_respuestas
        FROM clima_oleadas o
        LEFT JOIN clima_respuestas r ON r.oleada_id = o.id
        GROUP BY o.id ORDER BY o.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_centros(oleada_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT centro FROM clima_respuestas WHERE oleada_id = ? ORDER BY centro", (oleada_id,)
    ).fetchall()
    conn.close()
    return [r["centro"] for r in rows]


def _fetch_respuestas(conn, oleada_id, centro):
    if centro:
        rows = conn.execute(
            "SELECT datos_json FROM clima_respuestas WHERE oleada_id = ? AND centro = ?", (oleada_id, centro)
        ).fetchall()
    else:
        rows = conn.execute("SELECT datos_json FROM clima_respuestas WHERE oleada_id = ?", (oleada_id,)).fetchall()
    return [json.loads(r["datos_json"]) for r in rows]


def _empleados_total(conn, oleada_id, centro):
    if centro:
        row = conn.execute(
            "SELECT empleados FROM clima_plantilla WHERE oleada_id = ? AND centro = ?", (oleada_id, centro)
        ).fetchone()
        return row["empleados"] if row else None
    row = conn.execute("SELECT SUM(empleados) AS total FROM clima_plantilla WHERE oleada_id = ?", (oleada_id,)).fetchone()
    return row["total"] if row and row["total"] is not None else None


def _tokenizar(texto):
    palabras = re.findall(r"[a-záéíóúñü]+", texto.lower())
    return [p for p in palabras if len(p) > 2 and p not in STOPWORDS]


_RESPUESTAS_SIN_VALOR = {".", "..", "…", "-", "sin comentarios", "sin comentario"}


def _respuesta_con_valor(texto):
    """Filtra respuestas abiertas vacías o que son solo un punto/relleno
    ("." , "sin comentarios") — no aportan nada y no deben aparecer en la
    lista de comentarios ni en el PDF."""
    limpio = (texto or "").strip()
    if not limpio:
        return False
    return limpio.lower() not in _RESPUESTAS_SIN_VALOR


def compute_reporte(oleada_id, centro=None):
    conn = get_connection()
    filas = _fetch_respuestas(conn, oleada_id, centro)
    if not filas:
        conn.close()
        raise ValueError("No hay respuestas para este centro en esta oleada")

    roles = _column_roles(list(filas[0].keys()))
    n = len(filas)
    empleados = _empleados_total(conn, oleada_id, centro)
    participacion = round(n / empleados * 100, 1) if empleados else None

    def stats_pregunta(header):
        conteo = {cat: 0 for cat in LIKERT_ORDEN}
        respondidas = 0
        for fila in filas:
            valor = fila.get(header)
            if valor in conteo:
                conteo[valor] += 1
                respondidas += 1
        if respondidas == 0:
            porcentajes = {cat: 0.0 for cat in LIKERT_ORDEN}
        else:
            porcentajes = {cat: round(conteo[cat] / respondidas * 100, 1) for cat in LIKERT_ORDEN}
        top2box = round(porcentajes["Totalmente de acuerdo"] + porcentajes["De acuerdo"], 1)
        return porcentajes, top2box

    primera_categoria = roles["categorias_orden"][0] if roles["categorias_orden"] else None

    resultados_engagement = []
    impulsores_engagement = []
    todas_preguntas_top2box = []

    for header, categoria, pregunta in roles["likert"]:
        porcentajes, top2box = stats_pregunta(header)
        item = {"pregunta": pregunta, "categoria": categoria, "porcentajes": porcentajes, "top2box": top2box}
        if categoria == primera_categoria:
            resultados_engagement.append(item)
        else:
            impulsores_engagement.append(item)
        todas_preguntas_top2box.append(item)

    if resultados_engagement:
        engagement_score = round(
            sum(i["porcentajes"]["Totalmente de acuerdo"] for i in resultados_engagement) / len(resultados_engagement),
            1,
        )
    else:
        engagement_score = None

    # Empate en top2box se resuelve por % "Totalmente de acuerdo" (más
    # exigente que "De acuerdo"), para que el orden sea siempre el mismo.
    ordenado_top2box = sorted(
        todas_preguntas_top2box,
        key=lambda i: (i["top2box"], i["porcentajes"]["Totalmente de acuerdo"]),
        reverse=True,
    )
    fortalezas = ordenado_top2box[:2]
    oportunidades = list(reversed(ordenado_top2box[-2:]))

    abiertas = {}
    nube_palabras = {}
    for header in roles["abiertas"]:
        textos = [str(fila[header]).strip() for fila in filas if fila.get(header)]
        textos = [t for t in textos if _respuesta_con_valor(t)]
        abiertas[header] = textos
        conteo_palabras = {}
        for texto in textos:
            for palabra in _tokenizar(texto):
                conteo_palabras[palabra] = conteo_palabras.get(palabra, 0) + 1
        top_palabras = sorted(conteo_palabras.items(), key=lambda x: x[1], reverse=True)[:40]
        nube_palabras[header] = [{"palabra": p, "veces": c} for p, c in top_palabras]

    anterior = get_anterior_score(centro, oleada_id)
    satisfaccion = get_satisfaccion_cliente(centro, oleada_id)

    conn.close()
    return {
        "oleada_id": oleada_id,
        "centro": centro,
        "n": n,
        "empleados": empleados,
        "participacion": participacion,
        "engagement_presente": engagement_score,
        "engagement_anterior": anterior,
        "satisfaccion_presente": satisfaccion["presente"] if satisfaccion else None,
        "satisfaccion_anterior": satisfaccion["anterior"] if satisfaccion else None,
        "tiene_satisfaccion": satisfaccion is not None,
        "resultados_engagement": resultados_engagement,
        "impulsores_engagement": impulsores_engagement,
        "fortalezas": fortalezas,
        "oportunidades": oportunidades,
        "abiertas": abiertas,
        "nube_palabras": nube_palabras,
    }


def _tiendas_para_centro(centro):
    if centro is None:
        todas = set()
        for tiendas in _CENTRO_A_TIENDAS.values():
            todas.update(tiendas)
        return sorted(todas)
    return _CENTRO_A_TIENDAS.get(_normaliza_header(centro))


def get_satisfaccion_cliente(centro, oleada_id):
    """Satisfacción de cliente (estrellas de Google) para el mismo centro,
    para mostrarla junto al engagement. Presente = media de todas las
    reseñas a día de hoy. Anterior = media de reseñas hasta la fecha de la
    oleada anterior (así se compara el mismo punto en el tiempo que el
    engagement de esa oleada). None si el centro no tiene tienda física
    (p.ej. Oficinas) o no hay reseñas."""
    tiendas = _tiendas_para_centro(centro)
    if not tiendas:
        return None

    conn = get_connection()
    anterior_oleada = conn.execute(
        "SELECT creado_en FROM clima_oleadas WHERE id < ? ORDER BY id DESC LIMIT 1", (oleada_id,)
    ).fetchone()
    fecha_anterior = anterior_oleada["creado_en"] if anterior_oleada else None

    placeholders = ",".join("?" for _ in tiendas)

    def promedio(fecha_limite):
        query = f"SELECT AVG(calificacion_num) AS media FROM reviews WHERE tienda IN ({placeholders})"
        params = list(tiendas)
        if fecha_limite:
            query += " AND fecha_datetime <= ?"
            params.append(fecha_limite)
        row = conn.execute(query, params).fetchone()
        return round(row["media"], 2) if row and row["media"] is not None else None

    presente = promedio(None)
    anterior = promedio(fecha_anterior) if fecha_anterior else None
    conn.close()
    return {"presente": presente, "anterior": anterior}


def get_anterior_score(centro, oleada_id):
    conn = get_connection()
    oleadas_previas = conn.execute(
        "SELECT id FROM clima_oleadas WHERE id < ? ORDER BY id DESC", (oleada_id,)
    ).fetchall()
    conn.close()
    for row in oleadas_previas:
        try:
            reporte = compute_reporte(row["id"], centro)
        except ValueError:
            continue
        if reporte["engagement_presente"] is not None:
            return reporte["engagement_presente"]
    return None


ensure_clima_tables()
