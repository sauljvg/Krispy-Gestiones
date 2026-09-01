import datetime
import hashlib
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

# Columnas que se pueden pedir en el Excel de "Base de candidatos" (ver
# exportar_candidatos) -- clave interna -> cabecera legible. "vacante" y
# "test_resultado" no son columnas propias de la tabla, se resuelven aparte
# (join con vacantes/informe_respuestas).
CAMPOS_EXPORTABLES = {
    "nombre_completo": "Nombre completo",
    "telefono": "Teléfono",
    "email": "Email",
    "vacante": "Vacante",
    "test_resultado": "Resultado del test",
    "estado": "Estado",
    "puesto_solicitado": "Puesto solicitado",
    # direccion/fecha_nacimiento/dni/disponibilidad se quitaron de aquí a
    # petición expresa: son datos que no se recogen (el campo existe en la
    # ficha por si algún día hiciera falta, pero siempre sale vacío), así
    # que ofrecerlos como columna de exportación solo era ruido.
    "fecha_solicitud": "Fecha de solicitud",
    "contacto_estado": "Estado de contacto",
    "notas": "Notas",
}

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
    cols_vacantes = {row[1] for row in conn.execute("PRAGMA table_info(vacantes)")}
    if "archivada" not in cols_vacantes:
        # Independiente de estado (abierta/cubierta/cancelada) a propósito --
        # se puede archivar una vacante cubierta o cancelada para que deje de
        # verse por defecto sin perder qué pasó con ella, y reabrirla no la
        # desarchiva sola.
        conn.execute("ALTER TABLE vacantes ADD COLUMN archivada INTEGER NOT NULL DEFAULT 0")
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
    # ia_extraida_en: marca explícita de "a este candidato ya lo procesó
    # Gemini", independiente de si formacion_json/experiencia_json quedaron
    # con algo -- antes se usaba solo "¿tiene formacion_json/experiencia_json
    # no vacíos?" como señal (ver candidatos_ya_enriquecidos), pero un CV real
    # puede no tener ninguna entrada de formación o de experiencia que
    # extraer (candidato sin estudios reglados, p.ej.) y Gemini SÍ lo procesó
    # bien -- con la señal vieja, "Descargar CV en PDF" seguía sirviendo el
    # PDF original de InfoJobs en vez del nuestro aunque el candidato ya
    # estuviera correctamente enriquecido.
    if "ia_extraida_en" not in cols_candidatos:
        conn.execute("ALTER TABLE candidatos ADD COLUMN ia_extraida_en TEXT")
        # Backfill: quien ya tenía formacion_json/experiencia_json con datos
        # es, con certeza, alguien que SÍ pasó por Gemini (ver
        # candidatos_ya_enriquecidos) -- para esos se marca ya mismo, así no
        # se pierde la detección de quien se enriqueció antes de este cambio.
        conn.execute("""
            UPDATE candidatos SET ia_extraida_en = datetime('now')
            WHERE ia_extraida_en IS NULL
              AND ((formacion_json IS NOT NULL AND formacion_json NOT IN ('[]', 'null'))
                OR (experiencia_json IS NOT NULL AND experiencia_json NOT IN ('[]', 'null')))
        """)
    # Backfill de fecha_solicitud vacía con la fecha en la que se dio de alta
    # la ficha -- es una aproximación razonable (normalmente se sube el mismo
    # día que se recibe la solicitud) y evita dejar el campo en blanco en
    # fichas ya existentes. Idempotente, se puede ejecutar en cada arranque.
    conn.execute("""
        UPDATE candidatos SET fecha_solicitud = substr(creado_en, 1, 10)
        WHERE fecha_solicitud IS NULL OR fecha_solicitud = ''
    """)
    # El texto libre antiguo de formación/experiencia se dejaba como aviso de
    # "dato antiguo" mientras no hubiera historial estructurado -- pero en
    # cuanto SÍ hay formacion_json/experiencia_json, ese texto es ruido puro
    # (la información correcta ya está en el campo estructurado), así que se
    # vacía. Idempotente, se puede ejecutar en cada arranque.
    conn.execute("""
        UPDATE candidatos SET formacion = NULL
        WHERE formacion IS NOT NULL AND formacion_json IS NOT NULL AND formacion_json != '[]'
    """)
    conn.execute("""
        UPDATE candidatos SET experiencia = NULL
        WHERE experiencia IS NOT NULL AND experiencia_json IS NOT NULL AND experiencia_json != '[]'
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
    cols_archivos = {row[1] for row in conn.execute("PRAGMA table_info(candidato_archivos)")}
    if "contenido_hash" not in cols_archivos:
        # Para poder detectar cuando se adjunta el MISMO archivo otra vez
        # (p.ej. reintentar subir el mismo PDF de lote varias veces) y no
        # crear una copia nueva cada vez -- ver agregar_archivo.
        conn.execute("ALTER TABLE candidato_archivos ADD COLUMN contenido_hash TEXT")
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
    # Cola durable del relleno con IA en segundo plano (ver
    # _rellenar_huecos_en_segundo_plano en reclutamiento_routes.py). El
    # progreso en sí sigue viviendo en memoria (_progreso_lotes, solo para
    # pintar el indicador), pero SIN esto un redeploy o reinicio de Railway a
    # media tanda mataba el trabajo de verdad sin dejar ningún rastro -- el
    # usuario volvía a entrar, veía "0/32" y tenía que rehacer todo el lote a
    # mano. Con esto, al arrancar el proceso se retoma solo desde donde se
    # quedó (ver reanudar_lotes_ia_pendientes / _reanudar_lotes_al_arrancar).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lotes_ia (
            lote_id TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            total INTEGER NOT NULL,
            intentar_gemini INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cols_lotes_ia = {row[1] for row in conn.execute("PRAGMA table_info(lotes_ia)")}
    if "intentar_gemini" not in cols_lotes_ia:
        conn.execute("ALTER TABLE lotes_ia ADD COLUMN intentar_gemini INTEGER NOT NULL DEFAULT 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lotes_ia_pendientes (
            lote_id TEXT NOT NULL REFERENCES lotes_ia(lote_id) ON DELETE CASCADE,
            candidato_id INTEGER NOT NULL,
            archivo_id INTEGER NOT NULL,
            PRIMARY KEY (lote_id, candidato_id)
        )
    """)
    conn.commit()
    conn.close()
    _limpiar_archivos_duplicados()


