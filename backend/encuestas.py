"""Motor genérico de "Test" — constructor de encuestas por páginas y
preguntas (identificación, escala Likert, texto abierto, opción múltiple),
con una página pública para que cualquiera responda y un panel privado para
editar la estructura en cualquier momento. Pensado para sustituir a
Microsoft Forms: mismo aspecto (fondo de imagen, tarjeta centrada, barra de
progreso, Atrás/Siguiente) y, si la encuesta se vincula a un tipo de
Informe, la respuesta se puntúa automáticamente (motor de scoring_valores)
igual que si se hubiera subido el Excel de Forms a mano."""
import datetime
import json
import os
import re
from zoneinfo import ZoneInfo

import entrevistas as entrevistas_module
import informes as informes_module
from db import DATA_DIR, get_connection

FONDOS_DIR = os.path.join(DATA_DIR, "uploads", "encuestas_fondos")

TIPOS_PREGUNTA = {"texto", "email", "numero", "likert", "abierta", "opcion_simple", "opcion_multiple", "prioridad", "fecha", "calificacion"}

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
    # tipo_informe_clave y tipo_entrevista_empresa son mutuamente excluyentes
    # en la práctica (un test alimenta O un tipo de Informe O la Entrevista
    # de Salida de una empresa, nunca las dos) — se guardan en columnas
    # separadas en vez de una sola clave con prefijo para no tener que
    # parsear un string compuesto en cada sitio que lo usa.
    cols_encuestas = {row[1] for row in conn.execute("PRAGMA table_info(encuestas)")}
    if "tipo_entrevista_empresa" not in cols_encuestas:
        conn.execute("ALTER TABLE encuestas ADD COLUMN tipo_entrevista_empresa TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_paginas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL REFERENCES encuestas(id),
            orden INTEGER NOT NULL,
            instrucciones TEXT
        )
    """)
    # Ramificación: una página puede depender de la respuesta a una pregunta
    # de una página ANTERIOR (p.ej. "Centro de Trabajo" -> mostrar solo el
    # bloque de "Puesto" que corresponda a ese centro), igual que las
    # secciones condicionales de Microsoft Forms/Google Forms. NULL en
    # condicion_pregunta_id = página siempre visible (comportamiento previo,
    # así que no hace falta migrar datos existentes).
    cols_paginas = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_paginas)")}
    if "condicion_pregunta_id" not in cols_paginas:
        conn.execute("ALTER TABLE encuesta_paginas ADD COLUMN condicion_pregunta_id INTEGER")
        conn.execute("ALTER TABLE encuesta_paginas ADD COLUMN condicion_valores TEXT")
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
    # mostrar_dashboard: marca explícita de "esta respuesta quiero verla en
    # Scoring/Dashboard de Informes, no solo en la hoja Respuestas" — antes
    # era automático para abierta/prioridad; ahora es una casilla que el
    # admin puede activar en CUALQUIER tipo de pregunta (p.ej. una opción
    # múltiple de una pregunta situacional también puede ser útil de ver de
    # un vistazo). Las preguntas abiertas/prioridad ya existentes se migran
    # activadas para no perder el comportamiento que ya tenían.
    cols_preguntas = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_preguntas)")}
    if "mostrar_dashboard" not in cols_preguntas:
        conn.execute("ALTER TABLE encuesta_preguntas ADD COLUMN mostrar_dashboard INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE encuesta_preguntas SET mostrar_dashboard = 1 WHERE tipo IN ('abierta', 'prioridad')")
    # "opcion_multiple" originalmente solo dejaba marcar UNA opción (radio) —
    # el nombre no correspondía al comportamiento. Se separa en dos tipos:
    # "opcion_simple" (una sola respuesta, igual que antes) y "opcion_multiple"
    # (ahora sí, varias marcadas a la vez). Todo lo que ya existía en la BD
    # con tipo 'opcion_multiple' era en realidad de una sola respuesta, así
    # que se renombra una única vez (marcador de columna para no repetir esta
    # migración si un admin crea preguntas nuevas de opción múltiple real
    # después).
    if "migrada_opcion_simple" not in cols_preguntas:
        conn.execute("ALTER TABLE encuesta_preguntas ADD COLUMN migrada_opcion_simple INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE encuesta_preguntas SET tipo = 'opcion_simple' WHERE tipo = 'opcion_multiple'")
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
    # Enlace a la fila que esta respuesta generó en Informes (o NULL si el
    # test no alimenta ningún tipo de Informe) — para poder llevar al admin
    # directamente a "cuál fue la respuesta registrada" desde "Ver respuestas"
    # en vez de solo el JSON crudo interno.
    cols_respuestas = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_respuestas)")}
    if "informe_respuesta_id" not in cols_respuestas:
        conn.execute("ALTER TABLE encuesta_respuestas ADD COLUMN informe_tipo_clave TEXT")
        conn.execute("ALTER TABLE encuesta_respuestas ADD COLUMN informe_hoja TEXT")
        conn.execute("ALTER TABLE encuesta_respuestas ADD COLUMN informe_respuesta_id INTEGER")
    # Notificación de "hay respuestas nuevas" junto al menú hamburguesa: por
    # usuario, guarda desde cuándo cuenta como "ya visto" — todo lo que llegó
    # después de esa marca es "nuevo". Al crear la tabla no hay fila para
    # nadie todavía; get_notificaciones_tests() la crea con la hora actual en
    # la primera llamada de cada usuario, así el historial ya acumulado no
    # aparece de golpe como "nuevo" la primera vez que alguien entra tras
    # desplegar esto.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notificaciones_vistas (
            usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
            visto_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    os.makedirs(FONDOS_DIR, exist_ok=True)


def get_notificaciones_tests(usuario_id):
    conn = get_connection()
    row = conn.execute("SELECT visto_en FROM notificaciones_vistas WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO notificaciones_vistas (usuario_id, visto_en) VALUES (?, datetime('now'))", (usuario_id,)
        )
        conn.commit()
        conn.close()
        return {"total": 0, "tests": []}
    visto_en = row["visto_en"]
    rows = conn.execute("""
        SELECT e.id, e.titulo, COUNT(r.id) AS nuevas
        FROM encuesta_respuestas r
        JOIN encuestas e ON e.id = r.encuesta_id
        WHERE r.creado_en > ?
        GROUP BY e.id
        ORDER BY MAX(r.creado_en) DESC
    """, (visto_en,)).fetchall()
    conn.close()
    tests = [{"id": r["id"], "titulo": r["titulo"], "nuevas": r["nuevas"]} for r in rows]
    return {"total": sum(t["nuevas"] for t in tests), "tests": tests}


def marcar_notificaciones_vistas(usuario_id):
    conn = get_connection()
    conn.execute("""
        INSERT INTO notificaciones_vistas (usuario_id, visto_en) VALUES (?, datetime('now'))
        ON CONFLICT(usuario_id) DO UPDATE SET visto_en = excluded.visto_en
    """, (usuario_id,))
    conn.commit()
    conn.close()


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
            qd["mostrar_dashboard"] = bool(qd["mostrar_dashboard"])
            preguntas_dict.append(qd)
        pd = dict(p)
        pd["condicion_valores"] = json.loads(pd.get("condicion_valores") or "[]")
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
    encuesta.pop("tipo_entrevista_empresa", None)
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


def update_encuesta(encuesta_id, titulo, mensaje_final, color_boton, tipo_informe_clave, tipo_entrevista_empresa=None):
    conn = get_connection()
    conn.execute(
        "UPDATE encuestas SET titulo = ?, mensaje_final = ?, color_boton = ?, tipo_informe_clave = ?, "
        "tipo_entrevista_empresa = ? WHERE id = ?",
        (titulo.strip(), mensaje_final.strip(), color_boton.strip(), tipo_informe_clave or None,
         tipo_entrevista_empresa or None, encuesta_id),
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


def add_pagina(encuesta_id, instrucciones="", condicion_pregunta_id=None, condicion_valores=None):
    conn = get_connection()
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO encuesta_paginas (encuesta_id, orden, instrucciones, condicion_pregunta_id, condicion_valores) "
        "VALUES (?, ?, ?, ?, ?)",
        (encuesta_id, orden, instrucciones, condicion_pregunta_id,
         json.dumps(condicion_valores or [], ensure_ascii=False)),
    )
    pagina_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pagina_id


def update_pagina(pagina_id, instrucciones, condicion_pregunta_id=None, condicion_valores=None):
    conn = get_connection()
    conn.execute(
        "UPDATE encuesta_paginas SET instrucciones = ?, condicion_pregunta_id = ?, condicion_valores = ? WHERE id = ?",
        (instrucciones, condicion_pregunta_id, json.dumps(condicion_valores or [], ensure_ascii=False), pagina_id),
    )
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


def add_pregunta(pagina_id, tipo, etiqueta, obligatoria=True, opciones=None, mostrar_dashboard=False):
    if tipo not in TIPOS_PREGUNTA:
        raise ValueError(f"Tipo de pregunta desconocido: {tipo}")
    conn = get_connection()
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 FROM encuesta_preguntas WHERE pagina_id = ?", (pagina_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO encuesta_preguntas (pagina_id, orden, tipo, etiqueta, obligatoria, opciones_json, mostrar_dashboard) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pagina_id, orden, tipo, etiqueta.strip(), 1 if obligatoria else 0,
         json.dumps(opciones or [], ensure_ascii=False), 1 if mostrar_dashboard else 0),
    )
    pregunta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pregunta_id


def update_pregunta(pregunta_id, etiqueta, obligatoria, opciones=None, mostrar_dashboard=False):
    conn = get_connection()
    conn.execute(
        "UPDATE encuesta_preguntas SET etiqueta = ?, obligatoria = ?, opciones_json = ?, mostrar_dashboard = ? WHERE id = ?",
        (etiqueta.strip(), 1 if obligatoria else 0, json.dumps(opciones or [], ensure_ascii=False),
         1 if mostrar_dashboard else 0, pregunta_id),
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


def mover_pregunta_a_pagina(pregunta_id, pagina_destino_id, antes_de_pregunta_id=None):
    """Mueve una pregunta a `pagina_destino_id` (puede ser la misma página en
    la que ya está, para simplemente reordenarla) e inserta justo antes de
    `antes_de_pregunta_id`, o al final si es None. Reconstruye el orden 1..N
    de la página destino entera (y de la de origen, si es distinta) en vez de
    solo desplazar huecos, para que quede siempre contiguo sin duplicados."""
    conn = get_connection()
    actual = conn.execute("SELECT * FROM encuesta_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    if not actual:
        conn.close()
        return
    pagina_origen_id = actual["pagina_id"]

    destino_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM encuesta_preguntas WHERE pagina_id = ? AND id != ? ORDER BY orden",
            (pagina_destino_id, pregunta_id),
        ).fetchall()
    ]
    indice = destino_ids.index(antes_de_pregunta_id) if antes_de_pregunta_id in destino_ids else len(destino_ids)
    destino_ids.insert(indice, pregunta_id)

    conn.execute("UPDATE encuesta_preguntas SET pagina_id = ? WHERE id = ?", (pagina_destino_id, pregunta_id))
    for i, pid in enumerate(destino_ids, start=1):
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (i, pid))
    if pagina_origen_id != pagina_destino_id:
        _renumerar_preguntas(conn, pagina_origen_id)
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
        SELECT eq.id, eq.etiqueta, eq.mostrar_dashboard FROM encuesta_preguntas eq
        JOIN encuesta_paginas ep ON ep.id = eq.pagina_id
        WHERE ep.encuesta_id = ?
        ORDER BY ep.orden, eq.orden
    """, (encuesta_id,)).fetchall()
    etiqueta_por_id = {str(p["id"]): p["etiqueta"] for p in preguntas}
    mostrar_dashboard_por_id = {str(p["id"]): bool(p["mostrar_dashboard"]) for p in preguntas}

    # Dos preguntas pueden compartir el mismo enunciado a propósito (p.ej. la
    # misma pregunta de "Ordena las siguientes afirmaciones..." repetida en
    # varias páginas con distintas frases, tal cual el test real de Krispy
    # Kreme) — un dict simple perdería todas menos la última. Se numeran las
    # repetidas; el motor de scoring solo busca que el texto CONTENGA la
    # palabra clave, así que el sufijo no rompe la detección.
    #
    # columnas_extra: preguntas marcadas por el admin como "mostrar en el
    # dashboard" — no cambia su puntuación, pero Informes las copia tal cual
    # a Scoring/Dashboard para verlas de un vistazo (ver
    # scoring_valores.calcular()).
    fila_por_etiqueta = {}
    columnas_extra = set()
    for pid, etiqueta in etiqueta_por_id.items():
        if pid not in respuestas_por_pregunta:
            continue
        valor = respuestas_por_pregunta[pid]
        clave = etiqueta
        sufijo = 2
        while clave in fila_por_etiqueta:
            clave = f"{etiqueta} ({sufijo})"
            sufijo += 1
        fila_por_etiqueta[clave] = valor
        if mostrar_dashboard_por_id[pid]:
            columnas_extra.add(clave)

    dispositivo = _detectar_dispositivo(user_agent)
    cur = conn.execute(
        "INSERT INTO encuesta_respuestas (encuesta_id, datos_json, ip, user_agent, dispositivo) VALUES (?, ?, ?, ?, ?)",
        (encuesta_id, json.dumps(fila_por_etiqueta, ensure_ascii=False, default=str), ip, user_agent, dispositivo),
    )
    respuesta_id = cur.lastrowid
    conn.commit()
    conn.close()

    if tipo_informe_clave:
        # "Fecha del test" solo se manda a Informes (no se guarda en el
        # datos_json interno de encuesta_respuestas, que ya tiene su propio
        # creado_en) — scoring_valores._detectar_fecha la reconoce por su
        # nombre exacto y así no confunde con ella ninguna pregunta cuyo
        # enunciado contenga "fecha"/"hora" de pasada.
        fila_para_informes = dict(fila_por_etiqueta)
        # A diferencia de creado_en (que se guarda en UTC y se convierte a
        # hora local en el navegador al mostrarlo, ver tests.js
        # formatearFechaHoraLocal), esta columna se copia tal cual dentro de
        # datos_json y se muestra literal en Informes — por eso aquí hace
        # falta calcular ya la hora local, o se ve 2h por detrás de la real.
        fila_para_informes["Fecha del test"] = datetime.datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")
        enlace = informes_module.ingest_fila_directa(
            tipo_informe_clave, fila_para_informes, origen=f"Test web: {row['titulo']}", columnas_extra=columnas_extra
        )
        if enlace.get("respuesta_id"):
            conn2 = get_connection()
            conn2.execute(
                "UPDATE encuesta_respuestas SET informe_tipo_clave = ?, informe_hoja = ?, informe_respuesta_id = ? WHERE id = ?",
                (enlace["tipo_clave"], enlace["hoja"], enlace["respuesta_id"], respuesta_id),
            )
            conn2.commit()
            conn2.close()
    if row["tipo_entrevista_empresa"]:
        entrevistas_module.ingest_fila_directa(
            row["tipo_entrevista_empresa"], fila_por_etiqueta, origen=f"Test web: {row['titulo']}"
        )

    return {"ok": True}


def list_respuestas(encuesta_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, datos_json, ip, user_agent, dispositivo, creado_en, "
        "informe_tipo_clave, informe_hoja, informe_respuesta_id FROM encuesta_respuestas "
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
