"""Motor genérico de "Test" — constructor de encuestas por páginas y
preguntas (identificación, escala Likert, texto abierto, opción múltiple),
con una página pública para que cualquiera responda y un panel privado para
editar la estructura en cualquier momento. Pensado para sustituir a
Microsoft Forms: mismo aspecto (fondo de imagen, tarjeta centrada, barra de
progreso, Atrás/Siguiente) y, si la encuesta se vincula a un tipo de
Informe, la respuesta se puntúa automáticamente (motor de scoring_valores)
igual que si se hubiera subido el Excel de Forms a mano."""
import json
import os
import re

import informes as informes_module
from db import get_connection

FONDOS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", "encuestas_fondos"))

TIPOS_PREGUNTA = {"texto", "email", "numero", "likert", "abierta", "opcion_multiple"}

LIKERT_OPCIONES = [
    "Totalmente en desacuerdo", "En desacuerdo", "Ni de acuerdo ni en desacuerdo",
    "De acuerdo", "Totalmente de acuerdo",
]


def ensure_encuestas_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            estado TEXT NOT NULL DEFAULT 'cerrada',
            fondo_ruta TEXT,
            color_boton TEXT NOT NULL DEFAULT '#5b2a2a',
            mensaje_final TEXT NOT NULL DEFAULT 'Gracias por completar el formulario.',
            tipo_informe_clave TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_paginas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL REFERENCES encuestas(id),
            orden INTEGER NOT NULL,
            instrucciones TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_preguntas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pagina_id INTEGER NOT NULL REFERENCES encuesta_paginas(id),
            orden INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            etiqueta TEXT NOT NULL,
            obligatoria INTEGER NOT NULL DEFAULT 1,
            opciones_json TEXT
        )
    """)
    # Sin fila_hash/dedup a propósito: cada persona real puede responder una
    # sola vez desde el propio flujo (no hay reenvío), y a diferencia de
    # Informes esto no se alimenta por Excel donde sí hace falta deduplicar
    # una posible re-importación del mismo archivo.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_respuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL REFERENCES encuestas(id),
            datos_json TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            dispositivo TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    os.makedirs(FONDOS_DIR, exist_ok=True)


def _slugify(titulo):
    s = titulo.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "encuesta"


def _slug_disponible(conn, slug, excluir_id=None):
    row = conn.execute("SELECT id FROM encuestas WHERE slug = ?", (slug,)).fetchone()
    return row is None or row["id"] == excluir_id


def _generar_slug_unico(conn, titulo, excluir_id=None):
    base = _slugify(titulo)
    slug = base
    i = 2
    while not _slug_disponible(conn, slug, excluir_id):
        slug = f"{base}-{i}"
        i += 1
    return slug


def _row_encuesta(r):
    d = dict(r)
    d["tiene_fondo"] = d.pop("fondo_ruta", None) is not None
    return d


def list_encuestas():
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.*, (SELECT COUNT(*) FROM encuesta_respuestas r WHERE r.encuesta_id = e.id) AS num_respuestas
        FROM encuestas e ORDER BY e.id DESC
    """).fetchall()
    conn.close()
    return [_row_encuesta(r) for r in rows]


def _fetch_estructura(conn, encuesta_id):
    paginas = conn.execute(
        "SELECT * FROM encuesta_paginas WHERE encuesta_id = ? ORDER BY orden", (encuesta_id,)
    ).fetchall()
    resultado = []
    for p in paginas:
        preguntas = conn.execute(
            "SELECT * FROM encuesta_preguntas WHERE pagina_id = ? ORDER BY orden", (p["id"],)
        ).fetchall()
        preguntas_dict = []
        for q in preguntas:
            qd = dict(q)
            qd["opciones"] = json.loads(qd.pop("opciones_json") or "[]")
            qd["obligatoria"] = bool(qd["obligatoria"])
            preguntas_dict.append(qd)
        pd = dict(p)
        pd["preguntas"] = preguntas_dict
        resultado.append(pd)
    return resultado


