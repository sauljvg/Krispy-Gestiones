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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
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
    """Guarda el total de reseñas que Google anuncia para cada tienda (lo
    escribe el scraper al final de cada pasada), para poder marcar con un
    check cuando ya tenemos el 100% capturado."""
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
        # NULL/1 = sigue visible en Google (valor por defecto); 0 = la
        # reconciliación manual (scraper --reconciliar) no la encontró en una
        # pasada completa en vivo — la persona la borró o Google la retiró.
        # La rellena backend/routes.py (POST /reviews/reconciliacion), nunca
        # el scraper directamente (no escribe en la BD de producción).
        if "visible_en_google" not in cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN visible_en_google INTEGER")
        conn.commit()
    conn.close()


_ensure_transactions_table()
_ensure_store_meta_table()
_ensure_reviews_columns()
