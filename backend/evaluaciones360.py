import re
import unicodedata

import auth
from db import get_connection

# Las 31 preguntas Likert + 3 abiertas del proceso "Evaluación 360 Krispy
# Kreme" ya usado en Bizneo HR durante 2025 -- se replican tal cual (mismo
# texto, mismos 7 grupos, que son los valores de la empresa) para no romper
# la continuidad de un proceso que la gente ya conoce. N/A se añade como
# opción de respuesta (valor NULL en eval360_respuestas), algo que Bizneo no
# tenía y el usuario pidió explícitamente.
PREGUNTAS_SEED = [
    ("likert", "INTEGRIDAD", "¿Actúa de forma transparente e inspira confianza en los demás?"),
    ("likert", "INTEGRIDAD", "¿Asume su responsabilidad sin culpar a otras personas?"),
    ("likert", "GENEROSIDAD", "¿Busca formas de generar un impacto positivo en la comunidad o en su entorno?"),
    ("likert", "POSITIVIDAD", "¿Busca soluciones constructivas ante los conflictos?"),
    ("likert", "MOMENTOS MÁGICOS", "¿Colabora activamente para cubrir las necesidades de sus clientes internos?"),
    ("likert", "GENEROSIDAD", "¿Comparte sus ideas, conocimientos y experiencia con el equipo?"),
    ("likert", "DAMOS RESULTADOS", "¿Define objetivos claros y medibles, trabajando con intención y método?"),
    ("likert", "DAMOS RESULTADOS", "¿Demuestra comprensión del negocio y busca aprender continuamente para mejorarlo?"),
    ("likert", "INTEGRIDAD", "¿Dice la verdad en cualquier circunstancia sin importar las consecuencias?"),
    ("likert", "POSITIVIDAD", "¿Enfrenta situaciones difíciles con una actitud optimista?"),
    ("likert", "LLEVAMOS EL TALENTO", "¿Esta persona demuestra creer en las demás, en sus buenas intenciones y en su potencial?"),
    ("likert", "DAMOS RESULTADOS", "¿Identifica y aprovecha oportunidades para mejorar la eficiencia, el impacto y la rentabilidad del negocio?"),
    ("likert", "LLEVAMOS EL TALENTO", "¿Identifica y potencia las fortalezas del equipo, sacando lo mejor de cada persona?"),
    ("likert", "LLEVAMOS EL TALENTO", "¿Lidera desde el corazón, actuando con humildad y respeto hacia los demás?"),
    ("likert", "LLEVAMOS EL TALENTO", "¿Muestra una actitud constante de aprendizaje y mejora para aumentar su impacto en el equipo y la organización?"),
    ("likert", "DETERMINACIÓN", "¿Pone todo su empeño en lo que hace, incluso en situaciones exigentes?"),
    ("likert", "DAMOS RESULTADOS", "¿Prioriza lo importante y actúa de forma coherente con esas prioridades?"),
    ("likert", "DETERMINACIÓN", "¿Realiza su trabajo buscando la excelencia en los resultados?"),
    ("likert", "DETERMINACIÓN", "¿Se compromete con lo que dice y cumple lo acordado?"),
    ("likert", "MOMENTOS MÁGICOS", "¿Simplifica procesos y elimina barreras innecesarias en su forma de trabajar?"),
    ("likert", "MOMENTOS MÁGICOS", "¿Tiene en cuenta la experiencia de los Fans/Clientes en la toma de decisiones?"),
    ("likert", "GENEROSIDAD", "¿Trabaja como parte de un equipo y comparte los logros con los demás?"),
    ("likert", "POSITIVIDAD", "¿Transmite energía positiva, alegría e inspiración a las personas de su entorno?"),
    ("likert", "MOMENTOS MÁGICOS", "¿Utiliza herramientas y tecnología para mejorar la calidad de las interacciones?"),
    ("likert", "POSITIVIDAD", "Da retroalimentación positiva, clara y sin sarcasmo"),
    ("likert", "POSITIVIDAD", "Genera un ambiente de Buen Rollo con las personas que le rodean"),
    ("likert", "POSITIVIDAD", "Reconoce a los demás y genera una cultura de reconocimiento"),
    ("likert", "DAMOS RESULTADOS", "Sabe analizar datos y crea buenos planes de acción"),
    ("likert", "POSITIVIDAD", "Sabe enfrentar situaciones dificiles sin perder la calma ni ser insultante o faltar el respeto"),
    ("likert", "POSITIVIDAD", "Sabe reconducir un mal comportamiento o situación, sabe tener conversaciones difíciles"),
    ("likert", "DAMOS RESULTADOS", "Se interesa por lograr los objetivos del equipo y de la empresa"),
    ("abierta", None, "¿Qué es lo que esta persona debería seguir haciendo, porque genera un impacto positivo en ti, en el equipo o en los Fans?"),
    ("abierta", None, "¿Qué te gustaría que esta persona empiece a hacer, porque podría potenciar aún más su talento o el de quienes le rodean?"),
    ("abierta", None, "¿Qué hábito o comportamiento crees que esta persona debería dejar de hacer, para crecer y fortalecer aún más su impacto positivo?"),
]


