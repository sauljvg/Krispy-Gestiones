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
# Puestos
# ---------------------------------------------------------------------------

def list_puestos(empresa="kk", solo_activos=True):
    conn = get_connection()
    clauses = ["empresa = ?"]
    params = [empresa]
    if solo_activos:
        clauses.append("activo = 1")
    rows = conn.execute(
        f"SELECT * FROM eval360_puestos WHERE {' AND '.join(clauses)} ORDER BY nombre",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_puesto(empresa, nombre):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO eval360_puestos (empresa, nombre) VALUES (?, ?)",
        (empresa, nombre),
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


def actualizar_puesto(puesto_id, nombre=None, activo=None):
    conn = get_connection()
    if nombre is not None:
        conn.execute("UPDATE eval360_puestos SET nombre = ? WHERE id = ?", (nombre, puesto_id))
    if activo is not None:
        conn.execute("UPDATE eval360_puestos SET activo = ? WHERE id = ?", (1 if activo else 0, puesto_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Personas (organigrama)
# ---------------------------------------------------------------------------

def list_personas(empresa="kk", solo_activos=True):
    conn = get_connection()
    clauses = ["p.empresa = ?"]
    params = [empresa]
    if solo_activos:
        clauses.append("p.activo = 1")
    rows = conn.execute(f"""
        SELECT p.*, pu.nombre AS puesto_nombre,
               jefe.nombre_completo AS jefe_directo_nombre,
               u.nombre AS usuario_nombre, u.username AS usuario_username
        FROM eval360_personas p
        LEFT JOIN eval360_puestos pu ON pu.id = p.puesto_id
        LEFT JOIN eval360_personas jefe ON jefe.id = p.jefe_directo_id
        LEFT JOIN usuarios u ON u.id = p.usuario_id
        WHERE {' AND '.join(clauses)}
        ORDER BY p.orden, p.nombre_completo
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def crear_persona(empresa, nombre_completo, puesto_id=None, jefe_directo_id=None, usuario_id=None):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO eval360_personas (empresa, nombre_completo, puesto_id, jefe_directo_id, usuario_id)
           VALUES (?, ?, ?, ?, ?)""",
        (empresa, nombre_completo, puesto_id, jefe_directo_id, usuario_id),
    )
    persona_id = cur.lastrowid
    conn.commit()
    conn.close()
    return persona_id


def actualizar_persona(persona_id, campos: dict):
    if not campos:
        return
    permitidos = {"nombre_completo", "puesto_id", "jefe_directo_id", "usuario_id", "activo", "orden"}
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


ensure_eval360_tables()