def get_encuesta(encuesta_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM encuestas WHERE id = ?", (encuesta_id,)).fetchone()
    if not row:
        conn.close()
        return None
    encuesta = _row_encuesta(row)
    encuesta["paginas"] = _fetch_estructura(conn, encuesta_id)
    conn.close()
    return encuesta


def get_encuesta_publica(slug):
    """Igual que get_encuesta pero solo si está abierta, y sin exponer
    tipo_informe_clave (detalle interno de administración, no le hace falta
    al candidato)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM encuestas WHERE slug = ?", (slug,)).fetchone()
    if not row or row["estado"] != "abierta":
        conn.close()
        return None
    encuesta = _row_encuesta(row)
    encuesta["paginas"] = _fetch_estructura(conn, row["id"])
    conn.close()
    encuesta.pop("tipo_informe_clave", None)
    return encuesta


def create_encuesta(titulo):
    conn = get_connection()
    slug = _generar_slug_unico(conn, titulo)
    cur = conn.execute(
        "INSERT INTO encuestas (titulo, slug) VALUES (?, ?)", (titulo.strip(), slug)
    )
    encuesta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return encuesta_id


def update_encuesta(encuesta_id, titulo, mensaje_final, color_boton, tipo_informe_clave):
    conn = get_connection()
    conn.execute(
        "UPDATE encuestas SET titulo = ?, mensaje_final = ?, color_boton = ?, tipo_informe_clave = ? WHERE id = ?",
        (titulo.strip(), mensaje_final.strip(), color_boton.strip(), tipo_informe_clave or None, encuesta_id),
    )
    conn.commit()
    conn.close()


def set_estado(encuesta_id, abierta):
    conn = get_connection()
    conn.execute("UPDATE encuestas SET estado = ? WHERE id = ?", ("abierta" if abierta else "cerrada", encuesta_id))
    conn.commit()
    conn.close()


def guardar_fondo(encuesta_id, contenido, extension):
    ruta = os.path.join(FONDOS_DIR, f"{encuesta_id}{extension}")
    with open(ruta, "wb") as f:
        f.write(contenido)
    conn = get_connection()
    conn.execute("UPDATE encuestas SET fondo_ruta = ? WHERE id = ?", (ruta, encuesta_id))
    conn.commit()
    conn.close()


def get_fondo_ruta(encuesta_id):
    conn = get_connection()
    row = conn.execute("SELECT fondo_ruta FROM encuestas WHERE id = ?", (encuesta_id,)).fetchone()
    conn.close()
    return row["fondo_ruta"] if row and row["fondo_ruta"] else None


def delete_encuesta(encuesta_id):
    conn = get_connection()
    pagina_ids = [r["id"] for r in conn.execute("SELECT id FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,)).fetchall()]
    for pid in pagina_ids:
        conn.execute("DELETE FROM encuesta_preguntas WHERE pagina_id = ?", (pid,))
    conn.execute("DELETE FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,))
    conn.execute("DELETE FROM encuesta_respuestas WHERE encuesta_id = ?", (encuesta_id,))
    conn.execute("DELETE FROM encuestas WHERE id = ?", (encuesta_id,))
    conn.commit()
    conn.close()
    ruta = get_fondo_ruta(encuesta_id)
    if ruta and os.path.exists(ruta):
        os.remove(ruta)


def add_pagina(encuesta_id, instrucciones=""):
    conn = get_connection()
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO encuesta_paginas (encuesta_id, orden, instrucciones) VALUES (?, ?, ?)",
        (encuesta_id, orden, instrucciones),
    )
    pagina_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pagina_id


def update_pagina(pagina_id, instrucciones):
    conn = get_connection()
    conn.execute("UPDATE encuesta_paginas SET instrucciones = ? WHERE id = ?", (instrucciones, pagina_id))
    conn.commit()
    conn.close()


def delete_pagina(pagina_id):
    conn = get_connection()
    actual = conn.execute("SELECT encuesta_id FROM encuesta_paginas WHERE id = ?", (pagina_id,)).fetchone()
    conn.execute("DELETE FROM encuesta_preguntas WHERE pagina_id = ?", (pagina_id,))
    conn.execute("DELETE FROM encuesta_paginas WHERE id = ?", (pagina_id,))
    if actual:
        _renumerar_paginas(conn, actual["encuesta_id"])
    conn.commit()
    conn.close()


def _renumerar_paginas(conn, encuesta_id):
    """Tras borrar una página quedaría un hueco en "orden" (p.ej. 1,3,4) que
    haría que mover_pagina no encontrara vecino exacto en algunos casos —
    se recompacta a 1..N en el mismo orden relativo."""
    filas = conn.execute(
        "SELECT id FROM encuesta_paginas WHERE encuesta_id = ? ORDER BY orden", (encuesta_id,)
    ).fetchall()
    for i, f in enumerate(filas, start=1):
        conn.execute("UPDATE encuesta_paginas SET orden = ? WHERE id = ?", (i, f["id"]))


def mover_pagina(pagina_id, direccion):
    """direccion: -1 (subir) o 1 (bajar) — intercambia el "orden" con la
    página vecina en esa dirección."""
    conn = get_connection()
    actual = conn.execute("SELECT * FROM encuesta_paginas WHERE id = ?", (pagina_id,)).fetchone()
    if not actual:
        conn.close()
        return
    vecino_orden = actual["orden"] + direccion
    vecino = conn.execute(
        "SELECT * FROM encuesta_paginas WHERE encuesta_id = ? AND orden = ?", (actual["encuesta_id"], vecino_orden)
    ).fetchone()
    if vecino:
        conn.execute("UPDATE encuesta_paginas SET orden = ? WHERE id = ?", (vecino_orden, actual["id"]))
        conn.execute("UPDATE encuesta_paginas SET orden = ? WHERE id = ?", (actual["orden"], vecino["id"]))
        conn.commit()
    conn.close()


def add_pregunta(pagina_id, tipo, etiqueta, obligatoria=True, opciones=None):
    if tipo not in TIPOS_PREGUNTA:
        raise ValueError(f"Tipo de pregunta desconocido: {tipo}")
    conn = get_connection()
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 FROM encuesta_preguntas WHERE pagina_id = ?", (pagina_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO encuesta_preguntas (pagina_id, orden, tipo, etiqueta, obligatoria, opciones_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pagina_id, orden, tipo, etiqueta.strip(), 1 if obligatoria else 0, json.dumps(opciones or [], ensure_ascii=False)),
    )
    pregunta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pregunta_id


def update_pregunta(pregunta_id, etiqueta, obligatoria, opciones=None):
    conn = get_connection()
    conn.execute(
        "UPDATE encuesta_preguntas SET etiqueta = ?, obligatoria = ?, opciones_json = ? WHERE id = ?",
        (etiqueta.strip(), 1 if obligatoria else 0, json.dumps(opciones or [], ensure_ascii=False), pregunta_id),
    )
    conn.commit()
    conn.close()


def _renumerar_preguntas(conn, pagina_id):
    filas = conn.execute(
        "SELECT id FROM encuesta_preguntas WHERE pagina_id = ? ORDER BY orden", (pagina_id,)
    ).fetchall()
    for i, f in enumerate(filas, start=1):
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (i, f["id"]))


def delete_pregunta(pregunta_id):
    conn = get_connection()
    actual = conn.execute("SELECT pagina_id FROM encuesta_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    conn.execute("DELETE FROM encuesta_preguntas WHERE id = ?", (pregunta_id,))
    if actual:
        _renumerar_preguntas(conn, actual["pagina_id"])
    conn.commit()
    conn.close()


def mover_pregunta(pregunta_id, direccion):
    conn = get_connection()
    actual = conn.execute("SELECT * FROM encuesta_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    if not actual:
        conn.close()
        return
    vecino_orden = actual["orden"] + direccion
    vecino = conn.execute(
        "SELECT * FROM encuesta_preguntas WHERE pagina_id = ? AND orden = ?", (actual["pagina_id"], vecino_orden)
    ).fetchone()
    if vecino:
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (vecino_orden, actual["id"]))
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (actual["orden"], vecino["id"]))
        conn.commit()
    conn.close()


def _detectar_dispositivo(user_agent):
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "Tablet"
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return "Móvil"
    if ua:
        return "Escritorio"
    return "Desconocido"


def guardar_respuesta(slug, respuestas_por_pregunta, ip, user_agent):
    """respuestas_por_pregunta: {pregunta_id (str o int): valor}. Se guarda
    tal cual (por id) para la vista de administración, y además se arma un
    segundo dict keyed por ETIQUETA de pregunta — así, si la encuesta
    alimenta un tipo de Informe, encaja tal cual con lo que espera
    scoring_valores.calcular() (que reconoce las preguntas por el texto de
    su enunciado, igual que en el Excel de Forms)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM encuestas WHERE slug = ?", (slug,)).fetchone()
    if not row or row["estado"] != "abierta":
        conn.close()
        raise ValueError("Esta encuesta no está abierta actualmente")
    encuesta_id = row["id"]
    tipo_informe_clave = row["tipo_informe_clave"]

    preguntas = conn.execute("""
        SELECT eq.id, eq.etiqueta FROM encuesta_preguntas eq
        JOIN encuesta_paginas ep ON ep.id = eq.pagina_id
        WHERE ep.encuesta_id = ?
    """, (encuesta_id,)).fetchall()
    etiqueta_por_id = {str(p["id"]): p["etiqueta"] for p in preguntas}

    fila_por_etiqueta = {}
    for pid, valor in respuestas_por_pregunta.items():
        etiqueta = etiqueta_por_id.get(str(pid))
        if etiqueta:
            fila_por_etiqueta[etiqueta] = valor

    dispositivo = _detectar_dispositivo(user_agent)
    conn.execute(
        "INSERT INTO encuesta_respuestas (encuesta_id, datos_json, ip, user_agent, dispositivo) VALUES (?, ?, ?, ?, ?)",
        (encuesta_id, json.dumps(fila_por_etiqueta, ensure_ascii=False, default=str), ip, user_agent, dispositivo),
    )
    conn.commit()
    conn.close()

    if tipo_informe_clave:
        informes_module.ingest_fila_directa(tipo_informe_clave, fila_por_etiqueta, origen=f"Test web: {row['titulo']}")

    return {"ok": True}


def list_respuestas(encuesta_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, datos_json, ip, user_agent, dispositivo, creado_en FROM encuesta_respuestas "
        "WHERE encuesta_id = ? ORDER BY creado_en DESC",
        (encuesta_id,),
    ).fetchall()
    conn.close()
    resultado = []
    for r in rows:
        d = dict(r)
        d["datos"] = json.loads(d.pop("datos_json"))
        resultado.append(d)
    return resultado


ensure_encuestas_tables()