def _hash_archivo(ruta):
    try:
        with open(ruta, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _limpiar_archivos_duplicados():
    """Colapsa archivos duplicados que hayan quedado de subir el mismo PDF
    de lote varias veces (reintentos) -- por candidato, agrupa por (nombre
    original, contenido real) y se queda solo con la copia más reciente,
    borrando el resto (fila + archivo en disco). Se ejecuta en cada
    arranque; si no hay duplicados no hace nada, así que es barato dejarla
    puesta de forma permanente en vez de un script suelto de un solo uso."""
    conn = get_connection()
    filas = conn.execute(
        "SELECT id, candidato_id, nombre_original, ruta, subido_en, contenido_hash "
        "FROM candidato_archivos ORDER BY subido_en ASC"
    ).fetchall()
    grupos = {}
    for f in filas:
        h = f["contenido_hash"] or _hash_archivo(f["ruta"])
        if h is None:
            continue
        if not f["contenido_hash"]:
            conn.execute("UPDATE candidato_archivos SET contenido_hash = ? WHERE id = ?", (h, f["id"]))
        grupos.setdefault((f["candidato_id"], f["nombre_original"], h), []).append(f)
    borrados = 0
    for filas_grupo in grupos.values():
        if len(filas_grupo) <= 1:
            continue
        # Ya vienen ordenadas por subido_en ASC -- se conserva la última.
        for f in filas_grupo[:-1]:
            try:
                if f["ruta"] and os.path.exists(f["ruta"]):
                    os.remove(f["ruta"])
            except OSError:
                pass
            conn.execute("DELETE FROM candidato_archivos WHERE id = ?", (f["id"],))
            borrados += 1
    conn.commit()
    conn.close()
    if borrados:
        print(f"[reclutamiento] Limpieza de archivos duplicados: {borrados} copia(s) eliminada(s).")


def list_vacantes(empresa=None, estado=None, archivadas=False):
    conn = get_connection()
    clauses = ["v.archivada = ?"]
    params = [1 if archivadas else 0]
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


def get_empresa_vacante(vacante_id):
    """Solo la empresa de una vacante, sin cargar el resto -- para
    comprobar permisos por marca (KK/Saona) antes de tocar el recurso."""
    conn = get_connection()
    row = conn.execute("SELECT empresa FROM vacantes WHERE id = ?", (vacante_id,)).fetchone()
    conn.close()
    return row["empresa"] if row else None


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
    if "archivada" in campos:
        sets.append("archivada = ?")
        params.append(1 if campos["archivada"] else 0)
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
    los dos caminos de compartir INDIVIDUAL (candidato_compartidos, directo
    desde Reclutamiento, e informe_compartidos, que también guarda
    candidato_id desde que existe el enlace automático con el test) para
    poder avisar "ya compartido con X" sin importar por cuál de los dos
    caminos se hizo. No incluye vacante_compartidos a propósito -- ese es un
    acceso a nivel de SOLICITUD entera (ver "Responsables" en el editor de
    vacante), no una fila individual que se pueda "dejar de compartir" ni
    "cambiar de destinatario" uno a uno como estas dos.
    `directo`/`respuesta_id` van en cada entrada para que dejar_de_compartir
    y cambiar_destinatario sepan a qué tabla apuntar sin otra consulta."""
    if not candidato_ids:
        return {}
    placeholders = ",".join("?" * len(candidato_ids))
    rows = conn.execute(f"""
        SELECT cc.candidato_id AS candidato_id, cc.usuario_id AS usuario_id, u.nombre AS usuario_nombre,
               1 AS directo, NULL AS respuesta_id
        FROM candidato_compartidos cc JOIN usuarios u ON u.id = cc.usuario_id
        WHERE cc.candidato_id IN ({placeholders})
        UNION ALL
        SELECT ic.candidato_id AS candidato_id, ic.usuario_id AS usuario_id, u.nombre AS usuario_nombre,
               0 AS directo, ic.respuesta_id AS respuesta_id
        FROM informe_compartidos ic JOIN usuarios u ON u.id = ic.usuario_id
        WHERE ic.candidato_id IN ({placeholders})
    """, candidato_ids + candidato_ids).fetchall()
    mapa = {}
    vistos = set()
    for r in rows:
        # Si por lo que sea el mismo candidato-destinatario está compartido
        # por los dos caminos a la vez, no se muestra duplicado.
        clave = (r["candidato_id"], r["usuario_id"])
        if clave in vistos:
            continue
        vistos.add(clave)
        mapa.setdefault(r["candidato_id"], []).append({
            "usuario_id": r["usuario_id"],
            "nombre": r["usuario_nombre"],
            "directo": bool(r["directo"]),
            "respuesta_id": r["respuesta_id"],
        })
    return mapa


def get_empresa_candidato(candidato_id):
    """Solo la empresa de un candidato, sin cargar el resto -- para
    comprobar permisos por marca (KK/Saona) antes de tocar el recurso."""
    conn = get_connection()
    row = conn.execute("SELECT empresa FROM candidatos WHERE id = ?", (candidato_id,)).fetchone()
    conn.close()
    return row["empresa"] if row else None


def get_empresas_candidatos(candidato_ids: list[int]) -> dict[int, str]:
    """Igual que get_empresa_candidato pero para una lista de ids de golpe
    (acciones en lote: exportar, descargar PDFs...)."""
    if not candidato_ids:
        return {}
    conn = get_connection()
    placeholders = ",".join("?" for _ in candidato_ids)
    rows = conn.execute(
        f"SELECT id, empresa FROM candidatos WHERE id IN ({placeholders})", candidato_ids
    ).fetchall()
    conn.close()
    return {r["id"]: r["empresa"] for r in rows}


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


def exportar_candidatos(candidato_ids: list[int], columnas: list[str]) -> list[dict]:
    """Filas para el Excel de "Base de candidatos" (ver rows_to_xlsx en
    utils.py) -- solo las columnas pedidas (CAMPOS_EXPORTABLES), en el mismo
    orden en que se pidieron y con la cabecera legible como clave del dict.
    "vacante" y "test_resultado" no son columnas propias de candidatos, se
    resuelven aparte con un join."""
    columnas = [c for c in columnas if c in CAMPOS_EXPORTABLES] or ["nombre_completo"]
    if not candidato_ids:
        return []
    conn = get_connection()
    placeholders = ",".join("?" * len(candidato_ids))
    rows = conn.execute(f"""
        SELECT c.*, json_extract(r.datos_json, '$.RESULTADO') AS test_resultado,
               v.puesto AS vacante_puesto, v.centro AS vacante_centro
        FROM candidatos c
        LEFT JOIN informe_respuestas r ON r.id = c.respuesta_id
        LEFT JOIN vacantes v ON v.id = c.vacante_id
        WHERE c.id IN ({placeholders})
    """, candidato_ids).fetchall()
    conn.close()
    por_id = {r["id"]: r for r in rows}
    salida = []
    for cid in candidato_ids:
        r = por_id.get(cid)
        if r is None:
            continue
        fila = {}
        for col in columnas:
            etiqueta = CAMPOS_EXPORTABLES[col]
            if col == "vacante":
                fila[etiqueta] = (
                    r["vacante_puesto"] + (f" · {r['vacante_centro']}" if r["vacante_centro"] else "")
                    if r["vacante_puesto"] else "Sin vacante asignada"
                )
            elif col == "test_resultado":
                fila[etiqueta] = r["test_resultado"] or "Sin responder test"
            elif col in ("estado", "contacto_estado"):
                fila[etiqueta] = (r[col] or "").replace("_", " ").capitalize()
            else:
                fila[etiqueta] = r[col] or ""
        salida.append(fila)
    return salida


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


def candidatos_ya_enriquecidos(candidato_ids: list[int]) -> set[int]:
    """De esos ids, a cuáles YA procesó la extracción de CV (ver
    ia_extraida_en) -- se usa en la vista previa de "Adjuntar PDF a fichas
    existentes" para no hacer repasar a quien ya quedó bien si un lote se
    cortó a medias, y en "Descargar CV en PDF" para decidir si ya toca
    servir nuestro diseño en vez del PDF original. Antes se inferís de si
    formacion_json/experiencia_json tenían algo, pero un candidato sin
    estudios ni experiencia que extraer (CV real) se quedaba con esos dos
    campos vacíos igualmente -- se veía como "no procesado" aunque sí lo
    estuviera."""
    if not candidato_ids:
        return set()
    conn = get_connection()
    placeholders = ",".join("?" * len(candidato_ids))
    rows = conn.execute(f"""
        SELECT id FROM candidatos WHERE id IN ({placeholders}) AND ia_extraida_en IS NOT NULL
    """, candidato_ids).fetchall()
    conn.close()
    return {row["id"] for row in rows}


def marcar_ia_extraida(candidato_id: int):
    """Se llama cada vez que se extrae (con éxito) el CV de este candidato,
    encuentre o no encuentre formación/experiencia que rellenar -- ver
    candidatos_ya_enriquecidos."""
    conn = get_connection()
    conn.execute("UPDATE candidatos SET ia_extraida_en = datetime('now') WHERE id = ?", (candidato_id,))
    conn.commit()
    conn.close()


def candidatos_con_pdf(empresa=None, candidato_ids: list[int] | None = None) -> list[tuple[int, int]]:
    """[(candidato_id, archivo_id), ...] con el PDF más reciente de cada
    candidato que tenga al menos uno adjunto -- para re-extraer varios de
    golpe (ver /candidatos/reextraer-todos) sin que el reclutador tenga que
    volver a subir nada ni entrar ficha a ficha: el PDF ya está guardado en
    disco desde que se creó o se le adjuntó por lote. `candidato_ids`
    limita a esa lista concreta (el filtro que tenga puesto la pantalla en
    ese momento) -- con miles de candidatos, re-extraer TODOS de golpe cada
    vez que se pulsa el botón sería carísimo cuando en realidad solo hacen
    falta los que se acaban de añadir o los que el filtro tiene delante."""
    conn = get_connection()
    clausulas = []
    params = []
    if empresa:
        clausulas.append("c.empresa = ?")
        params.append(empresa)
    if candidato_ids is not None:
        if not candidato_ids:
            conn.close()
            return []
        marcadores = ",".join("?" * len(candidato_ids))
        clausulas.append(f"ca.candidato_id IN ({marcadores})")
        params.extend(candidato_ids)
    clausula_where = ("AND " + " AND ".join(clausulas)) if clausulas else ""
    rows = conn.execute(f"""
        SELECT ca.candidato_id, ca.id AS archivo_id
        FROM candidato_archivos ca
        JOIN candidatos c ON c.id = ca.candidato_id
        WHERE ca.nombre_original LIKE '%.pdf'
        {clausula_where}
        AND ca.id = (
            SELECT ca2.id FROM candidato_archivos ca2
            WHERE ca2.candidato_id = ca.candidato_id AND ca2.nombre_original LIKE '%.pdf'
            ORDER BY ca2.subido_en DESC LIMIT 1
        )
    """, params).fetchall()
    conn.close()
    return [(row["candidato_id"], row["archivo_id"]) for row in rows]


def candidatos_con_pdf_y_foto(empresa=None) -> list[tuple[int, int]]:
    """Igual que candidatos_con_pdf, pero solo de candidatos que YA tienen
    una foto de perfil guardada -- para poder revisar (ver
    limpiar_fotos_de_lote_compartido en reclutamiento_routes.py) si esa foto
    de verdad les pertenece, sin perder tiempo con quien no tiene ninguna."""
    conn = get_connection()
    clausula_empresa = "AND c.empresa = ?" if empresa else ""
    params = (empresa,) if empresa else ()
    rows = conn.execute(f"""
        SELECT ca.candidato_id, ca.id AS archivo_id
        FROM candidato_archivos ca
        JOIN candidatos c ON c.id = ca.candidato_id
        WHERE ca.nombre_original LIKE '%.pdf' AND c.foto_ruta IS NOT NULL
        {clausula_empresa}
        AND ca.id = (
            SELECT ca2.id FROM candidato_archivos ca2
            WHERE ca2.candidato_id = ca.candidato_id AND ca2.nombre_original LIKE '%.pdf'
            ORDER BY ca2.subido_en DESC LIMIT 1
        )
    """, params).fetchall()
    conn.close()
    return [(row["candidato_id"], row["archivo_id"]) for row in rows]


def candidatos_con_foto(empresa=None) -> list[dict]:
    """[{id, nombre_completo, foto_ruta}, ...] de todos los candidatos con
    foto de perfil -- para poder comparar el CONTENIDO real del archivo
    entre candidatos (ver detectar_fotos_duplicadas_route) y encontrar así
    cualquier caso de foto ajena que la limpieza por PDF no haya cogido
    (p.ej. si el PDF más reciente de la ficha ya cambió desde que se le puso
    la foto mala, o si el re-análisis del PDF ya no coincide con el de
    cuando se generó el problema)."""
    conn = get_connection()
    clausula_empresa = "WHERE empresa = ? AND foto_ruta IS NOT NULL" if empresa else "WHERE foto_ruta IS NOT NULL"
    params = (empresa,) if empresa else ()
    rows = conn.execute(
        f"SELECT id, nombre_completo, foto_ruta FROM candidatos {clausula_empresa}", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_lote_ia_pendiente(lote_id: str, usuario_id: int, titulo: str, candidatos_archivos: list[tuple[int, int]]):
    """candidatos_archivos: [(candidato_id, archivo_id), ...] -- registra en
    disco qué le falta por rellenar a este lote, para poder retomarlo solo
    si el proceso se reinicia a media tanda (ver lotes_ia_incompletos /
    _reanudar_lotes_al_arrancar en reclutamiento_routes.py). El archivo_id
    ya apunta a un PDF que agregar_archivo dejó guardado en disco ANTES de
    programar el relleno en segundo plano, así que no hace falta guardar
    los bytes aquí también."""
    if not candidatos_archivos:
        return
    conn = get_connection()
    conn.execute(
        "INSERT INTO lotes_ia (lote_id, usuario_id, titulo, total) VALUES (?, ?, ?, ?)",
        (lote_id, usuario_id, titulo, len(candidatos_archivos)),
    )
    conn.executemany(
        "INSERT INTO lotes_ia_pendientes (lote_id, candidato_id, archivo_id) VALUES (?, ?, ?)",
        [(lote_id, cid, aid) for cid, aid in candidatos_archivos],
    )
    conn.commit()
    conn.close()


def marcar_candidato_lote_terminado(lote_id: str, candidato_id: int):
    """Quita a este candidato de la cola pendiente del lote -- si no queda
    ninguno más, el lote ya está completo del todo y se borra también su
    fila de metadatos."""
    conn = get_connection()
    conn.execute("DELETE FROM lotes_ia_pendientes WHERE lote_id = ? AND candidato_id = ?", (lote_id, candidato_id))
    restantes = conn.execute("SELECT COUNT(*) FROM lotes_ia_pendientes WHERE lote_id = ?", (lote_id,)).fetchone()[0]
    if restantes == 0:
        conn.execute("DELETE FROM lotes_ia WHERE lote_id = ?", (lote_id,))
    conn.commit()
    conn.close()


def lotes_ia_incompletos():
    """Lotes que se quedaron a medias (ver _reanudar_lotes_al_arrancar) --
    con esto el arranque del proceso puede retomar cada uno justo donde se
    quedó en vez de perder el trabajo ya hecho."""
    conn = get_connection()
    lotes = conn.execute("SELECT * FROM lotes_ia").fetchall()
    resultado = []
    for lote in lotes:
        pendientes = conn.execute(
            "SELECT candidato_id, archivo_id FROM lotes_ia_pendientes WHERE lote_id = ?", (lote["lote_id"],)
        ).fetchall()
        if not pendientes:
            continue
        resultado.append({
            "lote_id": lote["lote_id"], "usuario_id": lote["usuario_id"], "titulo": lote["titulo"],
            "total": lote["total"], "pendientes": [(p["candidato_id"], p["archivo_id"]) for p in pendientes],
        })
    conn.close()
    return resultado


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


def rellenar_huecos_candidato(candidato_id, extraido: dict):
    """Como actualizar_candidato, pero solo rellena lo que está vacío --
    pensado para volver a extraer el CV de una ficha que YA existe (p.ej. al
    resubir un PDF de lote sobre fichas ya creadas) sin pisar nada que el
    reclutador haya editado a mano.

    formacion/experiencia (el texto libre "antiguo"), formacion_json/
    experiencia_json (el historial estructurado) y extra_fields (Idiomas,
    Carnet de conducir...) SÍ se sobrescriben aunque ya tuvieran algo --
    todos son casi siempre resultado de una extracción anterior, nunca algo
    que un reclutador escriba a mano de cero (formacion/experiencia además
    ya está marcado en la ficha como "dato antiguo" con su propio botón de
    borrar). Son justo los que salían mal con el extractor local de antes de
    que se corrigiera (ver cv_extraction.py) -- incluido formacion_json/
    experiencia_json, que en un primer intento de este mismo arreglo se
    dejó protegido "solo si estaba vacío" pensando en no pisar el historial
    de más confianza que pone Gemini, pero eso también bloqueaba corregir un
    historial estructurado que el propio extractor local ya había rellenado
    MAL en una tanda anterior (el caso real que lo reveló: mismo problema
    que ya se había arreglado para formacion/experiencia, solo que un paso
    después). Si algún día hace falta proteger una tarjeta que un reclutador
    añadió a mano con "+ Añadir estudio/experiencia" sin haber vuelto a
    extraer el PDF, hará falta guardar de qué vino cada tarjeta -- por ahora
    ese caso no se ha dado y sobrescribir es lo que corrige el problema real."""
    candidato = get_candidato(candidato_id)
    if candidato is None:
        return False
    campos = {}
    for campo in CAMPOS:
        if campo in ("estado", "notas", "formacion", "experiencia"):
            continue
        valor_nuevo = extraido.get(campo)
        if valor_nuevo and not candidato.get(campo):
            campos[campo] = valor_nuevo
    for campo in ("formacion", "experiencia"):
        valor_nuevo = extraido.get(campo)
        if valor_nuevo:
            campos[campo] = valor_nuevo
    # El texto libre "antiguo" de esa misma tanda queda de más en cuanto hay
    # historial ESTRUCTURADO (antes solo lo rellenaba Gemini, ahora también
    # el extractor local para los CV con el patrón habitual -- ver
    # cv_extraction._parsear_formacion_local): se limpia para que la ficha
    # muestre solo las tarjetas, no las dos cosas repetidas.
    if extraido.get("formacion_json"):
        campos["formacion_json"] = extraido["formacion_json"]
        campos["formacion"] = None
    if extraido.get("experiencia_json"):
        campos["experiencia_json"] = extraido["experiencia_json"]
        campos["experiencia"] = None
    extra_nuevo = extraido.get("extra_fields") or {}
    if extra_nuevo:
        campos["extra_fields"] = {**(candidato.get("extra_fields") or {}), **extra_nuevo}
    if not campos:
        return False
    actualizar_candidato(candidato_id, campos)
    return True


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
    """Comparte cada candidato con `usuario_id` -- compartir DIRECTO es
    EXCLUSIVO: si el candidato ya estaba compartido con otra persona (por
    cualquiera de los dos caminos, directo aquí o vía Informes), se le quita
    el acceso a esa persona antes de dárselo al nuevo destinatario. Así un
    candidato tiene como mucho un responsable DIRECTO a la vez, en vez de
    acumular gente cada vez que se re-comparte a alguien distinto (ver
    confirmarCompartirCandidatos en el frontend, que avisa de este cambio
    antes de hacerlo). Para cambiar quién es ese responsable directo, se
    vuelve a compartir con la persona nueva (no hay un "transferir" aparte).

    Esto es EXCLUSIVO SOLO en este camino -- no afecta a compartir_vacante
    (más abajo), que es intencionalmente lo contrario: una vacante SÍ puede
    tener varios responsables a la vez (un area manager o el director de
    operaciones necesitan ver TODAS las vacantes que se están compartiendo
    en cada momento, no solo la última). Un candidato puede perfectamente
    tener un responsable directo Y, a la vez, ser visible para varios
    responsables de su vacante -- son dos niveles de acceso distintos, no
    una contradicción."""
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


def get_candidato_compartido_por(candidato_id, usuario_id):
    """Quién compartió este candidato con este destinatario en concreto --
    para comprobar que solo esa misma persona (o un admin) puede quitarle
    el acceso o reasignarlo a otro."""
    conn = get_connection()
    row = conn.execute(
        "SELECT compartido_por FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id = ?",
        (candidato_id, usuario_id),
    ).fetchone()
    conn.close()
    return row["compartido_por"] if row else None


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


def candidatos_compartidos_con(usuario_id, empresa=None):
    """Todos los candidatos a los que este usuario tiene acceso, por
    CUALQUIERA de las tres vías de usuario_tiene_acceso_candidato (directo,
    vía Informes, o por ser responsable de la vacante entera), como una
    única lista de fichas completas -- mismo formato que list_candidatos,
    con vacante_puesto/vacante_centro ya resueltos aparte (quien no tiene el
    módulo completo no puede pedir /vacantes para resolverlo él mismo).
    Antes esto eran dos listados con lógicas y formatos de tarjeta distintos
    en Reclutamiento (uno agrupado por vacante con fichas completas, otro
    agrupado por tanda con el formato de una respuesta de test) -- se
    unifican aquí para que la pantalla de "Compartidos" sea una sola lista,
    sin duplicar ni la consulta ni el pintado."""
    conn = get_connection()
    clausula_empresa = "AND c.empresa = ?" if empresa else ""
    params_empresa = (empresa,) if empresa else ()
    ids = set()
    for row in conn.execute(f"""
        SELECT c.id FROM candidato_compartidos cc JOIN candidatos c ON c.id = cc.candidato_id
        WHERE cc.usuario_id = ? {clausula_empresa}
    """, (usuario_id, *params_empresa)):
        ids.add(row["id"])
    for row in conn.execute(f"""
        SELECT c.id FROM informe_compartidos ic JOIN candidatos c ON c.id = ic.candidato_id
        WHERE ic.usuario_id = ? {clausula_empresa}
    """, (usuario_id, *params_empresa)):
        ids.add(row["id"])
    for row in conn.execute(f"""
        SELECT c.id FROM candidatos c JOIN vacante_compartidos vc ON vc.vacante_id = c.vacante_id
        WHERE vc.usuario_id = ? {clausula_empresa}
    """, (usuario_id, *params_empresa)):
        ids.add(row["id"])
    if not ids:
        conn.close()
        return []
    marcadores = ",".join("?" * len(ids))
    rows = conn.execute(f"""
        SELECT c.*, json_extract(r.datos_json, '$.RESULTADO') AS test_resultado,
               v.puesto AS vacante_puesto, v.centro AS vacante_centro
        FROM candidatos c
        LEFT JOIN informe_respuestas r ON r.id = c.respuesta_id
        LEFT JOIN vacantes v ON v.id = c.vacante_id
        WHERE c.id IN ({marcadores})
        ORDER BY c.actualizado_en DESC
    """, list(ids)).fetchall()
    candidatos = [_row_to_dict(r) for r in rows]
    mapa_compartidos = _compartidos_por_candidato(conn, [c["id"] for c in candidatos])
    conn.close()
    for c in candidatos:
        c["compartidos"] = mapa_compartidos.get(c["id"], [])
    return candidatos


def candidatos_compartidos_por(username, empresa=None):
    """Espejo de candidatos_compartidos_con, pero para el lado de quien
    COMPARTE en vez de quien recibe: todos los candidatos que este usuario
    ha compartido con alguien, por cualquiera de las tres vías (directo,
    vía Informes, o por compartir la vacante entera con un responsable),
    como una única lista de fichas completas -- unifica lo que antes eran
    "Solicitudes que has compartido" (agrupada por vacante) y "Compartidos
    por ti" (agrupada por tanda+destinatario, con el formato crudo de una
    respuesta de test) en una sola fuente de datos. Cada ficha trae su
    "compartidos" (ver _compartidos_por_candidato) con quién exactamente la
    tiene -- eso es lo que permite "Dejar de compartir" a una persona en
    concreto sin afectar a las demás, y detectar qué compartir individual
    hay que reasignar en "Cambiar destinatario"."""
    conn = get_connection()
    clausula_empresa = "AND c.empresa = ?" if empresa else ""
    params_empresa = (empresa,) if empresa else ()
    ids = set()
    for row in conn.execute(f"""
        SELECT c.id FROM candidato_compartidos cc JOIN candidatos c ON c.id = cc.candidato_id
        WHERE cc.compartido_por = ? {clausula_empresa}
    """, (username, *params_empresa)):
        ids.add(row["id"])
    for row in conn.execute(f"""
        SELECT c.id FROM informe_compartidos ic JOIN candidatos c ON c.id = ic.candidato_id
        WHERE ic.compartido_por = ? {clausula_empresa}
    """, (username, *params_empresa)):
        ids.add(row["id"])
    for row in conn.execute(f"""
        SELECT c.id FROM candidatos c JOIN vacante_compartidos vc ON vc.vacante_id = c.vacante_id
        WHERE vc.compartido_por = ? {clausula_empresa}
    """, (username, *params_empresa)):
        ids.add(row["id"])
    if not ids:
        conn.close()
        return []
    marcadores = ",".join("?" * len(ids))
    rows = conn.execute(f"""
        SELECT c.*, json_extract(r.datos_json, '$.RESULTADO') AS test_resultado,
               v.puesto AS vacante_puesto, v.centro AS vacante_centro
        FROM candidatos c
        LEFT JOIN informe_respuestas r ON r.id = c.respuesta_id
        LEFT JOIN vacantes v ON v.id = c.vacante_id
        WHERE c.id IN ({marcadores})
        ORDER BY c.actualizado_en DESC
    """, list(ids)).fetchall()
    candidatos = [_row_to_dict(r) for r in rows]
    mapa_compartidos = _compartidos_por_candidato(conn, [c["id"] for c in candidatos])
    conn.close()
    for c in candidatos:
        c["compartidos"] = mapa_compartidos.get(c["id"], [])
    return candidatos


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
    # Sin PRAGMA foreign_keys activo en esta conexión no hay ON DELETE
    # CASCADE de verdad -- se limpia a mano, igual que ya hace
    # eliminar_vacante con vacante_compartidos, para no dejar filas
    # huérfanas de "compartido con X" apuntando a un candidato borrado.
    conn.execute("DELETE FROM candidato_compartidos WHERE candidato_id = ?", (candidato_id,))
    conn.execute("DELETE FROM informe_compartidos WHERE candidato_id = ?", (candidato_id,))
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
    # Si ya existe un archivo con el mismo nombre y el mismo contenido para
    # este candidato (p.ej. reintentar subir el mismo PDF de lote varias
    # veces), no se crea una copia nueva -- se reutiliza el que ya había,
    # actualizando su fecha para que quede como "el más reciente".
    hash_nuevo = hashlib.sha256(contenido).hexdigest()
    conn = get_connection()
    existente = conn.execute(
        "SELECT id FROM candidato_archivos WHERE candidato_id = ? AND nombre_original = ? AND contenido_hash = ?",
        (candidato_id, nombre_original, hash_nuevo),
    ).fetchone()
    if existente:
        conn.execute("UPDATE candidato_archivos SET subido_en = datetime('now') WHERE id = ?", (existente["id"],))
        conn.commit()
        conn.close()
        return existente["id"]
    carpeta = os.path.join(UPLOADS_DIR, str(candidato_id))
    os.makedirs(carpeta, exist_ok=True)
    ext = os.path.splitext(nombre_original)[1]
    n = conn.execute("SELECT COUNT(*) FROM candidato_archivos WHERE candidato_id = ?", (candidato_id,)).fetchone()[0]
    ruta = os.path.join(carpeta, f"{n + 1}{ext}")
    with open(ruta, "wb") as f:
        f.write(contenido)
    cur = conn.execute(
        "INSERT INTO candidato_archivos (candidato_id, nombre_original, ruta, contenido_hash) VALUES (?, ?, ?, ?)",
        (candidato_id, nombre_original, ruta, hash_nuevo),
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
