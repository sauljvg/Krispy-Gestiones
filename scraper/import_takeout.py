#!/usr/bin/env python3
"""Importa reseñas desde un export de Google Takeout ("Perfil de Empresa en
Google"), que trae el histórico completo y oficial de cada ubicación sin
pasar por Selenium/scroll — Takeout no sufre el bloqueo de automatización
que sí afecta al scraping de Maps.

Uso:
    python import_takeout.py "C:\\ruta\\a\\la\\carpeta\\Takeout_extraida"

La carpeta debe contener "Takeout/Perfil de Empresa en Google/account-*/".
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# Cuando se ejecuta como script, Python ya añade la carpeta scraper/ a
# sys.path automáticamente; al importar este módulo desde otro sitio (p.ej.
# el backend) hace falta añadirla a mano para que "import config" resuelva.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import calcular_sentimiento, fecha_categoria  # noqa: E402
import config  # noqa: E402

# IDs internos de ubicación de Google Business Profile -> nombre de tienda tal
# como aparece en stores.py. Se identificaron cruzando el "storeCode" de cada
# location/data.json con el código de tienda visible en el panel de gestión
# de reseñas (business.google.com).
LOCATION_TO_STORE = {
    "location-10398817451723850297": "ParqueSur",
    "location-12690726064070696692": "Princesa",
    "location-10317049400463155537": "Plenilunio",
    "location-12783565955788444310": "Caleido",
    "location-5186930758782444873": "Gran Plaza 2",
    "location-7326412347627659015": "La Gavia",
}

STAR_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

MADRID_TZ = ZoneInfo("Europe/Madrid")


def parse_google_timestamp(ts):
    """Convierte un timestamp de Google ('...Z', UTC, con o sin fracción de
    segundo) a un datetime naive en hora de Madrid — así el desglose por
    hora del día refleja la hora real en la que la gente escribe, no UTC."""
    if not ts:
        return None
    ts = ts.rstrip("Z")
    if "." in ts:
        base, frac = ts.split(".", 1)
        ts = f"{base}.{(frac + '000000')[:6]}"
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        fmt = "%Y-%m-%dT%H:%M:%S"
    try:
        dt_utc = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt_utc.astimezone(MADRID_TZ).replace(tzinfo=None)


def longpath(p):
    """Windows corta en 260 caracteres; los nombres de archivo de Takeout
    (el ID completo de la reseña) los superan fácilmente combinados con
    rutas ya profundas. El prefijo \\\\?\\ hace que Windows use la API de
    rutas largas sin límite práctico."""
    p = os.path.abspath(p)
    if not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


def strip_translation(texto):
    """Takeout adjunta la traducción automática al inglés tras el texto
    original separada por '(Translated by Google)'; nos quedamos solo con
    el texto original para no duplicar contenido ni desviar el análisis de
    sentimiento (afinado en español)."""
    if not texto:
        return ""
    marker = "(Translated by Google)"
    if marker in texto:
        texto = texto.split(marker)[0]
    return texto.strip()


def fecha_relativa_desde(fecha_dt, current_date):
    dias = (current_date - fecha_dt).days
    if dias <= 0:
        return "Hoy"
    if dias == 1:
        return "Hace 1 día"
    if dias < 30:
        return f"Hace {dias} días"
    meses = dias // 30
    if meses < 12:
        return f"Hace {meses} mes" if meses == 1 else f"Hace {meses} meses"
    anos = dias // 365
    return f"Hace {anos} año" if anos == 1 else f"Hace {anos} años"


def load_location_reviews(location_dir):
    """Consolida reviews.json + todos los reviews-<id>.json de una ubicación
    (deduplicados por el campo 'name', que es el ID canónico de Google)."""
    full_dir = longpath(location_dir)
    entries = os.listdir(full_dir)
    review_files = [e for e in entries if e.startswith("reviews") and e.endswith(".json")]
    all_reviews = {}
    for fname in review_files:
        fpath = os.path.join(full_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ! aviso: no se pudo leer {fname}: {e}", flush=True)
            continue
        revs = data.get("reviews", [data]) if isinstance(data, dict) else []
        for r in revs:
            rid = r.get("name")
            if rid:
                all_reviews[rid] = r
    return list(all_reviews.values())


def process_takeout_review(raw, tienda, current_date):
    review_id = raw["name"].rsplit("/", 1)[-1]
    rating = STAR_MAP.get(raw.get("starRating"))
    texto = strip_translation(raw.get("comment", ""))

    fecha_dt = parse_google_timestamp(raw.get("createTime"))

    reply = raw.get("reviewReply") or {}
    respuesta_texto = strip_translation(reply.get("comment", "")) or None
    respuesta_fecha_dt = parse_google_timestamp(reply.get("updateTime"))
    respuesta_fecha = respuesta_fecha_dt.strftime("%Y-%m-%d %H:%M:%S") if respuesta_fecha_dt else None

    sentiment, sentiment_score = calcular_sentimiento(texto, rating)
    es_reciente = bool(fecha_dt and (current_date - fecha_dt).days <= 120)

    return {
        "review_id": review_id,
        "tienda": tienda,
        "autor": (raw.get("reviewer") or {}).get("displayName", "Usuario de Google").strip(),
        "fecha": fecha_relativa_desde(fecha_dt, current_date) if fecha_dt else "",
        "fecha_datetime": fecha_dt.strftime("%Y-%m-%d") if fecha_dt else None,
        "fecha_hora": fecha_dt.strftime("%Y-%m-%d %H:%M:%S") if fecha_dt else None,
        "fecha_categoria": fecha_categoria(fecha_dt),
        "calificación": f"{rating}★" if rating else "No especificada",
        "calificacion_num": rating,
        "texto": texto,
        "es_abril_o_reciente": es_reciente,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "respuesta_texto": respuesta_texto,
        "respuesta_fecha": respuesta_fecha,
    }


def get_existing_ids(tienda):
    if not os.path.exists(config.DB_PATH):
        return set()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cur = conn.execute("SELECT review_id FROM reviews WHERE tienda = ?", (tienda,))
        return {row[0] for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def save_to_sqlite(reviews):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            review_id TEXT PRIMARY KEY,
            tienda TEXT,
            autor TEXT,
            fecha TEXT,
            fecha_datetime TEXT,
            fecha_hora TEXT,
            fecha_categoria TEXT,
            calificacion TEXT,
            calificacion_num INTEGER,
            texto TEXT,
            es_reciente INTEGER,
            sentiment TEXT,
            sentiment_score REAL,
            respuesta_texto TEXT,
            respuesta_fecha TEXT
        )
    """)
    # Migración idempotente para bases de datos creadas antes de añadir hora
    # exacta y respuesta del negocio (solo disponibles vía Takeout, no scraping).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    for col in ("fecha_hora", "respuesta_texto", "respuesta_fecha"):
        if col not in cols:
            conn.execute(f"ALTER TABLE reviews ADD COLUMN {col} TEXT")

    for r in reviews:
        conn.execute("""
            INSERT INTO reviews (
                review_id, tienda, autor, fecha, fecha_datetime, fecha_hora, fecha_categoria,
                calificacion, calificacion_num, texto, es_reciente, sentiment, sentiment_score,
                respuesta_texto, respuesta_fecha
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                tienda=excluded.tienda, autor=excluded.autor, fecha=excluded.fecha,
                fecha_datetime=excluded.fecha_datetime, fecha_hora=excluded.fecha_hora,
                fecha_categoria=excluded.fecha_categoria,
                calificacion=excluded.calificacion, calificacion_num=excluded.calificacion_num,
                texto=excluded.texto, es_reciente=excluded.es_reciente, sentiment=excluded.sentiment,
                sentiment_score=excluded.sentiment_score, respuesta_texto=excluded.respuesta_texto,
                respuesta_fecha=excluded.respuesta_fecha
        """, (
            r["review_id"], r["tienda"], r["autor"], r["fecha"], r["fecha_datetime"], r["fecha_hora"],
            r["fecha_categoria"], r["calificación"], r["calificacion_num"], r["texto"],
            int(r["es_abril_o_reciente"]), r["sentiment"], r["sentiment_score"],
            r["respuesta_texto"], r["respuesta_fecha"],
        ))
    conn.commit()
    conn.close()


