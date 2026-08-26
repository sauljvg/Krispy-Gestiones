import datetime
import os
import sqlite3

# DATA_DIR: raíz del repo por defecto (comportamiento de siempre, tanto en
# local como en Replit). En un hosting con disco realmente persistente
# (p.ej. un volumen montado en Fly.io) se fija esta variable de entorno
# apuntando a esa ruta montada, para que krispy_kreme.db y las carpetas de
# subidas vivan ahí en vez de en el disco efímero del contenedor — sin esto,
# cada redeploy perdería los datos igual que pasaba en Replit Autoscale.
DATA_DIR = os.environ.get("DATA_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(DATA_DIR, "krispy_kreme.db")


def get_connection():
    # WAL en vez del modo por defecto (rollback journal): permite lecturas
    # mientras hay una escritura en curso, en vez de bloquearlas -- sin esto,
    # una ráfaga de escrituras concurrentes (ej. el scraper de Agregadores
    # generando muchos puntos a la vez) puede dejar "database is locked"
    # hasta en peticiones que no tienen nada que ver, como el login. El
    # busy_timeout (más generoso que el timeout= de connect) hace que SQLite
    # reintente en vez de fallar de inmediato si aun así hay contención.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def dict_rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


def _ensure_transactions_table():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS store_transactions (
            tienda TEXT NOT NULL,
            mes TEXT NOT NULL,
            transacciones INTEGER NOT NULL,
            actualizado TEXT,
            PRIMARY KEY (tienda, mes)
        )
    """)
    # Migración: la tabla original solo tenía (tienda PK, transacciones), sin
    # mes. Si existe con el esquema viejo, se recrea (no había datos reales
    # todavía, solo pruebas).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(store_transactions)")}
    if "mes" not in cols:
        conn.execute("DROP TABLE store_transactions")
        conn.execute("""
            CREATE TABLE store_transactions (
                tienda TEXT NOT NULL,
                mes TEXT NOT NULL,
                transacciones INTEGER NOT NULL,
                actualizado TEXT,
                PRIMARY KEY (tienda, mes)
            )
        """)
    conn.commit()
    conn.close()


def _ensure_store_meta_table():
    """Tabla en desuso desde que se dejó de scrapear Maps en vivo (ver
    ESTADO_PROYECTO.md) — se mantiene solo para no romper bases de datos
    viejas que ya la tengan. Antes guardaba el total de reseñas que Google
    anunciaba para cada tienda (lo escribía scraper/scraper_v2.py al final de
    cada pasada)."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS store_meta (
            tienda TEXT PRIMARY KEY,
            total_google INTEGER,
            actualizado TEXT
        )
    """)
    conn.commit()
    conn.close()


def _ensure_reviews_columns():
    """fecha_hora/respuesta_texto/respuesta_fecha se añadieron después de
    crear la tabla reviews (la crea el scraper) — si ya existe pero le
    faltan estas columnas, se añaden aquí para que las consultas del
    backend no fallen aunque no se haya vuelto a correr el scraper."""
    conn = get_connection()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    if cols:  # si está vacío, la tabla reviews aún no existe
        for col in ("fecha_hora", "respuesta_texto", "respuesta_fecha"):
            if col not in cols:
                conn.execute(f"ALTER TABLE reviews ADD COLUMN {col} TEXT")
        # Columna en desuso desde que se dejó de scrapear Maps en vivo (ver
        # ESTADO_PROYECTO.md) — se mantiene solo por compatibilidad con
        # bases de datos viejas. NULL/1 = visible; 0 = una reconciliación
        # manual antigua no la encontró en una pasada completa en vivo.
        if "visible_en_google" not in cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN visible_en_google INTEGER")
        conn.commit()
    conn.close()


def _ensure_reviews_indexes():
    """reviews se filtra constantemente por tienda/fecha_datetime/sentiment
    (ver routes.build_filters) pero no tenía ningún índice más allá del
    rowid -- cada consulta filtrada era un full table scan. IF NOT EXISTS +
    el mismo guard "if cols" que _ensure_reviews_columns, para no fallar si
    el scraper todavía no ha creado la tabla en un despliegue nuevo."""
    conn = get_connection()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    if cols:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_tienda_fecha ON reviews(tienda, fecha_datetime)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_fecha ON reviews(fecha_datetime)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_sentiment ON reviews(sentiment)")
        conn.commit()
    conn.close()


def _ensure_import_meta_table():
    """Fila única con la fecha/hora de la última importación de Takeout —
    visible para cualquiera con acceso a Reseñas, no solo quien la lanzó
    (antes esa información no se guardaba en ningún sitio)."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS import_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            ultima_importacion_takeout TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO import_meta (id, ultima_importacion_takeout) VALUES (1, NULL)")
    conn.commit()
    conn.close()


def get_ultima_importacion_takeout():
    conn = get_connection()
    row = conn.execute("SELECT ultima_importacion_takeout FROM import_meta WHERE id = 1").fetchone()
    conn.close()
    return row["ultima_importacion_takeout"] if row else None


def set_ultima_importacion_takeout():
    # UTC, igual que reviews.creado_en — el frontend lo convierte a hora
    # local del navegador al mostrarlo (ver reviews.js/dashboard.js).
    conn = get_connection()
    conn.execute(
        "UPDATE import_meta SET ultima_importacion_takeout = ? WHERE id = 1",
        (datetime.datetime.utcnow().isoformat(),),
    )
    conn.commit()
    conn.close()


_ensure_transactions_table()
_ensure_store_meta_table()
_ensure_reviews_columns()
_ensure_reviews_indexes()
_ensure_import_meta_table()
