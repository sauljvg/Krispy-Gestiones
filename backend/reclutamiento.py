import datetime
import json
import os
import re
import unicodedata

from db import DATA_DIR, get_connection

UPLOADS_DIR = os.path.join(DATA_DIR, "uploads", "candidatos")

ESTADOS = ["pendiente", "entrevistado", "contratado", "descartado"]

VACANTE_ESTADOS = ["abierta", "cubierta", "cancelada"]

# Estado del contacto humano (llamada/WhatsApp) con el candidato -- se marca
# a mano, distinto de "estado" (que es la fase del proceso de selección) y
# de invitado_test_en/respuesta_id (que es sobre el TEST, no sobre hablar
# con la persona).
CONTACTO_ESTADOS = ["sin_contactar", "contactado", "respondio"]

# Campos "conocidos" del candidato — el resto de datos (de un CV, de un
# Excel de Informes o de un alta manual) se guarda en extra_fields (JSON),
# igual que el patrón extraFields de BBDD SV.
CAMPOS = [
    "nombre_completo", "telefono", "email", "direccion", "fecha_nacimiento",
    "dni", "formacion", "experiencia", "disponibilidad", "puesto_solicitado",
    "fecha_solicitud", "estado", "notas",
]

FIELD_LABELS = {
    "nombre_completo": "Nombre completo",
    "telefono": "Teléfono",
    "email": "Email",
    "direccion": "Dirección",
    "fecha_nacimiento": "Fecha de nacimiento",
    "dni": "DNI/NIE",
    "formacion": "Formación",
    "experiencia": "Experiencia",
    "disponibilidad": "Disponibilidad",
    "puesto_solicitado": "Puesto al que aplica",
    "fecha_solicitud": "Fecha de solicitud",
    "estado": "Estado",
    "notas": "Notas",
}

# Usado para mapear las columnas libres de un Excel de Informes (datos_json)
# a los campos conocidos del candidato, por coincidencia de substring en el
# nombre de columna (minúsculas, sin acentos no se normaliza aquí porque los
# propios Excel ya vienen con acentos consistentes). Primer campo que
# coincide gana esa columna; cada campo solo se rellena una vez (la primera
# columna que lo alcance).
FIELD_HINTS = [
    ("nombre_completo", ["nombre y apellido", "nombre completo", "nombre"]),
    ("telefono", ["teléfono", "telefono", "móvil", "movil"]),
    ("email", ["correo electrónico", "correo electronico", "correo", "email", "e-mail"]),
    ("direccion", ["dirección", "direccion", "domicilio"]),
    ("fecha_nacimiento", ["fecha de nacimiento", "nacimiento"]),
    ("dni", ["dni", "nie"]),
    ("formacion", ["formación", "formacion", "estudios", "educación", "educacion"]),
    ("experiencia", ["experiencia"]),
    ("disponibilidad", ["disponibilidad"]),
    ("puesto_solicitado", ["puesto", "posición", "posicion", "vacante"]),
    ("fecha_solicitud", ["fecha de solicitud", "fecha de aplicación", "fecha de aplicacion"]),
]


def ensure_reclutamiento_tables():
    conn = get_connection()
    # vacantes agrupa candidatos bajo una solicitud de reclutamiento concreta
    # (p.ej. "Ayudante de Cocina en SAONA Madnum") — fecha_solicitud es
    # cuándo se pidió cubrir el puesto (para medir cuánto lleva abierta) y
    # fecha_cierre se rellena sola al marcarla cubierta o cancelada (para
    # medir cuánto tardó en cubrirse). Un candidato puede no tener vacante
    # (candidatura espontánea, o los que llegan compartidos desde Informes).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vacantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            puesto TEXT NOT NULL,
            centro TEXT,
            estado TEXT NOT NULL DEFAULT 'abierta',
            notas TEXT,
            fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now')),
            fecha_cierre TEXT,
            creado_por TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            vacante_id INTEGER REFERENCES vacantes(id),
            nombre_completo TEXT,
            telefono TEXT,
            email TEXT,
            direccion TEXT,
            fecha_nacimiento TEXT,
            dni TEXT,
            formacion TEXT,
            experiencia TEXT,
            disponibilidad TEXT,
            puesto_solicitado TEXT,
            fecha_solicitud TEXT,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            notas TEXT,
            extra_fields TEXT NOT NULL DEFAULT '{}',
            origen TEXT NOT NULL DEFAULT 'manual',
            respuesta_id INTEGER UNIQUE REFERENCES informe_respuestas(id),
            creado_por TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now')),
            actualizado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cols_candidatos = {row[1] for row in conn.execute("PRAGMA table_info(candidatos)")}
    if "vacante_id" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN vacante_id INTEGER REFERENCES vacantes(id)")
    if "foto_ruta" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN foto_ruta TEXT")
    if "invitado_test_en" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN invitado_test_en TEXT")
    if "invitado_test_encuesta_id" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN invitado_test_encuesta_id INTEGER")
    if "contacto_estado" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN contacto_estado TEXT NOT NULL DEFAULT 'sin_contactar'")
    # formacion_json/experiencia_json: historial estructurado (título/centro/
    # fechas por estudio, puesto/empresa/fechas/descripción por experiencia),
    # como en un perfil de InfoJobs -- reemplaza a formacion/experiencia
    # (un único bloque de texto libre) para las fichas nuevas. Esas dos
    # columnas de texto se conservan tal cual para no perder lo ya extraído
    # de CVs antiguos; la ficha las sigue mostrando como aviso de "dato
    # antiguo" mientras no haya historial estructurado.
    if "formacion_json" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN formacion_json TEXT")
    if "experiencia_json" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN experiencia_json TEXT")
    # Backfill de fecha_solicitud vacía con la fecha en la que se dio de alta
    # la ficha -- es una aproximación razonable (normalmente se sube el mismo
    # día que se recibe la solicitud) y evita dejar el campo en blanco en
    # fichas ya existentes. Idempotente, se puede ejecutar en cada arranque.
    conn.execute("""
        UPDATE candidatos SET fecha_solicitud = substr(creado_en, 1, 10)
        WHERE fecha_solicitud IS NULL OR fecha_solicitud = ''
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidato_archivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidato_id INTEGER NOT NULL REFERENCES candidatos(id) ON DELETE CASCADE,
            nombre_original TEXT NOT NULL,
            ruta TEXT NOT NULL,
            subido_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Compartir un candidato directo desde Reclutamiento (sin pasar por un
    # test de Informes) — paralela a informe_compartidos, que exige un
    # respuesta_id y por eso no sirve para candidatos que llegaron por CV o
    # alta manual. Las dos se fusionan al leer "Compartidos" (ver
    # informes.get_compartidos_con/por) para que el gerente las vea juntas.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidato_compartidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidato_id INTEGER NOT NULL REFERENCES candidatos(id) ON DELETE CASCADE,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            compartido_por TEXT,
            compartido_en TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(candidato_id, usuario_id)
        )
    """)
    # Compartir a nivel de SOLICITUD (vacante), no de candidato suelto -- el
    # problema que resuelve: si compartes 5 candidatos uno a uno (o en
    # momentos distintos) a Heber, candidato_compartidos genera 5 "slots"
    # separados sin relación entre sí, y si mañana se añade un candidato más
    # a esa vacante, habría que acordarse de compartirlo también. Añadir un
    # usuario aquí como responsable de la vacante le da acceso a TODOS sus
    # candidatos de golpe, presentes y futuros -- un único sitio donde tanto
    # quien comparte como los gerentes ven todo junto (ver
    # get_vacantes_compartidas_con/por). usuario_tiene_acceso_candidato
    # también lo consulta para la ficha individual.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vacante_compartidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vacante_id INTEGER NOT NULL REFERENCES vacantes(id) ON DELETE CASCADE,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            compartido_por TEXT,
            compartido_en TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(vacante_id, usuario_id)
        )
    """)
    conn.commit()
    conn.close()


def list_vacantes(empresa=None, estado=None):
    conn = get_connection()
    clauses = []
    params = []
    if empresa:
        clauses.append("v.empresa = ?")
        params.append(empresa)
    if estado:
        clauses.append("v.estado = ?")
        params.append(estado)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"""
        SELECT v.*, COUNT(c.id) AS candidato_count
        FROM vacantes v
        LEFT JOIN candidatos c ON c.vacante_id = v.id
        {where}
        GROUP BY v.id
        ORDER BY v.estado = 'abierta' DESC, v.fecha_solicitud DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_gerentes_de_vacante(vacante_id, conn=None):
    propia = conn is None
    if propia:
        conn = get_connection()
    rows = conn.execute("""
        SELECT vc.usuario_id AS usuario_id, u.nombre AS nombre
        FROM vacante_compartidos vc JOIN usuarios u ON u.id = vc.usuario_id
        WHERE vc.vacante_id = ?
        ORDER BY u.nombre
    """, (vacante_id,)).fetchall()
    if propia:
        conn.close()
    return [dict(r) for r in rows]