def get_total_google(tienda):
    if not os.path.exists(config.DB_PATH):
        return None
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute(
            "SELECT total_google FROM store_meta WHERE tienda = ?", (tienda,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _describir_estructura(root, max_depth=4, max_entradas=80):
    """Árbol compacto de lo que realmente hay dentro del .zip subido, para
    diagnosticar cuando no coincide con lo que se espera (los nombres de
    carpeta de Takeout varían según idioma/versión y no hay forma de
    adivinarlos todos de antemano)."""
    root = os.path.abspath(root)
    lineas = []
    for dirpath, dirnames, filenames in os.walk(root):
        if len(lineas) >= max_entradas:
            lineas.append("… (recortado)")
            break
        profundidad = dirpath[len(root):].count(os.sep)
        if profundidad > max_depth:
            dirnames[:] = []
            continue
        rel = os.path.relpath(dirpath, root)
        prefijo = "  " * profundidad
        lineas.append(f"{prefijo}{rel}/")
        for nombre in sorted(dirnames)[:10]:
            lineas.append(f"{prefijo}  {nombre}/")
        for nombre in sorted(filenames)[:5]:
            lineas.append(f"{prefijo}  {nombre}")
    return "\n".join(lineas)


def find_account_dir(takeout_root):
    # Búsqueda recursiva e insensible a mayúsculas/minúsculas: en Windows
    # (donde esto se probó primero) glob.glob ya ignora mayúsculas por el
    # propio filesystem, pero en producción (Linux, filesystem sensible a
    # mayúsculas) el nombre real de la carpeta dentro del .zip de Takeout
    # puede venir con otra combinación de mayúsculas, y el glob exacto no
    # encontraba nada.
    for dirpath, dirnames, _filenames in os.walk(takeout_root):
        if os.path.basename(dirpath).lower() != "perfil de empresa en google":
            continue
        for name in dirnames:
            if name.lower().startswith("account-"):
                return os.path.join(dirpath, name)
    raise SystemExit(
        "No se encontró la carpeta 'Perfil de Empresa en Google/account-*' dentro del .zip subido.\n\n"
        "Esto es lo que sí contiene el .zip que subiste:\n"
        f"{_describir_estructura(takeout_root)}"
    )


def run_import(takeout_root, log=lambda msg: None):
    """Corre la importación completa y devuelve el reporte (lista de dicts,
    uno por tienda). `log` recibe líneas de progreso opcionales — el CLI las
    imprime, el endpoint del backend las puede ignorar o guardar."""
    account_dir = find_account_dir(takeout_root)
    log(f"Cuenta de Takeout: {account_dir}")
    current_date = datetime.now()

    report = []
    for loc_dir_name, tienda in LOCATION_TO_STORE.items():
        loc_path = os.path.join(account_dir, loc_dir_name)
        if not os.path.isdir(loc_path):
            log(f"! {tienda}: no se encontró la carpeta {loc_dir_name}, se omite")
            continue

        raw_reviews = load_location_reviews(loc_path)
        existing_ids = get_existing_ids(tienda)
        processed = [process_takeout_review(r, tienda, current_date) for r in raw_reviews]

        nuevas = [p for p in processed if p["review_id"] not in existing_ids]
        actualizadas = [p for p in processed if p["review_id"] in existing_ids]

        save_to_sqlite(processed)

        total_ahora = len(existing_ids | {p["review_id"] for p in processed})
        total_google = get_total_google(tienda)
        pct = f"{total_ahora * 100 // total_google}%" if total_google else "?"

        report.append({
            "tienda": tienda,
            "en_takeout": len(processed),
            "ya_teniamos": len(actualizadas),
            "nuevas": len(nuevas),
            "total_ahora": total_ahora,
            "total_google": total_google,
            "pct": pct,
        })

        log(f"{tienda}: {len(processed)} en Takeout | {len(nuevas)} nuevas | "
            f"{len(actualizadas)} ya existían (actualizadas) | "
            f"total ahora: {total_ahora}" + (f"/{total_google} ({pct})" if total_google else ""))

    return report


def main():
    if len(sys.argv) < 2:
        print("Uso: python import_takeout.py <carpeta_takeout_extraida>")
        sys.exit(1)

    report = run_import(sys.argv[1], log=print)

    print("\n" + "=" * 70)
    print("REPORTE FINAL — Import de Google Takeout")
    print("=" * 70)
    total_nuevas = sum(r["nuevas"] for r in report)
    for r in report:
        print(f"  {r['tienda']:<14} +{r['nuevas']:<5} nuevas  "
              f"(total: {r['total_ahora']}" + (f"/{r['total_google']} = {r['pct']}" if r['total_google'] else "") + ")")
    print(f"\nTotal de reseñas NUEVAS encontradas gracias a Takeout: {total_nuevas}")


if __name__ == "__main__":
    main()
