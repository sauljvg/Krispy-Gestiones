import datetime

from db import get_connection
import reclutamiento as reclutamiento_module

# Grados de IE University (campus Madrid/Segovia) -- investigado en ie.edu
# (indexado vía bachelorsportal.com; la propia ie.edu redirige en bucle a
# herramientas de scraping automatizado) para el selector del formulario
# público del evento con el IE (pedido explícito del usuario 16/09). Son
# grados (lo que en España se llama "carrera"), no másteres/MBA. "Otra / no
# listada" como válvula de escape si el catálogo real cambia antes de
# actualizar esta lista a mano.
CARRERAS_IE = [
    "Administración de Empresas (BBA)",
    "Administración de Empresas y Data & Business Analytics",
    "Administración de Empresas y Diseño",
    "Administración de Empresas y Diseño de Moda",
    "Administración de Empresas y Humanidades",
    "Administración de Empresas y Relaciones Internacionales",
    "Administración de Empresas y Derecho",
    "Administración de Empresas y Computer Science & IA",
    "Behavior and Social Sciences",
    "Comunicación y Medios Digitales",
    "Economía",
    "Economía y Matemáticas Aplicadas",
    "Economía y Relaciones Internacionales",
    "Relaciones Internacionales",
    "Computer Science and Artificial Intelligence",
    "Data & Business Analytics",
    "Humanidades",
    "Estudios de Arquitectura",
    "Diseño",
    "Diseño de Moda",
    "Derecho (LLB)",
    "Derecho y Relaciones Internacionales",
    "Matemáticas Aplicadas",
    "Environmental Sciences for Sustainability",
    "Philosophy, Politics, Law and Economics (PPLE)",
    "Otra / no listada",
]

# Versión del texto de RGPD que se muestra en el popup del formulario público
# -- se guarda junto a cada candidato QUÉ versión aceptó (ver
# crear_candidato_publico_ie), para poder demostrar qué texto exacto vio en
# caso de cambiarlo más adelante. Subir este número (o la fecha) cada vez que
# cambie el contenido real de privacidad.html#bbdd-ie.
RGPD_TEXTO_VERSION = "2026-09-ie-v1"

ETIQUETA_IE_NOMBRE = "IE"
ETIQUETA_IE_COLOR = "#2563eb"  # azul -- pedido explícito del usuario ("etiqueta de IE en azul")


