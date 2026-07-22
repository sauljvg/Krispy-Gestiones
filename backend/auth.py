import re
import secrets

from db import get_connection

# El rol ya no decide por sí solo a qué módulos entra un usuario (eso llevaba
# a que un rol nuevo heredara accesos "a ciegas") — ahora es solo una etiqueta
# de puesto. El acceso real a cada módulo se elige explícitamente al crear o
# editar el usuario (ver MODULOS y usuario_modulos). "admin" es la única
# excepción: siempre tiene todo, para que nunca se pueda quedar sin acceso a
# Usuarios por un checkbox mal marcado.
ROLES = {
    "admin": "Admin",
    "rrhh": "RRHH",
    "director_operaciones": "Director de Operaciones",
    "area_manager": "Area Manager",
    "gerente": "Gerente",
}

# Módulos que se pueden conceder explícitamente por checkbox al crear/editar
# un usuario. "usuarios" (gestión de cuentas) no está aquí a propósito: sigue
# siendo exclusivo del rol admin, porque de lo contrario cualquiera con ese
# módulo podría cambiarse su propio rol o el de otros.
MODULOS = {
    "resenas": "Reseñas",
    "informes": "Informes",
    "clima": "Clima Laboral",
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
    # A diferencia de usuario_tiendas (sin filas = ve todas), aquí sin filas
    # significa SIN acceso — el checkbox de cada módulo tiene que marcarse a
    # propósito, que es justo el problema que esto resuelve (un usuario nuevo
    # ya no hereda accesos implícitos de su rol).
    modulos_tabla_nueva = not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuario_modulos'"
    ).fetchone()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuario_modulos (
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            modulo TEXT NOT NULL,
            PRIMARY KEY (usuario_id, modulo)
        )
    """)
    if modulos_tabla_nueva:
        # Migración única: a los usuarios que ya existían se les concede lo
        # mismo que ya veían bajo el sistema viejo (admin/rrhh = todo,
        # el resto = solo Reseñas), para no cortarle el acceso a nadie el
        # día que esto se despliega. Los usuarios que se creen DESPUÉS de
        # esto ya no reciben nada por defecto.
        for row in conn.execute("SELECT id, rol FROM usuarios").fetchall():
            modulos = list(MODULOS) if row["rol"] in ("admin", "rrhh") else ["resenas"]
            for modulo in modulos:
                conn.execute(
                    "INSERT OR IGNORE INTO usuario_modulos (usuario_id, modulo) VALUES (?, ?)",
                    (row["id"], modulo),
                )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            token TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            creado TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Sin filas = sin restricción (ve todas las tiendas en Reseñas). Con
    # filas = solo ve esas tiendas concretas — así "seleccionar todos" es
    # simplemente no guardar ninguna fila, y no hay que mantener una lista
    # aparte sincronizada con las tiendas reales.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuario_tiendas (
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            tienda TEXT NOT NULL,
            PRIMARY KEY (usuario_id, tienda)
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


def get_tiendas_permitidas(usuario_id: int) -> list[str]:
    """Lista de tiendas a las que este usuario tiene acceso en Reseñas.
    Lista vacía = sin restricción (ve todas)."""
    conn = get_connection()
    rows = conn.execute("SELECT tienda FROM usuario_tiendas WHERE usuario_id = ? ORDER BY tienda", (usuario_id,)).fetchall()
    conn.close()
    return [r["tienda"] for r in rows]


def set_tiendas_permitidas(usuario_id: int, tiendas: list[str]):
    conn = get_connection()
    conn.execute("DELETE FROM usuario_tiendas WHERE usuario_id = ?", (usuario_id,))
    for tienda in tiendas:
        conn.execute("INSERT OR IGNORE INTO usuario_tiendas (usuario_id, tienda) VALUES (?, ?)", (usuario_id, tienda))
    conn.commit()
    conn.close()


def get_modulos_permitidos(usuario_id: int) -> list[str]:
    """Módulos a los que este usuario tiene acceso. Lista vacía = ninguno
    (a diferencia de las tiendas, aquí no hay "sin filas = todo")."""
    conn = get_connection()
    rows = conn.execute("SELECT modulo FROM usuario_modulos WHERE usuario_id = ? ORDER BY modulo", (usuario_id,)).fetchall()
    conn.close()
    return [r["modulo"] for r in rows]


def set_modulos_permitidos(usuario_id: int, modulos: list[str]):
    conn = get_connection()
    conn.execute("DELETE FROM usuario_modulos WHERE usuario_id = ?", (usuario_id,))
    for modulo in modulos:
        if modulo in MODULOS:
            conn.execute("INSERT OR IGNORE INTO usuario_modulos (usuario_id, modulo) VALUES (?, ?)", (usuario_id, modulo))
    conn.commit()
    conn.close()


def tiene_modulo(user: dict, modulo: str) -> bool:
    """admin siempre tiene todo, como red de seguridad para no quedarse
    fuera de Usuarios (u otro módulo) por un checkbox mal marcado."""
    if user["rol"] == "admin":
        return True
    return modulo in get_modulos_permitidos(user["id"])


def get_user_by_username(username: str):
    # COLLATE NOCASE: "Berta", "BERTA" y "BeRtA" deben entrar igual — el
    # usuario no tiene por qué acordarse de con qué mayúsculas se lo dieron.
    conn = get_connection()
    row = conn.execute("SELECT * FROM usuarios WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def username_disponible(username: str) -> bool:
    """Para evitar crear 'Berta' y 'berta' como dos cuentas distintas, ya que
    el login ahora no distingue mayúsculas de minúsculas."""
    return get_user_by_username(username) is None


def reset_pin(user_id: int):
    """Borra el PIN — el usuario vuelve a ver la pantalla de "todavía no
    tienes un PIN" la próxima vez que entre, y puede crear uno nuevo."""
    conn = get_connection()
    conn.execute("UPDATE usuarios SET pin = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


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
