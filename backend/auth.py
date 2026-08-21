import os
import re
import secrets
import sqlite3

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
    "colaborador": "Colaborador",
}

# Módulos que se pueden conceder explícitamente por checkbox al crear/editar
# un usuario. "usuarios" (gestión de cuentas) no está aquí a propósito: sigue
# siendo exclusivo del rol admin, porque de lo contrario cualquiera con ese
# módulo podría cambiarse su propio rol o el de otros.
MODULOS = {
    "resenas": "Reseñas",
    "informes": "Informes",
    "clima": "Clima Laboral",
    "boletines": "Boletines",
    "tests": "Test",
    "disc": "Perfil DISC",
    "agregadores": "Agregadores",
    "evaluaciones360": "Evaluaciones 360°",
    "saona_resenas": "SAONA · Reseñas",
    "saona_informes": "SAONA · Informes",
    "saona_clima": "SAONA · Clima Laboral",
    "saona_evaluaciones360": "SAONA · Evaluaciones 360°",
}

# Módulos que pertenecen al "hub" SAONA en Home — un usuario ve la tarjeta
# SAONA si tiene al menos uno de estos (o es admin), igual que cada tarjeta
# individual de Krispy Kreme depende de su propio módulo.
MODULOS_SAONA = ["saona_resenas", "saona_informes", "saona_clima", "saona_evaluaciones360"]

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
    # Para el indicador de "quién está en línea" (get_user_by_token la va
    # actualizando en cada request autenticado) — sin esto, una sesión de
    # hace días se seguiría contando como "en línea" para siempre.
    try:
        conn.execute("ALTER TABLE sesiones ADD COLUMN ultima_actividad TEXT")
    except sqlite3.OperationalError:
        pass  # La columna ya existía
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

    # Cuenta intentos fallidos de login por usuario para poder bloquear
    # temporalmente tras varios seguidos — el PIN es de solo 4 dígitos
    # (10.000 combinaciones), así que sin este freno alguien podría probarlas
    # todas en minutos con un script.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_intentos (
            username TEXT PRIMARY KEY,
            intentos INTEGER NOT NULL DEFAULT 0,
            bloqueado_hasta TEXT
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


def _backup_inmediato():
    """Fuerza una copia de seguridad justo después de guardar un PIN, en vez
    de esperar al ciclo periódico (cada 10 min, ver backups.py). Un PIN es
    justo el tipo de dato que se escribe una vez y no vuelve a tocarse — si
    Autoscale reinicia el contenedor (lo que pasa en cada redeploy) antes de
    que le toque turno al backup periódico, ese PIN recién creado se pierde
    y el usuario vuelve a aparecer "sin PIN" después de publicar. Import
    perezoso (no a nivel de módulo) para evitar un ciclo de imports con
    backups.py; nunca lanza excepción, igual que el resto de la capa de
    backups: si falla, el PIN ya se guardó igualmente, esto es solo una red
    de seguridad extra."""
    try:
        import backups as backups_module

        backups_module.hacer_backup()
    except Exception as e:
        print(f"[auth] No se pudo forzar backup tras guardar PIN: {e}", flush=True)