def ensure_eval360_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_puestos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            nombre TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)
    # puesto_padre_id se añadió después de crear la tabla -- separado del
    # jefe_directo_id de eval360_personas a propósito: son dos jerarquías
    # distintas (organigrama de PUESTOS, tipo Bizneo, donde un puesto puede
    # tener varias personas -- ej. varios "Gerente de Retail" -- frente al
    # organigrama de PERSONAS concretas que ya existía).
    cols_puestos = {row[1] for row in conn.execute("PRAGMA table_info(eval360_puestos)")}
    if "puesto_padre_id" not in cols_puestos:
        conn.execute("ALTER TABLE eval360_puestos ADD COLUMN puesto_padre_id INTEGER REFERENCES eval360_puestos(id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            nombre_completo TEXT NOT NULL,
            puesto_id INTEGER REFERENCES eval360_puestos(id),
            jefe_directo_id INTEGER REFERENCES eval360_personas(id),
            usuario_id INTEGER REFERENCES usuarios(id),
            activo INTEGER NOT NULL DEFAULT 1,
            orden INTEGER NOT NULL DEFAULT 0,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Email de contacto de cada persona -- no tiene por qué coincidir con el
    # de su cuenta de portal (usuario_id, si tiene una): sirve para poder
    # escribirle por fuera (botón mailto en campañas) aunque no tenga acceso
    # al portal todavía, y como base para sugerirle un username al crearle
    # un acceso (ver crear_acceso_para_persona).
    cols_personas_email = {row[1] for row in conn.execute("PRAGMA table_info(eval360_personas)")}
    if "email" not in cols_personas_email:
        conn.execute("ALTER TABLE eval360_personas ADD COLUMN email TEXT")
    # eval360_personas.puesto_id de arriba se queda en la tabla sin usarse
    # (una persona real puede ocupar más de un puesto a la vez -- ej. Jesús
    # Collado es Director Financiero Y Director de Desarrollo -- así que un
    # solo FK no bastaba) pero no se borra la columna para no depender de
    # ALTER TABLE ... DROP COLUMN (soporte desigual según la versión de
    # SQLite). Toda la asignación real de puestos vive desde aquí en esta
    # tabla puente, que si permite muchos-a-muchos.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_persona_puestos (
            persona_id INTEGER NOT NULL REFERENCES eval360_personas(id),
            puesto_id INTEGER NOT NULL REFERENCES eval360_puestos(id),
            PRIMARY KEY (persona_id, puesto_id)
        )
    """)
    # Migración única: las personas que ya tenían un puesto_id asignado (el
    # modelo viejo, uno-a-uno) pasan a tener esa misma asignación en la
    # tabla puente, para no perder datos ya cargados al desplegar esto.
    if not conn.execute("SELECT 1 FROM eval360_persona_puestos LIMIT 1").fetchone():
        for row in conn.execute("SELECT id, puesto_id FROM eval360_personas WHERE puesto_id IS NOT NULL"):
            conn.execute(
                "INSERT OR IGNORE INTO eval360_persona_puestos (persona_id, puesto_id) VALUES (?, ?)",
                (row["id"], row["puesto_id"]),
            )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_preguntas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            tipo TEXT NOT NULL,
            grupo TEXT,
            texto TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activa INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_campanas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            nombre TEXT NOT NULL,
            periodo_desde TEXT,
            periodo_hasta TEXT,
            estado TEXT NOT NULL DEFAULT 'borrador',
            creado_por INTEGER REFERENCES usuarios(id),
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_asignaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campana_id INTEGER NOT NULL REFERENCES eval360_campanas(id),
            evaluado_persona_id INTEGER NOT NULL REFERENCES eval360_personas(id),
            evaluador_persona_id INTEGER NOT NULL REFERENCES eval360_personas(id),
            relacion TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            completado_en TEXT,
            UNIQUE(campana_id, evaluado_persona_id, evaluador_persona_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval360_respuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asignacion_id INTEGER NOT NULL REFERENCES eval360_asignaciones(id),
            pregunta_id INTEGER NOT NULL REFERENCES eval360_preguntas(id),
            valor INTEGER,
            comentario TEXT,
            UNIQUE(asignacion_id, pregunta_id)
        )
    """)
    # Semilla única de las 31+3 preguntas reales -- solo si la tabla está
    # vacía, para no duplicar en cada arranque ni pisar ediciones que se
    # hagan después desde la pantalla de Preguntas.
    if not conn.execute("SELECT 1 FROM eval360_preguntas LIMIT 1").fetchone():
        for orden, (tipo, grupo, texto) in enumerate(PREGUNTAS_SEED):
            conn.execute(
                "INSERT INTO eval360_preguntas (empresa, tipo, grupo, texto, orden) VALUES ('kk', ?, ?, ?, ?)",
                (tipo, grupo, texto, orden),
            )
    conn.commit()
    conn.close()