def get_vacante(vacante_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM vacantes WHERE id = ?", (vacante_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    vacante = dict(row)
    vacante["gerentes"] = get_gerentes_de_vacante(vacante_id, conn)
    conn.close()
    vacante["candidatos"] = list_candidatos(vacante_id=vacante_id)
    return vacante


def compartir_vacante(vacante_id, usuario_ids: list[int], compartido_por):
    """Asigna a uno o más gerentes/responsables como encargados de TODA la
    solicitud -- a diferencia de compartir_candidatos_directo (candidato a
    candidato), esto da acceso a todos sus candidatos de una vez, presentes
    y los que se añadan después (ver usuario_tiene_acceso_candidato)."""
    if not usuario_ids:
        return
    conn = get_connection()
    for usuario_id in usuario_ids:
        conn.execute(
            """
            INSERT INTO vacante_compartidos (vacante_id, usuario_id, compartido_por)
            VALUES (?, ?, ?)
            ON CONFLICT(vacante_id, usuario_id)
            DO UPDATE SET compartido_por = excluded.compartido_por, compartido_en = datetime('now')
            """,
            (vacante_id, usuario_id, compartido_por),
        )
    conn.commit()
    conn.close()


def dejar_de_compartir_vacante(vacante_id, usuario_id):
    conn = get_connection()
    conn.execute(
        "DELETE FROM vacante_compartidos WHERE vacante_id = ? AND usuario_id = ?", (vacante_id, usuario_id)
    )
    conn.commit()
    conn.close()


def usuario_tiene_acceso_vacante(usuario_id, vacante_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM vacante_compartidos WHERE vacante_id = ? AND usuario_id = ?", (vacante_id, usuario_id)
    ).fetchone()
    conn.close()
    return row is not None


def get_vacantes_compartidas_con(usuario_id, empresa=None):
    """Vacantes donde este usuario es responsable -- para "Compartidos
    conmigo", en vez de fichas sueltas agrupadas por cuándo se compartieron,
    aquí se ve la solicitud completa con TODOS sus candidatos juntos."""
    conn = get_connection()
    clauses = ["vc.usuario_id = ?"]
    params = [usuario_id]
    if empresa:
        clauses.append("v.empresa = ?")
        params.append(empresa)
    rows = conn.execute(f"""
        SELECT v.*, vc.compartido_en, vc.compartido_por
        FROM vacante_compartidos vc JOIN vacantes v ON v.id = vc.vacante_id
        WHERE {' AND '.join(clauses)}
        ORDER BY vc.compartido_en DESC
    """, params).fetchall()
    resultado = []
    for r in rows:
        vacante = dict(r)
        vacante["gerentes"] = get_gerentes_de_vacante(vacante["id"], conn)
        resultado.append(vacante)
    conn.close()
    for vacante in resultado:
        vacante["candidatos"] = list_candidatos(vacante_id=vacante["id"])
    return resultado


def get_vacantes_compartidas_por(username, empresa=None):
    """Vacantes que ESTE usuario ha compartido con algún gerente -- una fila
    por vacante (no una por gerente), con la lista completa de a quiénes se
    la compartió."""
    conn = get_connection()
    clauses = ["vc.compartido_por = ?"]
    params = [username]
    if empresa:
        clauses.append("v.empresa = ?")
        params.append(empresa)
    rows = conn.execute(f"""
        SELECT DISTINCT v.*
        FROM vacante_compartidos vc JOIN vacantes v ON v.id = vc.vacante_id
        WHERE {' AND '.join(clauses)}
        ORDER BY v.id DESC
    """, params).fetchall()
    resultado = []
    for r in rows:
        vacante = dict(r)
        vacante["gerentes"] = get_gerentes_de_vacante(vacante["id"], conn)
        resultado.append(vacante)
    conn.close()
    for vacante in resultado:
        vacante["candidatos"] = list_candidatos(vacante_id=vacante["id"])
    return resultado


def crear_vacante(empresa, puesto, centro=None, notas=None, creado_por=None):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO vacantes (empresa, puesto, centro, notas, creado_por) VALUES (?, ?, ?, ?, ?)",
        (empresa, puesto, centro, notas, creado_por),
    )
    vacante_id = cur.lastrowid
    conn.commit()
    conn.close()
    return vacante_id


