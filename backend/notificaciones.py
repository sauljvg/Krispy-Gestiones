from db import get_connection


def ensure_notificaciones_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            mensaje TEXT NOT NULL,
            url TEXT,
            creada_en TEXT NOT NULL DEFAULT (datetime('now')),
            vista_en TEXT
        )
    """)
    conn.commit()
    conn.close()


def crear_notificacion(usuario_id, mensaje, url=None):
    """Campanita genérica del topbar (ver topbar-menu.js) -- pensada para
    avisar de trabajos en segundo plano (BackgroundTasks) que terminan
    cuando el usuario ya no tiene la pantalla delante, como el relleno de
    CVs de un lote (ver _rellenar_huecos_en_segundo_plano en
    reclutamiento_routes.py). No es un log de auditoría: solo lo que interesa
    ver como aviso puntual."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO notificaciones (usuario_id, mensaje, url) VALUES (?, ?, ?)",
        (usuario_id, mensaje, url),
    )
    conn.commit()
    conn.close()


def get_notificaciones(usuario_id, limite=20):
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, mensaje, url, creada_en, vista_en FROM notificaciones
        WHERE usuario_id = ? ORDER BY id DESC LIMIT ?
    """, (usuario_id, limite)).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    return {"total": sum(1 for i in items if not i["vista_en"]), "notificaciones": items}


def marcar_notificaciones_vistas(usuario_id):
    conn = get_connection()
    conn.execute(
        "UPDATE notificaciones SET vista_en = datetime('now') WHERE usuario_id = ? AND vista_en IS NULL",
        (usuario_id,),
    )
    conn.commit()
    conn.close()


ensure_notificaciones_tables()