def ensure_bbdd_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etiquetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL DEFAULT '#6b7280',
            creado_por TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Catálogo GLOBAL (no por empresa) a propósito -- pedido del usuario es
    # una única base con candidatos "de Krispy Kreme o Saona", y una etiqueta
    # como "IE" tiene que servir para filtrar en las dos marcas a la vez.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidato_etiquetas (
            candidato_id INTEGER NOT NULL REFERENCES candidatos(id) ON DELETE CASCADE,
            etiqueta_id INTEGER NOT NULL REFERENCES etiquetas(id) ON DELETE CASCADE,
            asignado_por TEXT,
            asignado_en TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (candidato_id, etiqueta_id)
        )
    """)
    # carrera/idiomas/nacionalidad como columnas propias de candidatos (no
    # dentro de extra_fields) -- así se pueden filtrar con SQL normal desde
    # BBDD sin tener que interpretar JSON libre; se suman a
    # reclutamiento.CAMPOS para que crear_candidato/actualizar_candidato las
    # traten igual que cualquier otro campo conocido de la ficha.
    cols_candidatos = {row[1] for row in conn.execute("PRAGMA table_info(candidatos)")}
    for columna in ("carrera", "idiomas", "nacionalidad", "rgpd_aceptado_en", "rgpd_texto_version"):
        if columna not in cols_candidatos:
            conn.execute(f"ALTER TABLE candidatos ADD COLUMN {columna} TEXT")
    conn.execute(
        "INSERT OR IGNORE INTO etiquetas (nombre, color, creado_por) VALUES (?, ?, ?)",
        (ETIQUETA_IE_NOMBRE, ETIQUETA_IE_COLOR, "sistema"),
    )
    conn.commit()
    conn.close()


def listar_etiquetas():
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.*, COUNT(ce.candidato_id) AS candidatos_count
        FROM etiquetas e LEFT JOIN candidato_etiquetas ce ON ce.etiqueta_id = e.id
        GROUP BY e.id ORDER BY e.nombre
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_etiqueta(nombre, color=None, creado_por=None):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El nombre de la etiqueta no puede estar vacío")
    conn = get_connection()
    existente = conn.execute("SELECT id FROM etiquetas WHERE lower(nombre) = lower(?)", (nombre,)).fetchone()
    if existente:
        conn.close()
        return existente["id"]
    cur = conn.execute(
        "INSERT INTO etiquetas (nombre, color, creado_por) VALUES (?, ?, ?)",
        (nombre, color or "#6b7280", creado_por),
    )
    etiqueta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return etiqueta_id


def eliminar_etiqueta(etiqueta_id):
    conn = get_connection()
    conn.execute("DELETE FROM candidato_etiquetas WHERE etiqueta_id = ?", (etiqueta_id,))
    conn.execute("DELETE FROM etiquetas WHERE id = ?", (etiqueta_id,))
    conn.commit()
    conn.close()


def asignar_etiqueta(candidato_id, etiqueta_id, asignado_por=None):
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO candidato_etiquetas (candidato_id, etiqueta_id, asignado_por) VALUES (?, ?, ?)",
        (candidato_id, etiqueta_id, asignado_por),
    )
    conn.commit()
    conn.close()


def quitar_etiqueta(candidato_id, etiqueta_id):
    conn = get_connection()
    conn.execute(
        "DELETE FROM candidato_etiquetas WHERE candidato_id = ? AND etiqueta_id = ?", (candidato_id, etiqueta_id)
    )
    conn.commit()
    conn.close()


def _asignar_etiqueta_por_nombre(candidato_id, nombre, conn):
    """Usado en altas automáticas por origen (hoy solo el formulario público
    del IE) -- resuelve el id de la etiqueta ya sembrada por
    ensure_bbdd_tables sin que el llamador tenga que conocerlo de antemano.
    Reutiliza la conexión del llamador (no abre/cierra la suya) para quedar
    en la misma transacción que el resto del alta."""
    row = conn.execute("SELECT id FROM etiquetas WHERE lower(nombre) = lower(?)", (nombre,)).fetchone()
    if row:
        conn.execute(
            "INSERT OR IGNORE INTO candidato_etiquetas (candidato_id, etiqueta_id, asignado_por) VALUES (?, ?, ?)",
            (candidato_id, row["id"], "sistema"),
        )


def etiquetas_de_candidatos(candidato_ids):
    if not candidato_ids:
        return {}
    conn = get_connection()
    placeholders = ",".join("?" * len(candidato_ids))
    rows = conn.execute(f"""
        SELECT ce.candidato_id AS candidato_id, e.id AS id, e.nombre AS nombre, e.color AS color
        FROM candidato_etiquetas ce JOIN etiquetas e ON e.id = ce.etiqueta_id
        WHERE ce.candidato_id IN ({placeholders})
        ORDER BY e.nombre
    """, candidato_ids).fetchall()
    conn.close()
    mapa = {}
    for r in rows:
        mapa.setdefault(r["candidato_id"], []).append({"id": r["id"], "nombre": r["nombre"], "color": r["color"]})
    return mapa


def _edad(fecha_nacimiento):
    if not fecha_nacimiento:
        return None
    try:
        nacimiento = datetime.date.fromisoformat(fecha_nacimiento[:10])
    except ValueError:
        return None
    hoy = datetime.date.today()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


def list_bbdd(empresa=None, etiqueta_id=None, estado=None, carrera=None, idioma=None,
              nacionalidad=None, edad_min=None, edad_max=None, q=None):
    """Vista completa de la base de candidatos: TODOS los candidatos de
    Reclutamiento sin importar su estado (pendiente/entrevistado/contratado/
    descartado) ni si están o no asignados a una vacante -- a diferencia de
    abrir una vacante concreta en Reclutamiento, aquí NO se filtra por
    vacante_id/sin_vacante (pedido explícito del usuario 16/09: "todas,
    descartadas, contratadas pendientes todas, con actualización de su
    último estado"). reclutamiento.list_candidatos ya deja "estado" fuera de
    ambigüedad -- es un único campo mutable por ficha, así que listarlo tal
    cual YA es "su último estado", no hace falta ningún histórico aparte.

    Reutiliza list_candidatos tal cual (mismo join con test/cita ya resuelto
    ahí) y añade encima lo propio de BBDD: etiquetas y sus filtros (etiqueta,
    carrera, idiomas, nacionalidad, edad)."""
    candidatos = reclutamiento_module.list_candidatos(empresa=empresa, estado=estado, q=q)
    if etiqueta_id:
        conn = get_connection()
        ids_con_etiqueta = {
            r["candidato_id"] for r in conn.execute(
                "SELECT candidato_id FROM candidato_etiquetas WHERE etiqueta_id = ?", (etiqueta_id,)
            ).fetchall()
        }
        conn.close()
        candidatos = [c for c in candidatos if c["id"] in ids_con_etiqueta]
    if carrera:
        candidatos = [c for c in candidatos if c.get("carrera") and carrera.lower() in c["carrera"].lower()]
    if idioma:
        candidatos = [c for c in candidatos if c.get("idiomas") and idioma.lower() in c["idiomas"].lower()]
    if nacionalidad:
        candidatos = [c for c in candidatos if c.get("nacionalidad") and nacionalidad.lower() in c["nacionalidad"].lower()]
    if edad_min is not None or edad_max is not None:
        filtrados = []
        for c in candidatos:
            edad = _edad(c.get("fecha_nacimiento"))
            if edad is None:
                continue
            if edad_min is not None and edad < edad_min:
                continue
            if edad_max is not None and edad > edad_max:
                continue
            filtrados.append(c)
        candidatos = filtrados

    mapa_etiquetas = etiquetas_de_candidatos([c["id"] for c in candidatos])
    for c in candidatos:
        c["etiquetas"] = mapa_etiquetas.get(c["id"], [])
        c["edad"] = _edad(c.get("fecha_nacimiento"))
    return candidatos


def crear_candidato_publico_ie(campos: dict, empresa: str = "kk") -> int:
    """Alta desde el formulario público del evento IE (sin autenticación) --
    ver bbdd_routes.py:router_publico. Crea la ficha como cualquier otro
    candidato de Reclutamiento (misma tabla, mismos campos conocidos -- ver
    reclutamiento.crear_candidato/CAMPOS), marcada con origen="ie" para poder
    distinguir de dónde vino, con constancia de la aceptación de RGPD (fecha +
    qué versión del texto aceptó, ver RGPD_TEXTO_VERSION) y con la etiqueta
    azul "IE" asignada automáticamente -- pedido explícito del usuario:
    "cuando queramos filtrar por etiqueta, IE nos aparecerá todas las
    personas que se inscribieron desde ese formulario"."""
    candidato_id = reclutamiento_module.crear_candidato(
        dict(campos), empresa=empresa, origen="ie", creado_por="formulario_ie"
    )
    conn = get_connection()
    conn.execute(
        "UPDATE candidatos SET rgpd_aceptado_en = datetime('now'), rgpd_texto_version = ? WHERE id = ?",
        (RGPD_TEXTO_VERSION, candidato_id),
    )
    _asignar_etiqueta_por_nombre(candidato_id, ETIQUETA_IE_NOMBRE, conn)
    conn.commit()
    conn.close()
    return candidato_id


ensure_bbdd_tables()