def actualizar_vacante(vacante_id, campos: dict):
    if not campos:
        return
    sets = []
    params = []
    for campo in ("puesto", "centro", "notas"):
        if campo in campos:
            sets.append(f"{campo} = ?")
            params.append(campos[campo])
    if "estado" in campos:
        sets.append("estado = ?")
        params.append(campos["estado"])
        # fecha_cierre refleja cuándo se cubrió/canceló la vacante — se
        # limpia si se reabre, para que no quede una fecha de cierre falsa.
        if campos["estado"] == "abierta":
            sets.append("fecha_cierre = NULL")
        else:
            sets.append("fecha_cierre = datetime('now')")
    if not sets:
        return
    params.append(vacante_id)
    conn = get_connection()
    conn.execute(f"UPDATE vacantes SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def eliminar_vacante(vacante_id):
    """Borra la vacante pero conserva los candidatos ya creados (quedan
    "sin vacante asignada" en vez de perderse). SQLite no aplica ON DELETE
    CASCADE salvo que se active PRAGMA foreign_keys (no está activado en
    esta conexión), así que vacante_compartidos se limpia a mano."""
    conn = get_connection()
    conn.execute("UPDATE candidatos SET vacante_id = NULL WHERE vacante_id = ?", (vacante_id,))
    conn.execute("DELETE FROM vacante_compartidos WHERE vacante_id = ?", (vacante_id,))
    conn.execute("DELETE FROM vacantes WHERE id = ?", (vacante_id,))
    conn.commit()
    conn.close()


def fusionar_vacantes(origen_id, destino_id):
    """Junta dos solicitudes que en realidad son el mismo proceso -- p.ej.
    candidatos que se fueron compartiendo sueltos con el mismo gerente en
    momentos distintos y acabaron sin agrupar bajo una única vacante. Mueve
    todos los candidatos de origen a destino y borra origen; destino
    conserva su fecha_solicitud/notas tal cual (no se intenta fusionar ese
    contenido, solo la lista de candidatos)."""
    if origen_id == destino_id:
        return
    conn = get_connection()
    conn.execute("UPDATE candidatos SET vacante_id = ? WHERE vacante_id = ?", (destino_id, origen_id))
    # Los responsables de origen también deberían seguir teniendo acceso
    # tras la fusión -- se copian a destino (ON CONFLICT por si alguien ya
    # era responsable de ambas). SQLite no aplica ON DELETE CASCADE en esta
    # conexión, así que además se limpian a mano antes de borrar origen.
    for row in conn.execute("SELECT usuario_id, compartido_por FROM vacante_compartidos WHERE vacante_id = ?", (origen_id,)).fetchall():
        conn.execute(
            """
            INSERT INTO vacante_compartidos (vacante_id, usuario_id, compartido_por)
            VALUES (?, ?, ?)
            ON CONFLICT(vacante_id, usuario_id) DO NOTHING
            """,
            (destino_id, row["usuario_id"], row["compartido_por"]),
        )
    conn.execute("DELETE FROM vacante_compartidos WHERE vacante_id = ?", (origen_id,))
    conn.execute("DELETE FROM vacantes WHERE id = ?", (origen_id,))
    conn.commit()
    conn.close()


def _row_to_dict(row):
    d = dict(row)
    d["extra_fields"] = json.loads(d.get("extra_fields") or "{}")
    d["formacion_json"] = json.loads(d.get("formacion_json") or "[]")
    d["experiencia_json"] = json.loads(d.get("experiencia_json") or "[]")
    # No se expone la ruta de disco tal cual (igual que cv_ruta en
    # informes.py) -- solo si hay foto o no; la propia foto se sirve por su
    # endpoint dedicado (GET /candidatos/{id}/foto).
    d["tiene_foto"] = bool(d.pop("foto_ruta", None))
    # Si ya respondió al test, por definición ya hubo contacto -- no tiene
    # sentido seguir mostrando "Sin contactar" y obligar a marcarlo a mano.
    # No se pisa una escalada manual a "respondio" (contacto humano
    # confirmado aparte del test).
    if d.get("respuesta_id") and d.get("contacto_estado") == "sin_contactar":
        d["contacto_estado"] = "contactado"
    return d


def mapear_datos_a_candidato(datos: dict):
    """Reparte las columnas libres de una fila de Informes (datos_json) entre
    los campos conocidos del candidato y un diccionario 'extra' con el resto,
    para poder crear un candidato editable a partir de un Excel importado."""
    campos = {}
    extra = {}
    for clave, valor in datos.items():
        if valor in (None, ""):
            continue
        clave_baja = clave.lower()
        destino = None
        for campo, keywords in FIELD_HINTS:
            if campo in campos:
                continue
            if any(kw in clave_baja for kw in keywords):
                destino = campo
                break
        if destino:
            campos[destino] = valor
        else:
            extra[clave] = valor
    return campos, extra


def _compartidos_por_candidato(conn, candidato_ids):
    """Para cada candidato de la lista, quién ya lo tiene compartido -- une
    los dos caminos de compartir (candidato_compartidos, directo desde
    Reclutamiento, e informe_compartidos, que también guarda candidato_id
    desde que existe el enlace automático con el test) para poder avisar
    "ya compartido con X" sin importar por cuál de los dos caminos se hizo."""
    if not candidato_ids:
        return {}
    placeholders = ",".join("?" * len(candidato_ids))
    rows = conn.execute(f"""
        SELECT candidato_id, usuario_id, usuario_nombre FROM (
            SELECT cc.candidato_id AS candidato_id, cc.usuario_id AS usuario_id, u.nombre AS usuario_nombre
            FROM candidato_compartidos cc JOIN usuarios u ON u.id = cc.usuario_id
            WHERE cc.candidato_id IN ({placeholders})
            UNION
            SELECT ic.candidato_id AS candidato_id, ic.usuario_id AS usuario_id, u.nombre AS usuario_nombre
            FROM informe_compartidos ic JOIN usuarios u ON u.id = ic.usuario_id
            WHERE ic.candidato_id IN ({placeholders})
        )
    """, candidato_ids + candidato_ids).fetchall()
    mapa = {}
    for r in rows:
        mapa.setdefault(r["candidato_id"], []).append({"usuario_id": r["usuario_id"], "nombre": r["usuario_nombre"]})
    return mapa


def get_candidato(candidato_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM candidatos WHERE id = ?", (candidato_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    candidato = _row_to_dict(row)
    candidato["compartidos"] = _compartidos_por_candidato(conn, [candidato_id]).get(candidato_id, [])
    # puesto/centro de la vacante (si tiene) -- un responsable de vacante sin
    # el módulo completo no tiene la lista de vacantes cargada en el
    # frontend para resolver el nombre por su cuenta, así que se manda ya
    # resuelto (evita además que el <select> de la ficha "pierda" la vacante
    # asignada al no encontrarla en una lista vacía y la desasigne sin
    # querer al guardar).
    if candidato.get("vacante_id"):
        vacante_row = conn.execute("SELECT puesto, centro FROM vacantes WHERE id = ?", (candidato["vacante_id"],)).fetchone()
        if vacante_row:
            candidato["vacante_puesto"] = vacante_row["puesto"]
            candidato["vacante_centro"] = vacante_row["centro"]
    archivos = conn.execute(
        "SELECT id, nombre_original, subido_en FROM candidato_archivos WHERE candidato_id = ? ORDER BY subido_en DESC",
        (candidato_id,),
    ).fetchall()
    # Si esta ficha está enlazada a una respuesta de Informes (por "compartir"
    # o por el match automático de guardar_respuesta), se expone también el
    # tipo/hoja para que el frontend pueda armar el enlace directo al
    # resultado — sin esto, respuesta_id es solo un número sin ningún sitio
    # al que llevar al usuario.
    if candidato.get("respuesta_id"):
        info = conn.execute("""
            SELECT t.clave AS tipo_clave, t.empresa, r.hoja, r.datos_json,
                   json_extract(r.datos_json, '$.RESULTADO') AS test_resultado
            FROM informe_respuestas r JOIN informe_tipos t ON t.id = r.tipo_id
            WHERE r.id = ?
        """, (candidato["respuesta_id"],)).fetchone()
        if info:
            candidato["informe_tipo_clave"] = info["tipo_clave"]
            candidato["informe_hoja"] = info["hoja"]
            candidato["informe_empresa"] = info["empresa"]
            candidato["test_resultado"] = info["test_resultado"]
            # Las preguntas/respuestas del test enlazado (Dashboard de
            # Informes) -- hoy se capta esta info al compartir/enlazar pero
            # se queda sin ver en la ficha del candidato; se expone aquí tal
            # cual (pregunta -> respuesta) para mostrarla de forma
            # de solo lectura.
            candidato["respuesta_datos"] = json.loads(info["datos_json"])
    conn.close()
    candidato["archivos"] = [dict(a) for a in archivos]
    return candidato


def get_candidato_por_respuesta(respuesta_id):
    conn = get_connection()
    row = conn.execute("SELECT id FROM candidatos WHERE respuesta_id = ?", (respuesta_id,)).fetchone()
    conn.close()
    return row["id"] if row else None


def _normalizar_telefono(telefono):
    return re.sub(r"\D", "", telefono or "")


def _ultimos_9_digitos(telefono):
    """Compara solo los últimos 9 dígitos (formato de móvil español) en vez
    del número normalizado completo — si un lado guarda el prefijo de país
    (+34, 0034...) y el otro no, con una igualdad exacta nunca habrían
    coincidido aunque sea la misma persona. Devuelve None si hay menos de 9
    dígitos, para no cruzar por accidente dos números incompletos."""
    digitos = _normalizar_telefono(telefono)
    return digitos[-9:] if len(digitos) >= 9 else None


def buscar_candidato_sin_respuesta_por_contacto(telefono, email):
    """Busca en Reclutamiento un candidato YA EXISTENTE (creado a mano, por CV
    o por una vacante) que coincida por teléfono o correo con quien acaba de
    responder un test — y que todavía no tenga ningún test enlazado. Así, si
    Bianca Burbano ya está en la base de candidatos y ahora rellena el test,
    se enlaza a su misma ficha en vez de quedar suelto hasta que alguien lo
    comparta a mano desde Informes. No toca candidatos que ya tengan un
    respuesta_id (para no perder un enlace anterior)."""
    tel_norm = _ultimos_9_digitos(telefono)
    email_norm = (email or "").strip().lower()
    if not tel_norm and not email_norm:
        return None
    conn = get_connection()
    candidatos = conn.execute(
        "SELECT id, telefono, email FROM candidatos WHERE respuesta_id IS NULL"
    ).fetchall()
    conn.close()
    for c in candidatos:
        if tel_norm and _ultimos_9_digitos(c["telefono"]) == tel_norm:
            return c["id"]
        if email_norm and (c["email"] or "").strip().lower() == email_norm:
            return c["id"]
    return None


def buscar_respuesta_huerfana_por_contacto(telefono, email):
    """Simétrico al anterior: cuando el candidato se da de alta en
    Reclutamiento DESPUÉS de que la persona ya hubiera respondido el test
    (p.ej. una importación de candidatos de una vacante), busca entre las
    respuestas de test que todavía no están enlazadas a ningún candidato una
    que coincida por teléfono o correo. Sin esto, el enlace automático solo
    funcionaba en un sentido (respuesta nueva -> candidato existente) y una
    importación posterior se quedaba huérfana para siempre."""
    tel_norm = _ultimos_9_digitos(telefono)
    email_norm = (email or "").strip().lower()
    if not tel_norm and not email_norm:
        return None
    conn = get_connection()
    rows = conn.execute("""
        SELECT r.id, r.datos_json FROM informe_respuestas r
        LEFT JOIN candidatos c ON c.respuesta_id = r.id
        WHERE c.id IS NULL
    """).fetchall()
    conn.close()
    for r in rows:
        datos = json.loads(r["datos_json"])
        campos, _ = mapear_datos_a_candidato(datos)
        if tel_norm and _ultimos_9_digitos(campos.get("telefono")) == tel_norm:
            return r["id"]
        if email_norm and (campos.get("email") or "").strip().lower() == email_norm:
            return r["id"]
    return None


def enlazar_respuesta_a_candidato(candidato_id, respuesta_id):
    conn = get_connection()
    conn.execute(
        "UPDATE candidatos SET respuesta_id = ?, actualizado_en = datetime('now') WHERE id = ?",
        (respuesta_id, candidato_id),
    )
    conn.commit()
    conn.close()


def list_candidatos(empresa=None, estado=None, q=None, vacante_id=None, sin_vacante=False):
    conn = get_connection()
    clauses = []
    params = []
    if empresa:
        clauses.append("c.empresa = ?")
        params.append(empresa)
    if estado:
        clauses.append("c.estado = ?")
        params.append(estado)
    if vacante_id is not None:
        clauses.append("c.vacante_id = ?")
        params.append(vacante_id)
    elif sin_vacante:
        clauses.append("c.vacante_id IS NULL")
    if q:
        clauses.append("(c.nombre_completo LIKE ? OR c.telefono LIKE ? OR c.email LIKE ? OR c.puesto_solicitado LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # test_resultado viene de la respuesta de Valores y Competencias enlazada
    # (si la hay) — así el listado puede mostrar el mismo check de apto/no
    # apto que ya se ve en Informes, sin que el frontend tenga que pedirlo
    # aparte candidato a candidato.
    rows = conn.execute(f"""
        SELECT c.*, json_extract(r.datos_json, '$.RESULTADO') AS test_resultado
        FROM candidatos c
        LEFT JOIN informe_respuestas r ON r.id = c.respuesta_id
        {where}
        ORDER BY c.actualizado_en DESC
    """, params).fetchall()
    candidatos = [_row_to_dict(r) for r in rows]
    mapa_compartidos = _compartidos_por_candidato(conn, [c["id"] for c in candidatos])
    conn.close()
    for c in candidatos:
        c["compartidos"] = mapa_compartidos.get(c["id"], [])
    return candidatos


def normalizar_nombre(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def buscar_candidato_por_nombre(empresa, nombre):
    """Busca una ficha YA EXISTENTE por nombre completo (normalizado, sin
    acentos/mayúsculas/espacios de más) -- se usa para adjuntar
    retroactivamente un PDF por lotes a las fichas que ya se crearon a
    partir de ese mismo PDF (ver /candidatos/adjuntar-pdf-lote), sin volver
    a crear a nadie. Coincidencia exacta a propósito: un match aproximado
    podría adjuntar el CV de una persona a la ficha de otra."""
    objetivo = normalizar_nombre(nombre)
    if not objetivo:
        return None
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, nombre_completo FROM candidatos WHERE empresa = ?", (empresa,)
    ).fetchall()
    conn.close()
    for row in rows:
        if row["nombre_completo"] and normalizar_nombre(row["nombre_completo"]) == objetivo:
            return row["id"]
    return None


def crear_candidato(campos: dict, empresa="kk", origen="manual", respuesta_id=None, creado_por=None, vacante_id=None):
    extra_fields = campos.pop("extra_fields", {}) or {}
    formacion_json = campos.pop("formacion_json", None)
    experiencia_json = campos.pop("experiencia_json", None)
    # Si no se indica fecha de solicitud, se asume la de hoy -- lo normal es
    # que la ficha se dé de alta el mismo día que se recibe la solicitud.
    if not campos.get("fecha_solicitud"):
        campos["fecha_solicitud"] = datetime.date.today().isoformat()
    # Si no viene ya con una respuesta enlazada (alta manual, CV o
    # importación de una vacante), se comprueba si esta persona ya había
    # respondido un test antes de tener ficha en Reclutamiento — ver
    # buscar_respuesta_huerfana_por_contacto.
    if respuesta_id is None:
        respuesta_id = buscar_respuesta_huerfana_por_contacto(campos.get("telefono"), campos.get("email"))
    valores = {c: campos.get(c) for c in CAMPOS if c in campos}
    conn = get_connection()
    columnas = ["empresa", "origen", "respuesta_id", "creado_por", "extra_fields", "vacante_id",
                "formacion_json", "experiencia_json"] + list(valores.keys())
    placeholders = ", ".join("?" for _ in columnas)
    params = [
        empresa, origen, respuesta_id, creado_por, json.dumps(extra_fields, ensure_ascii=False), vacante_id,
        json.dumps(formacion_json or [], ensure_ascii=False), json.dumps(experiencia_json or [], ensure_ascii=False),
    ] + list(valores.values())
    cur = conn.execute(
        f"INSERT INTO candidatos ({', '.join(columnas)}) VALUES ({placeholders})", params
    )
    candidato_id = cur.lastrowid
    conn.commit()
    conn.close()
    return candidato_id


def revincular_candidatos_existentes():
    """Re-escanea TODOS los candidatos sin test enlazado en busca de una
    respuesta huérfana que coincida — para poner al día de golpe a quienes
    ya estaban en Reclutamiento antes de que este enlace bidireccional
    existiera (p.ej. una vacante importada antes de este cambio). Se llama a
    mano desde un botón, no en cada arranque, porque recorre todas las
    respuestas de test sin enlazar y puede ser una operación algo pesada."""
    conn = get_connection()
    candidatos = conn.execute(
        "SELECT id, telefono, email FROM candidatos WHERE respuesta_id IS NULL"
    ).fetchall()
    conn.close()
    enlazados = 0
    for c in candidatos:
        respuesta_id = buscar_respuesta_huerfana_por_contacto(c["telefono"], c["email"])
        if respuesta_id:
            enlazar_respuesta_a_candidato(c["id"], respuesta_id)
            enlazados += 1
    return enlazados


def actualizar_candidato(candidato_id, campos: dict):
    if not campos:
        return
    sets = []
    params = []
    if "extra_fields" in campos:
        sets.append("extra_fields = ?")
        params.append(json.dumps(campos.pop("extra_fields") or {}, ensure_ascii=False))
    if "vacante_id" in campos:
        sets.append("vacante_id = ?")
        params.append(campos.pop("vacante_id"))
    if "contacto_estado" in campos:
        sets.append("contacto_estado = ?")
        params.append(campos.pop("contacto_estado"))
    if "formacion_json" in campos:
        sets.append("formacion_json = ?")
        params.append(json.dumps(campos.pop("formacion_json") or [], ensure_ascii=False))
    if "experiencia_json" in campos:
        sets.append("experiencia_json = ?")
        params.append(json.dumps(campos.pop("experiencia_json") or [], ensure_ascii=False))
    for campo in CAMPOS:
        if campo in campos:
            sets.append(f"{campo} = ?")
            params.append(campos[campo])
    if not sets:
        return
    sets.append("actualizado_en = datetime('now')")
    params.append(candidato_id)
    conn = get_connection()
    conn.execute(f"UPDATE candidatos SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def actualizar_estado_multiple(candidato_ids: list[int], estado: str):
    if not candidato_ids:
        return
    conn = get_connection()
    placeholders = ", ".join("?" for _ in candidato_ids)
    conn.execute(
        f"UPDATE candidatos SET estado = ?, actualizado_en = datetime('now') WHERE id IN ({placeholders})",
        [estado, *candidato_ids],
    )
    conn.commit()
    conn.close()


def actualizar_vacante_multiple(candidato_ids: list[int], vacante_id):
    """Asigna en un solo paso una solicitud (vacante) a varios candidatos ya
    existentes -- pensado para agrupar bajo el mismo proceso a gente que se
    fue compartiendo suelta en momentos distintos (ver fusionar_vacantes
    para el caso de dos solicitudes ya creadas por separado). vacante_id
    puede ser None para "quitar de la vacante"."""
    if not candidato_ids:
        return
    conn = get_connection()
    placeholders = ", ".join("?" for _ in candidato_ids)
    conn.execute(
        f"UPDATE candidatos SET vacante_id = ?, actualizado_en = datetime('now') WHERE id IN ({placeholders})",
        [vacante_id, *candidato_ids],
    )
    conn.commit()
    conn.close()


def marcar_invitados_test(candidato_ids: list[int], encuesta_id: int):
    """Registra que se les acaba de generar un enlace de test por WhatsApp a
    estos candidatos -- no hay forma de saber si de verdad se envió (el
    envío es manual, fuera del sistema, ver abrirCampanaWhatsapp), así que
    esto es una aproximación de "se intentó contactar", suficiente para
    poder distinguir luego "invitado pero sin respuesta todavía" (para el
    recordatorio) de "nunca se le mandó nada"."""
    if not candidato_ids:
        return
    conn = get_connection()
    placeholders = ", ".join("?" for _ in candidato_ids)
    conn.execute(
        f"UPDATE candidatos SET invitado_test_en = datetime('now'), invitado_test_encuesta_id = ? WHERE id IN ({placeholders})",
        [encuesta_id, *candidato_ids],
    )
    conn.commit()
    conn.close()


def contar_por_estado(empresa=None, q=None, vacante_id=None, sin_vacante=False):
    """Conteo de candidatos por estado con los mismos filtros que
    list_candidatos (menos el propio estado) — alimenta los números de cada
    pestaña en la vista de Reclutamiento."""
    conn = get_connection()
    clauses = []
    params = []
    if empresa:
        clauses.append("empresa = ?")
        params.append(empresa)
    if vacante_id is not None:
        clauses.append("vacante_id = ?")
        params.append(vacante_id)
    elif sin_vacante:
        clauses.append("vacante_id IS NULL")
    if q:
        clauses.append("(nombre_completo LIKE ? OR telefono LIKE ? OR email LIKE ? OR puesto_solicitado LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT estado, COUNT(*) AS n FROM candidatos {where} GROUP BY estado", params).fetchall()
    conn.close()
    conteo = {e: 0 for e in ESTADOS}
    for r in rows:
        conteo[r["estado"]] = r["n"]
    return conteo


def compartir_candidatos_directo(candidato_ids: list[int], usuario_id: int, compartido_por: str):
    """Comparte cada candidato con `usuario_id` -- compartir es EXCLUSIVO: si
    el candidato ya estaba compartido con otra persona (por cualquiera de
    los dos caminos, directo aquí o vía Informes), se le quita el acceso a
    esa persona antes de dárselo al nuevo destinatario. Así un candidato
    tiene como mucho un responsable de Reclutamiento a la vez, en vez de
    acumular gente cada vez que se re-comparte a alguien distinto (ver
    confirmarCompartirCandidatos en el frontend, que avisa de este cambio
    antes de hacerlo)."""
    conn = get_connection()
    for candidato_id in candidato_ids:
        conn.execute(
            "DELETE FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id != ?",
            (candidato_id, usuario_id),
        )
        conn.execute(
            "DELETE FROM informe_compartidos WHERE candidato_id = ? AND usuario_id != ?",
            (candidato_id, usuario_id),
        )
        conn.execute(
            """
            INSERT INTO candidato_compartidos (candidato_id, usuario_id, compartido_por)
            VALUES (?, ?, ?)
            ON CONFLICT(candidato_id, usuario_id)
            DO UPDATE SET compartido_por = excluded.compartido_por, compartido_en = datetime('now')
            """,
            (candidato_id, usuario_id, compartido_por),
        )
    conn.commit()
    conn.close()


def dejar_de_compartir_candidato(candidato_id: int, usuario_id: int):
    conn = get_connection()
    conn.execute(
        "DELETE FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id = ?", (candidato_id, usuario_id)
    )
    conn.commit()
    conn.close()


def cambiar_destinatario_directo(pares, nuevo_usuario_id, compartido_en):
    """pares = [(candidato_id, usuario_id_actual), ...]. Mueve cada share
    directo a `nuevo_usuario_id`, re-estampando `compartido_en` con la
    MISMA fecha para todos -- así, aunque vinieran de tandas o
    destinatarios distintos, quedan agrupados en una sola tanda nueva tras
    el cambio (ver informes.cambiar_destinatario_compartidos, que orquesta
    esto junto con el lado de informe_compartidos bajo el mismo timestamp).
    Si el candidato YA estaba también compartido con el destinatario nuevo,
    se descarta el share viejo en vez de chocar con
    UNIQUE(candidato_id, usuario_id)."""
    conn = get_connection()
    for candidato_id, usuario_id_actual in pares:
        if usuario_id_actual == nuevo_usuario_id:
            conn.execute(
                "UPDATE candidato_compartidos SET compartido_en = ? WHERE candidato_id = ? AND usuario_id = ?",
                (compartido_en, candidato_id, nuevo_usuario_id),
            )
            continue
        ya_existe = conn.execute(
            "SELECT 1 FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id = ?",
            (candidato_id, nuevo_usuario_id),
        ).fetchone()
        if ya_existe:
            conn.execute(
                "DELETE FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id = ?",
                (candidato_id, usuario_id_actual),
            )
            conn.execute(
                "UPDATE candidato_compartidos SET compartido_en = ? WHERE candidato_id = ? AND usuario_id = ?",
                (compartido_en, candidato_id, nuevo_usuario_id),
            )
        else:
            conn.execute(
                "UPDATE candidato_compartidos SET usuario_id = ?, compartido_en = ? "
                "WHERE candidato_id = ? AND usuario_id = ?",
                (nuevo_usuario_id, compartido_en, candidato_id, usuario_id_actual),
            )
    conn.commit()
    conn.close()


def get_candidatos_compartidos_directo_con(usuario_id, empresa=None):
    conn = get_connection()
    clauses = ["cc.usuario_id = ?"]
    params = [usuario_id]
    if empresa:
        clauses.append("c.empresa = ?")
        params.append(empresa)
    rows = conn.execute(f"""
        SELECT cc.id AS compartido_id, cc.compartido_en, cc.compartido_por, c.*,
               json_extract(r.datos_json, '$.RESULTADO') AS test_resultado
        FROM candidato_compartidos cc
        JOIN candidatos c ON c.id = cc.candidato_id
        LEFT JOIN informe_respuestas r ON r.id = c.respuesta_id
        WHERE {' AND '.join(clauses)}
        ORDER BY cc.compartido_en DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_candidatos_compartidos_directo_por(username, empresa=None):
    conn = get_connection()
    clauses = ["cc.compartido_por = ?"]
    params = [username]
    if empresa:
        clauses.append("c.empresa = ?")
        params.append(empresa)
    rows = conn.execute(f"""
        SELECT cc.id AS compartido_id, cc.compartido_en, cc.compartido_por,
               cc.usuario_id AS destinatario_id,
               u.nombre AS destinatario_nombre, u.username AS destinatario_username, c.*,
               json_extract(r.datos_json, '$.RESULTADO') AS test_resultado
        FROM candidato_compartidos cc
        JOIN candidatos c ON c.id = cc.candidato_id
        JOIN usuarios u ON u.id = cc.usuario_id
        LEFT JOIN informe_respuestas r ON r.id = c.respuesta_id
        WHERE {' AND '.join(clauses)}
        ORDER BY cc.compartido_en DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def usuario_tiene_acceso_candidato(usuario_id, candidato_id):
    """Puerta para quien NO tiene el módulo Informes/Reclutamiento completo
    (gerentes, area managers) pero sí tiene acceso a este candidato en
    concreto -- por "compartir directo" (candidato_compartidos), por el
    camino de siempre desde Informes (informe_compartidos, que también
    guarda candidato_id desde que existe el enlace automático con el test),
    o porque es responsable de la VACANTE a la que pertenece este candidato
    (vacante_compartidos) -- este último da acceso a toda la solicitud de
    una vez, no solo a los candidatos compartidos uno a uno."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id = ?", (candidato_id, usuario_id)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT 1 FROM informe_compartidos WHERE candidato_id = ? AND usuario_id = ?", (candidato_id, usuario_id)
        ).fetchone()
    if row is None:
        row = conn.execute("""
            SELECT 1 FROM candidatos c
            JOIN vacante_compartidos vc ON vc.vacante_id = c.vacante_id
            WHERE c.id = ? AND vc.usuario_id = ?
        """, (candidato_id, usuario_id)).fetchone()
    conn.close()
    return row is not None


def candidatos_descartados_antiguos(meses: int):
    """Candidatos en estado 'descartado' que llevan más de `meses` sin
    actividad (actualizado_en) — la lista de lo que se borraría, para poder
    revisarla antes de purgar de verdad. No incluye estados activos
    (pendiente/entrevistado/contratado) a propósito: la retención solo tiene
    sentido para candidaturas ya cerradas y descartadas."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, nombre_completo, telefono, email, actualizado_en
        FROM candidatos
        WHERE estado = 'descartado' AND actualizado_en < datetime('now', ?)
        ORDER BY actualizado_en
    """, (f"-{meses} months",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purgar_descartados(meses: int) -> int:
    """Borra de verdad (ficha + archivos) los candidatos devueltos por
    candidatos_descartados_antiguos — se llama a mano desde Ajustes tras
    revisar la lista, nunca sola en el arranque."""
    candidatos = candidatos_descartados_antiguos(meses)
    for c in candidatos:
        eliminar_candidato(c["id"])
    return len(candidatos)


def eliminar_candidato(candidato_id):
    candidato = get_candidato(candidato_id)
    if candidato is None:
        return
    for archivo in candidato["archivos"]:
        _borrar_archivo_disco(archivo["id"])
    conn = get_connection()
    conn.execute("DELETE FROM candidato_archivos WHERE candidato_id = ?", (candidato_id,))
    conn.execute("DELETE FROM candidatos WHERE id = ?", (candidato_id,))
    conn.commit()
    conn.close()


def _borrar_archivo_disco(archivo_id):
    conn = get_connection()
    row = conn.execute("SELECT ruta FROM candidato_archivos WHERE id = ?", (archivo_id,)).fetchone()
    conn.close()
    if row and row["ruta"] and os.path.exists(row["ruta"]):
        os.remove(row["ruta"])


def agregar_archivo(candidato_id, nombre_original, contenido):
    carpeta = os.path.join(UPLOADS_DIR, str(candidato_id))
    os.makedirs(carpeta, exist_ok=True)
    ext = os.path.splitext(nombre_original)[1]
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM candidato_archivos WHERE candidato_id = ?", (candidato_id,)).fetchone()[0]
    ruta = os.path.join(carpeta, f"{n + 1}{ext}")
    with open(ruta, "wb") as f:
        f.write(contenido)
    cur = conn.execute(
        "INSERT INTO candidato_archivos (candidato_id, nombre_original, ruta) VALUES (?, ?, ?)",
        (candidato_id, nombre_original, ruta),
    )
    archivo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return archivo_id


def get_foto_ruta(candidato_id):
    conn = get_connection()
    row = conn.execute("SELECT foto_ruta FROM candidatos WHERE id = ?", (candidato_id,)).fetchone()
    conn.close()
    return row["foto_ruta"] if row and row["foto_ruta"] else None


def guardar_foto(candidato_id, contenido: bytes, ext: str):
    ruta_anterior = get_foto_ruta(candidato_id)
    carpeta = os.path.join(UPLOADS_DIR, str(candidato_id))
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, f"foto{ext}")
    with open(ruta, "wb") as f:
        f.write(contenido)
    conn = get_connection()
    conn.execute("UPDATE candidatos SET foto_ruta = ? WHERE id = ?", (ruta, candidato_id))
    conn.commit()
    conn.close()
    # Si la extensión cambió respecto a la foto anterior (p.ej. era .png y
    # ahora es .jpg), el archivo viejo se queda huérfano en disco -- se
    # limpia para no acumular basura.
    if ruta_anterior and ruta_anterior != ruta and os.path.exists(ruta_anterior):
        os.remove(ruta_anterior)


def quitar_foto(candidato_id):
    ruta = get_foto_ruta(candidato_id)
    if ruta and os.path.exists(ruta):
        os.remove(ruta)
    conn = get_connection()
    conn.execute("UPDATE candidatos SET foto_ruta = NULL WHERE id = ?", (candidato_id,))
    conn.commit()
    conn.close()


def info_fotos_perfil() -> dict:
    """Diagnóstico de solo lectura: cuántas fotos de perfil hay y cuánto
    pesan en total -- para confirmar que son de verdad las que están
    llenando el volumen antes de borrarlas."""
    conn = get_connection()
    filas = conn.execute("SELECT foto_ruta FROM candidatos WHERE foto_ruta IS NOT NULL").fetchall()
    conn.close()
    total_bytes = 0
    n = 0
    for fila in filas:
        ruta = fila["foto_ruta"]
        if ruta and os.path.isfile(ruta):
            total_bytes += os.path.getsize(ruta)
            n += 1
    return {"fotos": n, "bytes": total_bytes, "mb": round(total_bytes / 1024 / 1024, 1)}


def quitar_todas_las_fotos() -> dict:
    """Borra el ARCHIVO de foto de perfil de todos los candidatos y limpia
    foto_ruta -- no toca CVs, notas, ni ningún otro dato de la ficha (mismo
    criterio que quitar_foto() para un candidato, aplicado a todos)."""
    conn = get_connection()
    ids = [row["id"] for row in conn.execute("SELECT id FROM candidatos WHERE foto_ruta IS NOT NULL")]
    conn.close()
    borrados = 0
    bytes_liberados = 0
    for candidato_id in ids:
        ruta = get_foto_ruta(candidato_id)
        if ruta and os.path.isfile(ruta):
            try:
                bytes_liberados += os.path.getsize(ruta)
                os.remove(ruta)
                borrados += 1
            except OSError:
                pass
        conn = get_connection()
        conn.execute("UPDATE candidatos SET foto_ruta = NULL WHERE id = ?", (candidato_id,))
        conn.commit()
        conn.close()
    return {"borrados": borrados, "bytes_liberados": bytes_liberados}


def info_archivos_duplicados() -> dict:
    """Diagnóstico de solo lectura: candidato_archivos cuyo contenido (hash)
    coincide con el de otro archivo distinto -- p.ej. un PDF con varias
    fichas juntas adjuntado a cada candidato como "copia propia" (ver
    'Adjuntar PDF a fichas existentes'), que guarda una copia física
    completa por cada ficha en vez de compartir el mismo archivo. No borra
    nada, solo mide cuánto se podría ahorrar deduplicando."""
    import hashlib

    conn = get_connection()
    filas = conn.execute("SELECT id, candidato_id, nombre_original, ruta FROM candidato_archivos").fetchall()
    conn.close()

    por_hash = {}
    for fila in filas:
        ruta = fila["ruta"]
        if not ruta or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            continue
        tamano = os.path.getsize(ruta)
        por_hash.setdefault(h, []).append({
            "archivo_id": fila["id"], "candidato_id": fila["candidato_id"],
            "nombre_original": fila["nombre_original"], "ruta": ruta, "bytes": tamano,
        })

    grupos_duplicados = [copias for copias in por_hash.values() if len(copias) > 1]
    bytes_recuperables = sum(copias[0]["bytes"] * (len(copias) - 1) for copias in grupos_duplicados)
    return {
        "grupos_duplicados": len(grupos_duplicados),
        "copias_de_mas": sum(len(c) - 1 for c in grupos_duplicados),
        "bytes_recuperables": bytes_recuperables,
        "mb_recuperables": round(bytes_recuperables / 1024 / 1024, 1),
        "detalle": grupos_duplicados[:20],
    }


def deduplicar_archivos() -> dict:
    """Aplica lo que mide info_archivos_duplicados(): por cada grupo de
    archivos con el mismo contenido, deja UNA sola copia física en disco y
    actualiza el resto de filas de candidato_archivos para que apunten a
    esa misma ruta -- cada candidato SIGUE teniendo su adjunto exactamente
    igual (mismo nombre_original, mismo contenido al verlo/descargarlo),
    solo deja de haber 49 copias idénticas de los mismos bytes en disco."""
    info = info_archivos_duplicados()
    conn = get_connection()
    borrados = 0
    bytes_liberados = 0
    for grupo in info["detalle"]:
        canonica = grupo[0]["ruta"]
        for copia in grupo[1:]:
            if copia["ruta"] == canonica:
                continue
            conn.execute(
                "UPDATE candidato_archivos SET ruta = ? WHERE id = ?",
                (canonica, copia["archivo_id"]),
            )
            try:
                if os.path.isfile(copia["ruta"]):
                    bytes_liberados += os.path.getsize(copia["ruta"])
                    os.remove(copia["ruta"])
                    borrados += 1
            except OSError:
                pass
    conn.commit()
    conn.close()
    return {"archivos_deduplicados": borrados, "bytes_liberados": bytes_liberados}


def registrar_archivo_existente(candidato_id, nombre_original, ruta):
    """Como agregar_archivo, pero para un fichero que YA está guardado en
    disco (el CV que Informes guarda en su propia carpeta al compartir una
    respuesta) — no copia bytes, solo lo enlaza a la ficha del candidato."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO candidato_archivos (candidato_id, nombre_original, ruta) VALUES (?, ?, ?)",
        (candidato_id, nombre_original, ruta),
    )
    archivo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return archivo_id


def get_archivo(archivo_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM candidato_archivos WHERE id = ?", (archivo_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _carpetas_huerfanas():
    """Carpetas de UPLOADS_DIR/{candidato_id}/ cuyo candidato_id ya no existe
    en la tabla `candidatos` -- eliminar_candidato() sí borra los archivos de
    cada candidato al eliminarlo, pero solo por lo que hay en
    candidato_archivos en ese momento; si algo se coló por otra vía (borrado
    directo en DB, migración, bug ya corregido...) la carpeta entera se queda
    huérfana en disco para siempre. Solo lectura -- no borra nada."""
    if not os.path.isdir(UPLOADS_DIR):
        return []
    conn = get_connection()
    ids_vivos = {row["id"] for row in conn.execute("SELECT id FROM candidatos")}
    conn.close()

    huerfanas = []
    for nombre_carpeta in os.listdir(UPLOADS_DIR):
        ruta_carpeta = os.path.join(UPLOADS_DIR, nombre_carpeta)
        if not os.path.isdir(ruta_carpeta):
            continue
        try:
            candidato_id = int(nombre_carpeta)
        except ValueError:
            continue
        if candidato_id in ids_vivos:
            continue
        huerfanas.append(ruta_carpeta)
    return huerfanas


def info_archivos_huerfanos() -> dict:
    """Diagnóstico de solo lectura: tamaño total de las carpetas huérfanas
    (ver _carpetas_huerfanas) sin borrar nada, para decidir con datos reales."""
    detalle = []
    total_bytes = 0
    for ruta_carpeta in _carpetas_huerfanas():
        tamano_carpeta = 0
        n_archivos = 0
        for raiz, _, nombres in os.walk(ruta_carpeta):
            for nombre in nombres:
                try:
                    tamano_carpeta += os.path.getsize(os.path.join(raiz, nombre))
                    n_archivos += 1
                except OSError:
                    pass
        detalle.append({"carpeta": ruta_carpeta, "archivos": n_archivos, "bytes": tamano_carpeta})
        total_bytes += tamano_carpeta
    return {"carpetas_huerfanas": len(detalle), "bytes": total_bytes, "mb": round(total_bytes / 1024 / 1024, 1), "detalle": detalle}


def borrar_archivos_huerfanos() -> dict:
    """Borra las carpetas huérfanas (ver _carpetas_huerfanas) -- re-consulta
    la lista de ids vivos en el momento de borrar, no reusa un resultado
    anterior, para no borrar por error una carpeta de un candidato creado
    justo entre el diagnóstico y el borrado."""
    import shutil

    borrados = 0
    bytes_liberados = 0
    for ruta_carpeta in _carpetas_huerfanas():
        for raiz, _, nombres in os.walk(ruta_carpeta):
            for nombre in nombres:
                ruta = os.path.join(raiz, nombre)
                try:
                    bytes_liberados += os.path.getsize(ruta)
                    borrados += 1
                except OSError:
                    pass
        try:
            shutil.rmtree(ruta_carpeta)
        except OSError:
            pass
    return {"borrados": borrados, "bytes_liberados": bytes_liberados}


ensure_reclutamiento_tables()