def reset_pin(user_id: int):
    """Borra el PIN — el usuario vuelve a ver la pantalla de "todavía no
    tienes un PIN" la próxima vez que entre, y puede crear uno nuevo."""
    conn = get_connection()
    conn.execute("UPDATE usuarios SET pin = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    _backup_inmediato()


def set_pin_si_no_tiene(username: str, pin: str) -> bool:
    """Activación de cuenta: solo deja crear el PIN si el usuario todavía no
    tenía uno (evita que cualquiera con solo el username lo sobreescriba).
    COLLATE NOCASE para que coincida con get_user_by_username — si no, un
    usuario creado como "Berta" que activa su cuenta escribiendo "berta" no
    encontraba la fila (esta consulta sí distinguía mayúsculas), y recibía
    el mensaje engañoso de "ya tiene un PIN" sin haberlo llegado a crear."""
    conn = get_connection()
    row = conn.execute("SELECT id, pin FROM usuarios WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    if row is None or row["pin"] is not None:
        conn.close()
        return False
    conn.execute("UPDATE usuarios SET pin = ? WHERE id = ?", (pin, row["id"]))
    conn.commit()
    conn.close()
    _backup_inmediato()
    return True


def admin_set_pin(user_id: int, pin: str):
    conn = get_connection()
    conn.execute("UPDATE usuarios SET pin = ? WHERE id = ?", (pin, user_id))
    conn.commit()
    conn.close()
    _backup_inmediato()


def authenticate_pin(username: str, pin: str):
    user = get_user_by_username(username)
    if user is None or user["pin"] is None:
        return None
    if not secrets.compare_digest(user["pin"], pin):
        return None
    return user


# El PIN es de solo 4 dígitos (10.000 combinaciones) — sin límite de
# intentos, un script podría probarlas todas en minutos. Bloqueo por
# username (no por IP, que aquí no se conoce a nivel de este módulo) tras
# varios fallos seguidos.
MAX_INTENTOS_LOGIN = 5
BLOQUEO_MINUTOS = 10


def _clave_intentos(username: str) -> str:
    """login_intentos no usa COLLATE NOCASE en la columna (INSERT ... ON
    CONFLICT necesita que la clave sea idéntica letra a letra para
    detectarlo), así que se normaliza aquí en vez de depender de eso."""
    return (username or "").strip().lower()


def login_bloqueado_minutos(username: str) -> int | None:
    """Minutos que faltan para poder reintentar, o None si no está
    bloqueado ahora mismo."""
    conn = get_connection()
    row = conn.execute("""
        SELECT CAST((julianday(bloqueado_hasta) - julianday('now')) * 1440 AS INTEGER) AS restante
        FROM login_intentos WHERE username = ? AND bloqueado_hasta IS NOT NULL
    """, (_clave_intentos(username),)).fetchone()
    conn.close()
    if row and row["restante"] is not None and row["restante"] > 0:
        return row["restante"]
    return None


def registrar_intento_fallido(username: str):
    clave = _clave_intentos(username)
    conn = get_connection()
    row = conn.execute("SELECT intentos FROM login_intentos WHERE username = ?", (clave,)).fetchone()
    intentos = (row["intentos"] if row else 0) + 1
    bloqueado_hasta = None
    if intentos >= MAX_INTENTOS_LOGIN:
        bloqueado_hasta = conn.execute(
            "SELECT datetime('now', ?)", (f"+{BLOQUEO_MINUTOS} minutes",)
        ).fetchone()[0]
        intentos = 0  # se reinicia el contador al entrar en el bloqueo
    conn.execute("""
        INSERT INTO login_intentos (username, intentos, bloqueado_hasta) VALUES (?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET intentos = excluded.intentos, bloqueado_hasta = excluded.bloqueado_hasta
    """, (clave, intentos, bloqueado_hasta))
    conn.commit()
    conn.close()


def limpiar_intentos_login(username: str):
    conn = get_connection()
    conn.execute("DELETE FROM login_intentos WHERE username = ?", (_clave_intentos(username),))
    conn.commit()
    conn.close()


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
    if row:
        # Se marca aquí (no en un endpoint aparte) porque este es el único
        # punto por el que pasa CUALQUIER request autenticado — así "en
        # línea" refleja actividad real navegando la app, no solo tener
        # sesión abierta desde hace días.
        conn.execute("UPDATE sesiones SET ultima_actividad = datetime('now') WHERE token = ?", (token,))
        conn.commit()
    conn.close()
    return dict(row) if row else None


# Ventana de "en línea": una sesión sin actividad en más de esto ya no cuenta,
# aunque el usuario nunca haya cerrado sesión explícitamente.
EN_LINEA_MINUTOS = 3


def get_usuarios_en_linea(excluir_usuario_id=None):
    """Usuarios con actividad reciente (ver EN_LINEA_MINUTOS), para el
    indicador del topbar — pensado solo para el usuario admin principal, no
    es una lista de presencia de uso general."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT usuarios.id, usuarios.nombre, usuarios.rol, MAX(sesiones.ultima_actividad) AS ultima_actividad
        FROM sesiones
        JOIN usuarios ON usuarios.id = sesiones.usuario_id
        WHERE sesiones.ultima_actividad >= datetime('now', ?)
        GROUP BY usuarios.id
        ORDER BY ultima_actividad DESC
    """, (f"-{EN_LINEA_MINUTOS} minutes",)).fetchall()
    conn.close()
    return [dict(r) for r in rows if r["id"] != excluir_usuario_id]


def sembrar_admin_inicial():
    """Crea un único admin de arranque cuando la tabla usuarios está
    completamente vacía (despliegue nuevo en Railway/Fly.io/etc. sin datos
    previos) — sin esto, un despliegue desde git nunca tiene ningún usuario
    con el que entrar, porque la base de datos real vive fuera de git a
    propósito (ver .gitignore) y nunca viaja con el código.

    Se activa solo con la variable de entorno ADMIN_PIN puesta a mano en el
    panel de la plataforma de turno (nunca en el código/git) — sin ella no
    hace nada, para no crear un admin con PIN adivinable en ningún entorno.
    Es un mecanismo de un solo uso: en cuanto exista al menos un usuario ya
    no vuelve a ejecutarse, así que no pisa nada en despliegues ya poblados
    (Replit) ni si luego restauras una copia de seguridad real."""
    admin_pin = os.environ.get("ADMIN_PIN")
    if not admin_pin or not pin_valido(admin_pin):
        return
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if total > 0:
        conn.close()
        return
    username = os.environ.get("ADMIN_USERNAME", "saul")
    conn.execute(
        "INSERT INTO usuarios (username, nombre, rol, pin) VALUES (?, ?, 'admin', ?)",
        (username, "Saul", admin_pin),
    )
    conn.commit()
    conn.close()
    print(f"[auth] Base de datos vacía: creado admin de arranque '{username}' desde ADMIN_PIN.", flush=True)


ensure_auth_tables()
sembrar_admin_inicial()
