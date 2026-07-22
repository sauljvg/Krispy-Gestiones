import re
import secrets

from db import get_connection

# "Todo" = acceso a Reseñas e Informes. El resto, por ahora, solo Reseñas
# (Informes se irá abriendo por rol/compartido a medida que se construya).
ROLES = {
    "admin": "Admin (Todo)",
    "rrhh": "RRHH (Todo)",
    "director_operaciones": "Director de Operaciones (Reseñas)",
    "area_manager": "Area Manager (Reseñas)",
    "gerente": "Gerentes (Reseñas)",
}

PIN_REGEX = re.compile(r"^\d{4}$")


def pin_valido(pin: str) -> bool:
    return bool(PIN_REGEX.match(pin or ""))


def ensure_auth_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pin TEXT,
            nombre TEXT NOT NULL,
            rol TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            token TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            creado TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Migración: la tabla original tenía password_hash (con o sin el CHECK
    # de rol viejo). El login pasó a ser por PIN visible para el admin (no
    # tiene sentido guardarlo hasheado), así que se recrea sin password_hash
    # y con una columna 'pin' de texto plano.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(usuarios)")}
    if "password_hash" in cols:
        conn.execute("ALTER TABLE usuarios RENAME TO usuarios_old")
        conn.execute("""
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                pin TEXT,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL,
                creado TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            INSERT INTO usuarios (id, username, nombre, rol, creado)
            SELECT id, username, nombre, rol, creado FROM usuarios_old
        """)
        conn.execute("DROP TABLE usuarios_old")
        # El único usuario que ya tenía sesión activa en pruebas (saul) queda
        # con el mismo PIN que usaba como contraseña, para no perder acceso.
        conn.execute("UPDATE usuarios SET pin = '1234' WHERE username = 'saul' AND pin IS NULL")

    conn.commit()
    conn.close()


def create_user(username: str, nombre: str, rol: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO usuarios (username, nombre, rol, pin) VALUES (?, ?, ?, NULL)",
        (username, nombre, rol),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def get_user_by_username(username: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM usuarios WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_pin_si_no_tiene(username: str, pin: str) -> bool:
    """Activación de cuenta: solo deja crear el PIN si el usuario todavía no
    tenía uno (evita que cualquiera con solo el username lo sobreescriba)."""
    conn = get_connection()
    row = conn.execute("SELECT id, pin FROM usuarios WHERE username = ?", (username,)).fetchone()
    if row is None or row["pin"] is not None:
        conn.close()
        return False
    conn.execute("UPDATE usuarios SET pin = ? WHERE id = ?", (pin, row["id"]))
    conn.commit()
    conn.close()
    return True


def admin_set_pin(user_id: int, pin: str):
    conn = get_connection()
    conn.execute("UPDATE usuarios SET pin = ? WHERE id = ?", (pin, user_id))
    conn.commit()
    conn.close()


def authenticate_pin(username: str, pin: str):
    user = get_user_by_username(username)
    if user is None or user["pin"] is None:
        return None
    if not secrets.compare_digest(user["pin"], pin):
        return None
    return user


def create_session(usuario_id: int) -> str:
    token = secrets.token_hex(32)
    conn = get_connection()
    conn.execute("INSERT INTO sesiones (token, usuario_id) VALUES (?, ?)", (token, usuario_id))
    conn.commit()
    conn.close()
    return token


def delete_session(token: str):
    conn = get_connection()
    conn.execute("DELETE FROM sesiones WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def get_user_by_token(token: str):
    if not token:
        return None
    conn = get_connection()
    row = conn.execute("""
        SELECT usuarios.* FROM sesiones
        JOIN usuarios ON usuarios.id = sesiones.usuario_id
        WHERE sesiones.token = ?
    """, (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


ensure_auth_tables()