def list_usuarios_seleccionables():
    """Para el buscador de "vincular a cuenta" al editar una persona del
    organigrama -- solo id/nombre/username, nunca el pin (a diferencia de
    GET /auth/users, que es admin-only porque expone el pin en claro)."""
    conn = get_connection()
    rows = conn.execute("SELECT id, nombre, username FROM usuarios ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Preguntas
# ---------------------------------------------------------------------------

def list_preguntas(empresa="kk", solo_activas=False):
    conn = get_connection()
    clauses = ["empresa = ?"]
    params = [empresa]
    if solo_activas:
        clauses.append("activa = 1")
    rows = conn.execute(
        f"SELECT * FROM eval360_preguntas WHERE {' AND '.join(clauses)} ORDER BY orden",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_pregunta(empresa, tipo, grupo, texto):
    """Para SAONA, que no hereda los 7 valores de Krispy Kreme -- la semilla
    de PREGUNTAS_SEED solo se inserta para 'kk' (ver ensure_eval360_tables),
    así que cada empresa nueva construye su propio cuestionario desde cero
    en la pantalla de Preguntas."""
    conn = get_connection()
    siguiente_orden = conn.execute(
        "SELECT COALESCE(MAX(orden), -1) + 1 FROM eval360_preguntas WHERE empresa = ?", (empresa,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO eval360_preguntas (empresa, tipo, grupo, texto, orden) VALUES (?, ?, ?, ?, ?)",
        (empresa, tipo, grupo, texto, siguiente_orden),
    )
    pregunta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pregunta_id


def get_pregunta(pregunta_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM eval360_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def actualizar_pregunta(pregunta_id, texto=None, orden=None, activa=None):
    sets, params = [], []
    if texto is not None:
        sets.append("texto = ?")
        params.append(texto)
    if orden is not None:
        sets.append("orden = ?")
        params.append(orden)
    if activa is not None:
        sets.append("activa = ?")
        params.append(1 if activa else 0)
    if not sets:
        return
    conn = get_connection()
    params.append(pregunta_id)
    conn.execute(f"UPDATE eval360_preguntas SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Puestos
# ---------------------------------------------------------------------------

def list_puestos(empresa="kk", solo_activos=True):
    """Incluye nombre del puesto padre (para pintar el árbol) y cuántas
    personas ocupan cada puesto directamente -- ver list_personas_de_puesto
    para el listado completo, con nombre y no solo el conteo."""
    conn = get_connection()
    clauses = ["p.empresa = ?"]
    params = [empresa]
    if solo_activos:
        clauses.append("p.activo = 1")
    rows = conn.execute(f"""
        SELECT p.*, padre.nombre AS puesto_padre_nombre,
               (SELECT COUNT(*) FROM eval360_personas per WHERE per.puesto_id = p.id AND per.activo = 1) AS num_personas
        FROM eval360_puestos p
        LEFT JOIN eval360_puestos padre ON padre.id = p.puesto_padre_id
        WHERE {' AND '.join(clauses)}
        ORDER BY p.nombre
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_puesto(empresa, nombre, puesto_padre_id=None):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO eval360_puestos (empresa, nombre, puesto_padre_id) VALUES (?, ?, ?)",
        (empresa, nombre, puesto_padre_id),
    )
    puesto_id = cur.lastrowid
    conn.commit()
    conn.close()
    return puesto_id


def get_puesto(puesto_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM eval360_puestos WHERE id = ?", (puesto_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def actualizar_puesto(puesto_id, nombre=None, activo=None, puesto_padre_id=-1):
    """puesto_padre_id usa -1 como centinela de "no tocar" (a diferencia de
    None, que sí es un valor válido: significa "raíz, sin padre")."""
    conn = get_connection()
    if nombre is not None:
        conn.execute("UPDATE eval360_puestos SET nombre = ? WHERE id = ?", (nombre, puesto_id))
    if activo is False:
        # Al desactivar un puesto, sus subpuestos no se quedan huérfanos
        # (invisibles en el árbol, colgando de un padre que ya no aparece):
        # pasan a depender directamente de a quién reportaba este puesto --
        # "sus reportes pasan al gerente siguiente", como pidió el usuario.
        padre_actual = conn.execute(
            "SELECT puesto_padre_id FROM eval360_puestos WHERE id = ?", (puesto_id,)
        ).fetchone()
        nuevo_padre_para_hijos = padre_actual["puesto_padre_id"] if padre_actual else None
        conn.execute(
            "UPDATE eval360_puestos SET puesto_padre_id = ? WHERE puesto_padre_id = ?",
            (nuevo_padre_para_hijos, puesto_id),
        )
    if activo is not None:
        conn.execute("UPDATE eval360_puestos SET activo = ? WHERE id = ?", (1 if activo else 0, puesto_id))
    if puesto_padre_id != -1:
        conn.execute("UPDATE eval360_puestos SET puesto_padre_id = ? WHERE id = ?", (puesto_padre_id, puesto_id))
    conn.commit()
    conn.close()


def list_personas_de_puesto(puesto_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.* FROM eval360_personas p
        JOIN eval360_persona_puestos pp ON pp.persona_id = p.id
        WHERE pp.puesto_id = ? AND p.activo = 1
        ORDER BY p.nombre_completo
    """, (puesto_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_puestos_de_persona(persona_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT pu.* FROM eval360_puestos pu
        JOIN eval360_persona_puestos pp ON pp.puesto_id = pu.id
        WHERE pp.persona_id = ?
        ORDER BY pu.nombre
    """, (persona_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_puestos_de_persona(persona_id, puesto_ids: list):
    conn = get_connection()
    conn.execute("DELETE FROM eval360_persona_puestos WHERE persona_id = ?", (persona_id,))
    for puesto_id in puesto_ids:
        conn.execute(
            "INSERT OR IGNORE INTO eval360_persona_puestos (persona_id, puesto_id) VALUES (?, ?)",
            (persona_id, puesto_id),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Personas (organigrama)
# ---------------------------------------------------------------------------

def list_personas(empresa="kk", solo_activos=True):
    """Cada persona trae su lista de puestos (una persona real puede ocupar
    más de uno a la vez, ej. Jesús Collado = Director Financiero + Director
    de Desarrollo) en vez de un único puesto_nombre -- ver eval360_persona_puestos."""
    conn = get_connection()
    clauses = ["p.empresa = ?"]
    params = [empresa]
    if solo_activos:
        clauses.append("p.activo = 1")
    rows = conn.execute(f"""
        SELECT p.*,
               jefe.nombre_completo AS jefe_directo_nombre,
               u.nombre AS usuario_nombre, u.username AS usuario_username
        FROM eval360_personas p
        LEFT JOIN eval360_personas jefe ON jefe.id = p.jefe_directo_id
        LEFT JOIN usuarios u ON u.id = p.usuario_id
        WHERE {' AND '.join(clauses)}
        ORDER BY p.orden, p.nombre_completo
    """, params).fetchall()
    personas = [dict(r) for r in rows]
    if personas:
        placeholders = ",".join("?" for _ in personas)
        puesto_rows = conn.execute(f"""
            SELECT pp.persona_id, pu.id, pu.nombre
            FROM eval360_persona_puestos pp
            JOIN eval360_puestos pu ON pu.id = pp.puesto_id
            WHERE pp.persona_id IN ({placeholders})
            ORDER BY pu.nombre
        """, [p["id"] for p in personas]).fetchall()
        puestos_por_persona = {}
        for r in puesto_rows:
            puestos_por_persona.setdefault(r["persona_id"], []).append({"id": r["id"], "nombre": r["nombre"]})
        for persona in personas:
            persona["puestos"] = puestos_por_persona.get(persona["id"], [])
    conn.close()
    return personas


def get_persona(persona_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM eval360_personas WHERE id = ?", (persona_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_persona_por_usuario(usuario_id, empresa=None):
    conn = get_connection()
    clauses = ["usuario_id = ?", "activo = 1"]
    params = [usuario_id]
    if empresa:
        clauses.append("empresa = ?")
        params.append(empresa)
    row = conn.execute(
        f"SELECT * FROM eval360_personas WHERE {' AND '.join(clauses)}", params
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Espejo con Usuarios (Ajustes): admin/gerente/area_manager se gestionan
# también desde 360 -- aparecen solos en el organigrama (sin tener que darlos
# de alta a mano) y cualquier cambio de nombre en un lado se refleja en el
# otro. A petición expresa: Ajustes se queda con la gente que usa el portal
# a diario, 360 con quien usa solo eso, y el espejo mantiene ambos en sync.
# ---------------------------------------------------------------------------

ROLES_ESPEJO = ("admin", "gerente", "area_manager")


def _empresas_de_usuario(usuario_id, rol) -> list[str]:
    """A qué organigrama(s) de 360 pertenece este usuario -- solo cuando hay
    una señal fiable, si no, lista vacía (no se adivina, ver
    sincronizar_personas_privilegiadas). admin ve las dos marcas. El resto:
    cualquier módulo "saona_*" concedido cuenta como SAONA; cualquier tienda
    sin prefijo "saona_" (ver scraper/stores.py) cuenta como KK. Sin tiendas
    Y sin módulos saona -- como pasó con gerentes de SAONA dados de alta sin
    tienda asignada -- no hay ninguna señal, así que no se devuelve nada."""
    if rol == "admin":
        return ["kk", "saona"]
    empresas = set()
    tiendas = auth.get_tiendas_permitidas(usuario_id)
    for t in tiendas:
        empresas.add("saona" if t.startswith("saona_") else "kk")
    if any(m.startswith("saona_") for m in auth.get_modulos_permitidos(usuario_id)):
        empresas.add("saona")
    return sorted(empresas)


def _get_persona_por_usuario_y_empresa(usuario_id, empresa):
    """A diferencia de get_persona_por_usuario, incluye inactivas -- para no
    recrear un duplicado si alguien la desactivó a propósito desde el
    organigrama."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM eval360_personas WHERE usuario_id = ? AND empresa = ?", (usuario_id, empresa)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _hay_persona_sin_vincular_con_nombre_parecido(empresa, nombre) -> bool:
    """Antes de crear una persona espejo nueva, si ya hay alguien sin
    vincular en esa empresa cuyo primer nombre coincide (ej. el organigrama
    ya tenía "Berta Garcia" a mano y la cuenta se llama "Berta"), no se crea
    un duplicado -- se deja sin tocar para que se vincule a mano desde el
    desplegable de "Cuenta vinculada" del editor de personas."""
    partes_nombre = (nombre or "").strip().split()
    if not partes_nombre:
        return False
    primer_nombre = partes_nombre[0].lower()
    conn = get_connection()
    rows = conn.execute(
        "SELECT nombre_completo FROM eval360_personas WHERE empresa = ? AND usuario_id IS NULL AND activo = 1", (empresa,)
    ).fetchall()
    conn.close()
    for r in rows:
        otras_partes = (r["nombre_completo"] or "").strip().split()
        if otras_partes and otras_partes[0].lower() == primer_nombre:
            return True
    return False


def sincronizar_personas_privilegiadas():
    """Reconciliación idempotente: cada admin/gerente/area_manager con
    cuenta en el portal Y una empresa identificable (ver _empresas_de_usuario)
    tiene una persona espejo en el organigrama de 360, con el nombre al día.
    Se llama cada vez que se abre Organigrama/Accesos en 360 -- barato (unas
    pocas filas) y así nunca hace falta un cron aparte para mantenerlo
    fresco. Si ya hay alguien sin vincular con el mismo nombre de pila, no
    crea nada (evita duplicar a alguien que ya estaba en el organigrama a
    mano, como pasó con "Berta"/"Berta Garcia")."""
    conn = get_connection()
    usuarios = conn.execute(
        f"SELECT id, nombre, rol FROM usuarios WHERE rol IN ({','.join('?' * len(ROLES_ESPEJO))})", ROLES_ESPEJO
    ).fetchall()
    conn.close()
    for u in usuarios:
        usuario_id, nombre, rol = u["id"], u["nombre"], u["rol"]
        for empresa in _empresas_de_usuario(usuario_id, rol):
            persona = _get_persona_por_usuario_y_empresa(usuario_id, empresa)
            if persona is None:
                if _hay_persona_sin_vincular_con_nombre_parecido(empresa, nombre):
                    continue
                crear_persona(empresa, nombre, usuario_id=usuario_id)
            elif persona["nombre_completo"] != nombre:
                actualizar_persona(persona["id"], {"nombre_completo": nombre})


def sincronizar_nombre_a_personas(usuario_id, nombre):
    """Usuario -> personas: al renombrar una cuenta desde Ajustes, refleja
    el nombre nuevo en cualquier persona espejo vinculada (puede haber una
    por empresa, kk y saona)."""
    conn = get_connection()
    rows = conn.execute("SELECT id FROM eval360_personas WHERE usuario_id = ?", (usuario_id,)).fetchall()
    conn.close()
    for r in rows:
        actualizar_persona(r["id"], {"nombre_completo": nombre})


def desvincular_personas_de_usuario(usuario_id):
    """Usuario -> personas al borrar la cuenta: no se borra la persona de
    verdad (arrastraría respuestas de evaluaciones ya hechas y dejaría jefes
    huérfanos a medio evaluar, igual que eliminar_persona) -- se desactiva y
    se desvincula, que es la parte "de verdad" de haber dejado de tener
    acceso al portal."""
    conn = get_connection()
    conn.execute(
        "UPDATE eval360_personas SET activo = 0, usuario_id = NULL WHERE usuario_id = ?", (usuario_id,)
    )
    conn.commit()
    conn.close()


def crear_persona(empresa, nombre_completo, puesto_ids=None, jefe_directo_id=None, usuario_id=None, email=None):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO eval360_personas (empresa, nombre_completo, jefe_directo_id, usuario_id, email)
           VALUES (?, ?, ?, ?, ?)""",
        (empresa, nombre_completo, jefe_directo_id, usuario_id, email),
    )
    persona_id = cur.lastrowid
    conn.commit()
    conn.close()
    if puesto_ids:
        set_puestos_de_persona(persona_id, puesto_ids)
    return persona_id


def actualizar_persona(persona_id, campos: dict):
    if not campos:
        return
    # puesto_ids ya no vive en la propia tabla de personas (ver
    # eval360_persona_puestos) -- se gestiona aparte porque es una lista,
    # no una columna simple.
    if "puesto_ids" in campos:
        set_puestos_de_persona(persona_id, campos["puesto_ids"] or [])
    permitidos = {"nombre_completo", "jefe_directo_id", "usuario_id", "activo", "orden", "email"}
    sets, params = [], []
    for campo, valor in campos.items():
        if campo in permitidos:
            sets.append(f"{campo} = ?")
            params.append(valor)
    if not sets:
        return
    conn = get_connection()
    params.append(persona_id)
    conn.execute(f"UPDATE eval360_personas SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def eliminar_persona(persona_id):
    """No se borra si tiene reportes o preguntas ya respondidas ligadas --
    solo se desactiva, igual que candidatos/vacantes en Reclutamiento, para
    no dejar el organigrama con jefes huérfanos a medio evaluar."""
    conn = get_connection()
    conn.execute("UPDATE eval360_personas SET activo = 0 WHERE id = ?", (persona_id,))
    conn.commit()
    conn.close()


def superior_de(persona_id):
    persona = get_persona(persona_id)
    if not persona or not persona["jefe_directo_id"]:
        return None
    return get_persona(persona["jefe_directo_id"])


def pares_de(persona_id):
    persona = get_persona(persona_id)
    if not persona or not persona["jefe_directo_id"]:
        return []
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM eval360_personas WHERE jefe_directo_id = ? AND id != ? AND activo = 1",
        (persona["jefe_directo_id"], persona_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reportes_de(persona_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM eval360_personas WHERE jefe_directo_id = ? AND activo = 1", (persona_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Campañas
# ---------------------------------------------------------------------------

def list_campanas(empresa="kk"):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM eval360_campanas WHERE empresa = ? ORDER BY creado_en DESC", (empresa,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_campana(campana_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM eval360_campanas WHERE id = ?", (campana_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def crear_campana(empresa, nombre, periodo_desde=None, periodo_hasta=None, creado_por=None):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO eval360_campanas (empresa, nombre, periodo_desde, periodo_hasta, creado_por)
           VALUES (?, ?, ?, ?, ?)""",
        (empresa, nombre, periodo_desde, periodo_hasta, creado_por),
    )
    campana_id = cur.lastrowid
    conn.commit()
    conn.close()
    return campana_id


def actualizar_campana(campana_id, campos: dict):
    permitidos = {"nombre", "periodo_desde", "periodo_hasta"}
    sets, params = [], []
    for campo, valor in campos.items():
        if campo in permitidos:
            sets.append(f"{campo} = ?")
            params.append(valor)
    if not sets:
        return
    conn = get_connection()
    params.append(campana_id)
    conn.execute(f"UPDATE eval360_campanas SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def contar_asignaciones(campana_id):
    conn = get_connection()
    total = conn.execute(
        "SELECT COUNT(*) FROM eval360_asignaciones WHERE campana_id = ?", (campana_id,)
    ).fetchone()[0]
    conn.close()
    return total


def lanzar_campana(campana_id):
    conn = get_connection()
    conn.execute("UPDATE eval360_campanas SET estado = 'abierta' WHERE id = ? AND estado = 'borrador'", (campana_id,))
    conn.commit()
    conn.close()


def cerrar_campana(campana_id):
    conn = get_connection()
    conn.execute("UPDATE eval360_campanas SET estado = 'cerrada' WHERE id = ?", (campana_id,))
    conn.commit()
    conn.close()


def reabrir_campana(campana_id):
    """Vuelve una campaña cerrada a 'abierta' -- no había forma de deshacer
    un cierre (accidental o prematuro) hasta ahora. Los evaluadores
    recuperan sus pendientes ahí mismo (mis_pendientes ya filtra por
    c.estado = 'abierta')."""
    conn = get_connection()
    conn.execute("UPDATE eval360_campanas SET estado = 'abierta' WHERE id = ? AND estado = 'cerrada'", (campana_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Asignaciones (quién evalúa a quién) y autopropuesta
# ---------------------------------------------------------------------------

def _insertar_asignacion(campana_id, evaluado_persona_id, evaluador_persona_id, relacion):
    conn = get_connection()
    conn.execute(
        """INSERT OR IGNORE INTO eval360_asignaciones
           (campana_id, evaluado_persona_id, evaluador_persona_id, relacion)
           VALUES (?, ?, ?, ?)""",
        (campana_id, evaluado_persona_id, evaluador_persona_id, relacion),
    )
    conn.commit()
    conn.close()


def autopropuesta_evaluadores(persona_id):
    """Superior + pares + reportes desde el organigrama, más la
    autoevaluación -- la sugerencia inicial que se le muestra a RRHH al
    añadir un evaluado a una campaña, siempre editable después."""
    propuesta = [(persona_id, "autoevaluacion")]
    superior = superior_de(persona_id)
    if superior:
        propuesta.append((superior["id"], "superior"))
    for par in pares_de(persona_id):
        propuesta.append((par["id"], "par"))
    for reporte in reportes_de(persona_id):
        propuesta.append((reporte["id"], "reporte"))
    return propuesta


def agregar_evaluado_a_campana(campana_id, evaluado_persona_id):
    """No hace nada si ya se había añadido antes -- así reabrir el panel de
    un evaluado ya añadido no duplica evaluadores ni pisa ajustes manuales
    que RRHH ya hubiera hecho sobre esa lista."""
    conn = get_connection()
    ya_existe = conn.execute(
        "SELECT 1 FROM eval360_asignaciones WHERE campana_id = ? AND evaluado_persona_id = ? LIMIT 1",
        (campana_id, evaluado_persona_id),
    ).fetchone()
    conn.close()
    if ya_existe:
        return
    for evaluador_id, relacion in autopropuesta_evaluadores(evaluado_persona_id):
        _insertar_asignacion(campana_id, evaluado_persona_id, evaluador_id, relacion)


def quitar_evaluado_de_campana(campana_id, evaluado_persona_id):
    conn = get_connection()
    conn.execute(
        "DELETE FROM eval360_asignaciones WHERE campana_id = ? AND evaluado_persona_id = ? AND estado != 'completada'",
        (campana_id, evaluado_persona_id),
    )
    conn.commit()
    conn.close()


def agregar_evaluador_manual(campana_id, evaluado_persona_id, evaluador_persona_id):
    _insertar_asignacion(campana_id, evaluado_persona_id, evaluador_persona_id, "manual")


def get_asignacion(asignacion_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM eval360_asignaciones WHERE id = ?", (asignacion_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def quitar_asignacion(asignacion_id):
    """No quita evaluaciones ya completadas -- RRHH puede arrepentirse de un
    evaluador antes de que responda, pero no puede hacer desaparecer una
    respuesta ya dada."""
    conn = get_connection()
    conn.execute("DELETE FROM eval360_asignaciones WHERE id = ? AND estado != 'completada'", (asignacion_id,))
    conn.commit()
    conn.close()


def list_evaluados_de_campana(campana_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.id, p.nombre_completo, p.puesto_id, p.email,
               COUNT(a.id) AS total_evaluadores,
               SUM(CASE WHEN a.estado = 'completada' THEN 1 ELSE 0 END) AS completadas
        FROM eval360_asignaciones a
        JOIN eval360_personas p ON p.id = a.evaluado_persona_id
        WHERE a.campana_id = ?
        GROUP BY p.id
        ORDER BY p.nombre_completo
    """, (campana_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_evaluadores_de_evaluado(campana_id, evaluado_persona_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT a.*, p.nombre_completo AS evaluador_nombre, p.email AS evaluador_email
        FROM eval360_asignaciones a
        JOIN eval360_personas p ON p.id = a.evaluador_persona_id
        WHERE a.campana_id = ? AND a.evaluado_persona_id = ?
        ORDER BY a.relacion, p.nombre_completo
    """, (campana_id, evaluado_persona_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Responder evaluaciones
# ---------------------------------------------------------------------------

def personas_de_usuario(usuario_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM eval360_personas WHERE usuario_id = ? AND activo = 1", (usuario_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mis_pendientes(usuario_id):
    ids = [p["id"] for p in personas_de_usuario(usuario_id)]
    if not ids:
        return []
    conn = get_connection()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"""
        SELECT a.id AS asignacion_id, a.relacion, a.estado,
               ev.nombre_completo AS evaluado_nombre,
               c.id AS campana_id, c.nombre AS campana_nombre
        FROM eval360_asignaciones a
        JOIN eval360_campanas c ON c.id = a.campana_id
        JOIN eval360_personas ev ON ev.id = a.evaluado_persona_id
        WHERE a.evaluador_persona_id IN ({placeholders}) AND a.estado = 'pendiente' AND c.estado = 'abierta'
        ORDER BY c.creado_en DESC, ev.nombre_completo
    """, ids).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_formulario_asignacion(asignacion_id):
    asignacion = get_asignacion(asignacion_id)
    if not asignacion:
        return None
    evaluado = get_persona(asignacion["evaluado_persona_id"])
    preguntas = list_preguntas(evaluado["empresa"], solo_activas=True)
    conn = get_connection()
    respuestas = {
        r["pregunta_id"]: dict(r)
        for r in conn.execute("SELECT * FROM eval360_respuestas WHERE asignacion_id = ?", (asignacion_id,)).fetchall()
    }
    conn.close()
    return {
        "asignacion": asignacion,
        "evaluado_nombre": evaluado["nombre_completo"],
        "preguntas": preguntas,
        "respuestas": respuestas,
    }


def guardar_respuesta(asignacion_id, pregunta_id, valor=None, comentario=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO eval360_respuestas (asignacion_id, pregunta_id, valor, comentario)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(asignacion_id, pregunta_id) DO UPDATE SET valor = excluded.valor, comentario = excluded.comentario
    """, (asignacion_id, pregunta_id, valor, comentario))
    conn.commit()
    conn.close()


def finalizar_asignacion(asignacion_id):
    conn = get_connection()
    conn.execute(
        "UPDATE eval360_asignaciones SET estado = 'completada', completado_en = datetime('now') WHERE id = ?",
        (asignacion_id,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Resultados (solo admin, ver evaluaciones360_routes.py)
# ---------------------------------------------------------------------------

def resultados_evaluado(campana_id, evaluado_persona_id):
    conn = get_connection()
    filas_likert = conn.execute("""
        SELECT a.relacion, pr.grupo, r.valor
        FROM eval360_respuestas r
        JOIN eval360_asignaciones a ON a.id = r.asignacion_id
        JOIN eval360_preguntas pr ON pr.id = r.pregunta_id
        WHERE a.campana_id = ? AND a.evaluado_persona_id = ? AND a.estado = 'completada'
              AND pr.tipo = 'likert' AND r.valor IS NOT NULL
    """, (campana_id, evaluado_persona_id)).fetchall()
    comentarios = conn.execute("""
        SELECT a.relacion, ev.nombre_completo AS evaluador_nombre, pr.texto AS pregunta_texto, r.comentario
        FROM eval360_respuestas r
        JOIN eval360_asignaciones a ON a.id = r.asignacion_id
        JOIN eval360_preguntas pr ON pr.id = r.pregunta_id
        JOIN eval360_personas ev ON ev.id = a.evaluador_persona_id
        WHERE a.campana_id = ? AND a.evaluado_persona_id = ? AND a.estado = 'completada'
              AND pr.tipo = 'abierta' AND r.comentario IS NOT NULL AND r.comentario != ''
        ORDER BY a.relacion, ev.nombre_completo
    """, (campana_id, evaluado_persona_id)).fetchall()
    conn.close()

    por_grupo, por_relacion = {}, {}
    for f in filas_likert:
        por_grupo.setdefault(f["grupo"], []).append(f["valor"])
        por_relacion.setdefault(f["relacion"], []).append(f["valor"])
    promedio = lambda valores: round(sum(valores) / len(valores), 2)
    return {
        "promedio_por_grupo": {g: promedio(v) for g, v in por_grupo.items()},
        "promedio_por_relacion": {r: promedio(v) for r, v in por_relacion.items()},
        "promedio_general": promedio([v for vs in por_grupo.values() for v in vs]) if por_grupo else None,
        "comentarios_abiertos": [dict(c) for c in comentarios],
    }


# ---------------------------------------------------------------------------
# Accesos: crear cuentas de portal para personas del organigrama que todavía
# no tienen una (para poder entrar y responder sus evaluaciones). Separado a
# propósito de "vincular a cuenta existente" (el selector de la ficha de
# persona) -- esto CREA cuentas nuevas, así que solo aplica a quien todavía
# no tiene ninguna, para no pisar jamás las cuentas reales del día a día
# (gerentes, area manager, etc. que ya usan el portal para otras cosas).
# ---------------------------------------------------------------------------

def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def sugerir_local_part(nombre_completo: str) -> str:
    """De 'Saul Vasquez Garcia' saca 'saul.v' -- primer nombre + inicial del
    primer apellido, sin tildes ni espacios. Mismo patrón que ya usa la
    empresa para el email (nombre.inicialdeapellido@krispykreme.es); se
    reutiliza tal cual como base del username al crear un acceso."""
    partes = (nombre_completo or "").strip().split()
    if not partes:
        return "persona"
    nombre = re.sub(r"[^a-z0-9]", "", _sin_tildes(partes[0]).lower())
    inicial = re.sub(r"[^a-z0-9]", "", _sin_tildes(partes[1]).lower())[:1] if len(partes) > 1 else ""
    base = f"{nombre}.{inicial}" if inicial else nombre
    return base or "persona"


def list_personas_con_estado_acceso(empresa="kk"):
    """Todas las personas activas del organigrama (no solo las que aún no
    tienen cuenta) -- a diferencia de la extinta list_personas_sin_acceso,
    esto hace que una persona a la que se le acaba de crear el acceso siga
    apareciendo en la pestaña "Accesos" (ahora con tiene_acceso=True), en vez
    de desaparecer de la lista en el siguiente refresco."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.id, p.nombre_completo, p.email, p.usuario_id, u.username, u.pin
        FROM eval360_personas p
        LEFT JOIN usuarios u ON u.id = p.usuario_id
        WHERE p.empresa = ? AND p.activo = 1
        ORDER BY p.nombre_completo
    """, (empresa,)).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "nombre_completo": r["nombre_completo"],
            "email": r["email"],
            "tiene_acceso": r["usuario_id"] is not None,
            "usuario_id": r["usuario_id"],
            "username": r["username"],
            "pin": r["pin"],
        }
        for r in rows
    ]


def crear_acceso_para_persona(persona_id):
    """Username desambiguado contra TODOS los usuarios existentes (los del
    día a día incluidos) para que nunca choquen. El PIN no lo reparte el
    admin -- se lo crea la propia persona la primera vez que entra con su
    username, igual que el resto de cuentas (ver auth.set_pin_si_no_tiene)."""
    persona = get_persona(persona_id)
    if not persona:
        return None
    if persona["usuario_id"]:
        return {"error": "ya_tiene_cuenta"}
    base = sugerir_local_part(persona["nombre_completo"])
    username = base
    sufijo = 2
    while not auth.username_disponible(username):
        username = f"{base}{sufijo}"
        sufijo += 1
    usuario_id = auth.create_user(username, persona["nombre_completo"], "colaborador")
    modulo = "saona_evaluaciones360" if persona["empresa"] == "saona" else "evaluaciones360"
    auth.set_modulos_permitidos(usuario_id, [modulo])
    actualizar_persona(persona_id, {"usuario_id": usuario_id})
    return {"usuario_id": usuario_id, "username": username}


# ---------------------------------------------------------------------------
# Email de aviso al lanzar una campaña
# ---------------------------------------------------------------------------

def _es_jv(persona_id) -> bool:
    """El departamento "JV" del organigrama (Alessandro Moneta, Arnaud Van
    Coppenolle, Joe Wendling, Maria Ibañez-Fischer, Raphael Duvivier, a fecha
    de esto) usa un dominio y patrón de email distintos al resto del grupo
    -- ver email_de_persona()."""
    conn = get_connection()
    row = conn.execute("""
        SELECT 1 FROM eval360_persona_puestos pp
        JOIN eval360_puestos pu ON pu.id = pp.puesto_id
        WHERE pp.persona_id = ? AND pu.nombre = 'JV'
        LIMIT 1
    """, (persona_id,)).fetchone()
    conn.close()
    return row is not None


def email_de_persona(persona: dict) -> str | None:
    """Email a usar para avisar a esta persona: el guardado a mano en su
    ficha si existe; si no, se deriva del nombre. Todo el grupo usa
    nombre.inicialdeapellido@krispykreme.es (ver sugerir_local_part), EXCEPTO
    el departamento "JV", que usa inicialdenombre+apellido (sin punto, sin
    espacios) @krispykreme.com -- ej. Alessandro Moneta -> amoneta@krispykreme.com,
    Arnaud Van Coppenolle -> avancoppenolle@krispykreme.com."""
    if persona.get("email"):
        return persona["email"]
    partes = (persona.get("nombre_completo") or "").strip().split()
    if not partes:
        return None
    if _es_jv(persona["id"]):
        inicial = re.sub(r"[^a-z0-9]", "", _sin_tildes(partes[0]).lower())[:1]
        apellido = re.sub(r"[^a-z0-9]", "", _sin_tildes("".join(partes[1:])).lower())
        local = f"{inicial}{apellido}" if apellido else inicial
        return f"{local}@krispykreme.com" if local else None
    local = sugerir_local_part(persona["nombre_completo"])
    return f"{local}@krispykreme.es" if local != "persona" else None


def rellenar_emails_automaticos(empresa="kk") -> int:
    """Rellena el email de todas las personas activas de esta empresa que
    todavía no tienen uno guardado, derivándolo del nombre (mismo patrón que
    email_de_persona, incluida la excepción de JV) -- pensado para usarse
    desde el botón de Accesos, no solo al lanzar una campaña."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, nombre_completo, email FROM eval360_personas WHERE empresa = ? AND activo = 1 AND (email IS NULL OR email = '')",
        (empresa,),
    ).fetchall()
    conn.close()
    actualizados = 0
    for r in rows:
        email = email_de_persona(dict(r))
        if email:
            actualizar_persona(r["id"], {"email": email})
            actualizados += 1
    return actualizados


def notificar_campana_lanzada(campana_id) -> dict:
    """Al lanzar una campaña, avisa por email a cada evaluador con al menos
    una asignación pendiente ahí (un email por persona, aunque tenga varias
    evaluaciones que hacer). Best-effort: una persona sin email resoluble o
    un fallo de Resend no interrumpe a las demás, se cuenta como omitida."""
    import boletines as boletines_module

    campana = get_campana(campana_id)
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT ev.id, ev.nombre_completo, ev.email
        FROM eval360_asignaciones a
        JOIN eval360_personas ev ON ev.id = a.evaluador_persona_id
        WHERE a.campana_id = ? AND a.estado = 'pendiente'
    """, (campana_id,)).fetchall()
    conn.close()

    enviados, omitidos = 0, 0
    for r in rows:
        evaluador = dict(r)
        destino = email_de_persona(evaluador)
        if not destino:
            omitidos += 1
            continue
        html = (
            f"<p>Hola {evaluador['nombre_completo']},</p>"
            f"<p>Se ha lanzado la campaña de evaluación 360° <b>{campana['nombre']}</b> "
            f"y tienes evaluaciones pendientes por completar.</p>"
            f"<p>Entra en Krispy Gestiones, sección Evaluaciones 360°, pestaña "
            f"\"Mis evaluaciones\", para responderlas.</p>"
        )
        ok, _error = boletines_module._enviar_email_resend(
            destino, evaluador["nombre_completo"], f"Evaluación 360° pendiente: {campana['nombre']}", html
        )
        if ok:
            enviados += 1
        else:
            omitidos += 1
    return {"enviados": enviados, "omitidos": omitidos}


ensure_eval360_tables()
