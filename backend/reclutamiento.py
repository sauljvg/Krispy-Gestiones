import json
import os
import re

from db import DATA_DIR, get_connection

UPLOADS_DIR = os.path.join(DATA_DIR, "uploads", "candidatos")

ESTADOS = ["pendiente", "entrevistado", "contratado", "descartado"]

VACANTE_ESTADOS = ["abierta", "cubierta", "cancelada"]

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


def get_vacante(vacante_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM vacantes WHERE id = ?", (vacante_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    vacante = dict(row)
    conn.close()
    vacante["candidatos"] = list_candidatos(vacante_id=vacante_id)
    return vacante


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
    "sin vacante asignada" en vez de perderse)."""
    conn = get_connection()
    conn.execute("UPDATE candidatos SET vacante_id = NULL WHERE vacante_id = ?", (vacante_id,))
    conn.execute("DELETE FROM vacantes WHERE id = ?", (vacante_id,))
    conn.commit()
    conn.close()


def _row_to_dict(row):
    d = dict(row)
    d["extra_fields"] = json.loads(d.get("extra_fields") or "{}")
    # No se expone la ruta de disco tal cual (igual que cv_ruta en
    # informes.py) -- solo si hay foto o no; la propia foto se sirve por su
    # endpoint dedicado (GET /candidatos/{id}/foto).
    d["tiene_foto"] = bool(d.pop("foto_ruta", None))
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


def get_candidato(candidato_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM candidatos WHERE id = ?", (candidato_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    candidato = _row_to_dict(row)
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
            SELECT t.clave AS tipo_clave, t.empresa, r.hoja, json_extract(r.datos_json, '$.RESULTADO') AS test_resultado
            FROM informe_respuestas r JOIN informe_tipos t ON t.id = r.tipo_id
            WHERE r.id = ?
        """, (candidato["respuesta_id"],)).fetchone()
        if info:
            candidato["informe_tipo_clave"] = info["tipo_clave"]
            candidato["informe_hoja"] = info["hoja"]
            candidato["informe_empresa"] = info["empresa"]
            candidato["test_resultado"] = info["test_resultado"]
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
    conn.close()
    return [_row_to_dict(r) for r in rows]


def crear_candidato(campos: dict, empresa="kk", origen="manual", respuesta_id=None, creado_por=None, vacante_id=None):
    extra_fields = campos.pop("extra_fields", {}) or {}
    # Si no viene ya con una respuesta enlazada (alta manual, CV o
    # importación de una vacante), se comprueba si esta persona ya había
    # respondido un test antes de tener ficha en Reclutamiento — ver
    # buscar_respuesta_huerfana_por_contacto.
    if respuesta_id is None:
        respuesta_id = buscar_respuesta_huerfana_por_contacto(campos.get("telefono"), campos.get("email"))
    valores = {c: campos.get(c) for c in CAMPOS if c in campos}
    conn = get_connection()
    columnas = ["empresa", "origen", "respuesta_id", "creado_por", "extra_fields", "vacante_id"] + list(valores.keys())
    placeholders = ", ".join("?" for _ in columnas)
    params = [empresa, origen, respuesta_id, creado_por, json.dumps(extra_fields, ensure_ascii=False), vacante_id] + list(valores.values())
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
    conn = get_connection()
    for candidato_id in candidato_ids:
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
    (gerentes, area managers) pero sí recibió este candidato en concreto —
    por el nuevo "compartir directo" (candidato_compartidos) o por el camino
    de siempre desde Informes (informe_compartidos, que también guarda
    candidato_id desde que existe el enlace automático con el test)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM candidato_compartidos WHERE candidato_id = ? AND usuario_id = ?", (candidato_id, usuario_id)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT 1 FROM informe_compartidos WHERE candidato_id = ? AND usuario_id = ?", (candidato_id, usuario_id)
        ).fetchone()
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


ensure_reclutamiento_tables()
