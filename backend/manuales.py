"""Manuales/instrucciones paso a paso (Odoo y demás herramientas internas) --
pedido explícito del usuario: nada de documentos largos para leer, cada
manual es una secuencia de PASOS (una captura de pantalla + una frase corta
cada uno), como una guía visual en vez de un manual de texto. Un manual se
agrupa por `categoria` (texto libre, p.ej. "Odoo") para el catálogo."""
import os
import sqlite3

from PIL import Image, ImageDraw, ImageFilter

from db import DATA_DIR, get_connection

IMAGENES_DIR = os.path.join(DATA_DIR, "uploads", "manuales_imagenes")

# Pictogramas de acción: etiqueta rápida y opcional por paso (además de la
# captura, que sigue siendo la protagonista) -- "escanear" el manual sin
# tener que leer cada frase. Lista cerrada para que el desplegable del
# editor tenga sentido y no se acumulen variantes sueltas con el tiempo.
PICTOGRAMAS = {
    "clic": "🖱️ Clic",
    "escribir": "⌨️ Escribe",
    "subir": "📤 Sube un archivo",
    "revisar": "👀 Revisa",
    "confirmar": "✅ Confirma",
    "aviso": "⚠️ Atención",
}


def ensure_manuales_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manuales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT 'General',
            creado_por TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now')),
            actualizado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manual_pasos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manual_id INTEGER NOT NULL REFERENCES manuales(id) ON DELETE CASCADE,
            orden INTEGER NOT NULL,
            texto TEXT NOT NULL DEFAULT '',
            pictograma TEXT,
            imagen_ruta TEXT,
            imagen_nombre_original TEXT
        )
    """)
    # "Spotlight": la captura entera en blanco y negro salvo un círculo a
    # color en el punto exacto donde hay que mirar/hacer clic -- pedido
    # explícito del usuario ("tipo tutoriales de ikea... todo en blanco y
    # negro excepto lo único que estamos señalando"). marca_x/marca_y/
    # marca_radio son fracciones (0-1) del ancho/alto de la imagen, no
    # píxeles -- así la marca se sigue viendo en el sitio correcto aunque la
    # imagen se reescale. Ver generar_spotlight más abajo.
    cols_pasos = {row[1] for row in conn.execute("PRAGMA table_info(manual_pasos)")}
    for columna in ("marca_x", "marca_y", "marca_radio"):
        if columna not in cols_pasos:
            try:
                conn.execute(f"ALTER TABLE manual_pasos ADD COLUMN {columna} REAL")
            except sqlite3.OperationalError:
                pass
    conn.commit()
    conn.close()
    os.makedirs(IMAGENES_DIR, exist_ok=True)


def _ruta_spotlight(paso_id):
    return os.path.join(IMAGENES_DIR, f"{paso_id}_spot.png")


def generar_spotlight(manual_id, paso_id, x, y, radio):
    """Genera (o borra, si x es None) la versión "spotlight" de la imagen de
    este paso: el resto en blanco y negro, un círculo a color centrado en
    (x, y) -- fracciones 0-1 del ancho/alto -- con `radio` (fracción del
    ancho) y un borde difuminado para que no quede un corte duro."""
    paso = get_paso(manual_id, paso_id)
    if paso is None:
        raise ValueError("El paso no existe")
    conn = get_connection()
    if x is None or paso["imagen_ruta"] is None:
        conn.execute(
            "UPDATE manual_pasos SET marca_x = NULL, marca_y = NULL, marca_radio = NULL WHERE id = ?", (paso_id,)
        )
        conn.commit()
        conn.close()
        _borrar_imagen_fisica(_ruta_spotlight(paso_id))
        return
    with Image.open(paso["imagen_ruta"]) as im:
        color = im.convert("RGB")
    ancho, alto = color.size
    gris = color.convert("L").convert("RGB")
    radio_px = max(radio, 0.02) * ancho
    cx, cy = x * ancho, y * alto
    mascara = Image.new("L", (ancho, alto), 0)
    ImageDraw.Draw(mascara).ellipse([cx - radio_px, cy - radio_px, cx + radio_px, cy + radio_px], fill=255)
    mascara = mascara.filter(ImageFilter.GaussianBlur(radio_px * 0.18))
    resultado = Image.composite(color, gris, mascara)
    resultado.save(_ruta_spotlight(paso_id), "PNG")
    conn.execute(
        "UPDATE manual_pasos SET marca_x = ?, marca_y = ?, marca_radio = ? WHERE id = ?",
        (x, y, radio, paso_id),
    )
    conn.commit()
    conn.close()


def get_imagen_servida(manual_id, paso_id):
    """Ruta física que hay que servir para este paso: la versión spotlight
    si tiene marca puesta, si no la original tal cual."""
    paso = get_paso(manual_id, paso_id)
    if paso is None or paso["imagen_ruta"] is None:
        return None
    if paso["marca_x"] is not None and os.path.exists(_ruta_spotlight(paso_id)):
        return _ruta_spotlight(paso_id)
    return paso["imagen_ruta"]


def _row_manual(r):
    d = dict(r)
    return d


def list_manuales():
    """Catálogo: cada manual con su nº de pasos y la portada (imagen del
    primer paso, si tiene) -- para pintar tarjetas sin tener que pedir cada
    manual completo de golpe."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.*, COUNT(p.id) AS pasos_count,
               MIN(p.id) AS portada_paso_id
        FROM manuales m LEFT JOIN manual_pasos p ON p.manual_id = m.id
        GROUP BY m.id
        ORDER BY m.categoria, m.titulo
    """).fetchall()
    conn.close()
    resultado = []
    for r in rows:
        d = _row_manual(r)
        portada_id = d.pop("portada_paso_id")
        d["portada_paso_id"] = portada_id
        resultado.append(d)
    return resultado


def get_manual(manual_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM manuales WHERE id = ?", (manual_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    manual = _row_manual(row)
    pasos = conn.execute("""
        SELECT id, orden, texto, pictograma, imagen_ruta IS NOT NULL AS tiene_imagen,
               marca_x IS NOT NULL AS tiene_marca
        FROM manual_pasos WHERE manual_id = ? ORDER BY orden
    """, (manual_id,)).fetchall()
    conn.close()
    manual["pasos"] = [dict(p) | {"tiene_imagen": bool(p["tiene_imagen"]), "tiene_marca": bool(p["tiene_marca"])} for p in pasos]
    return manual


def crear_manual(titulo, categoria, creado_por):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO manuales (titulo, categoria, creado_por) VALUES (?, ?, ?)",
        (titulo, categoria or "General", creado_por),
    )
    conn.commit()
    manual_id = cur.lastrowid
    conn.close()
    return manual_id


def actualizar_manual(manual_id, titulo, categoria):
    conn = get_connection()
    conn.execute(
        "UPDATE manuales SET titulo = ?, categoria = ?, actualizado_en = datetime('now') WHERE id = ?",
        (titulo, categoria or "General", manual_id),
    )
    conn.commit()
    conn.close()


def _borrar_imagen_fisica(ruta):
    if ruta and os.path.exists(ruta):
        os.remove(ruta)


def eliminar_manual(manual_id):
    conn = get_connection()
    pasos = conn.execute(
        "SELECT id, imagen_ruta FROM manual_pasos WHERE manual_id = ?", (manual_id,)
    ).fetchall()
    conn.execute("DELETE FROM manual_pasos WHERE manual_id = ?", (manual_id,))
    conn.execute("DELETE FROM manuales WHERE id = ?", (manual_id,))
    conn.commit()
    conn.close()
    for p in pasos:
        _borrar_imagen_fisica(p["imagen_ruta"])
        _borrar_imagen_fisica(_ruta_spotlight(p["id"]))


def agregar_paso(manual_id, texto, pictograma, nombre_original, extension, contenido, marca=None):
    """`marca`, si se da, es (x, y, radio) -- fracciones 0-1 -- para dejar el
    paso ya con el efecto spotlight puesto desde el momento en que se crea,
    sin tener que subir la imagen y marcarla después en dos pasos."""
    if get_manual(manual_id) is None:
        raise ValueError("El manual no existe")
    conn = get_connection()
    siguiente = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 AS n FROM manual_pasos WHERE manual_id = ?", (manual_id,)
    ).fetchone()["n"]
    cur = conn.execute(
        "INSERT INTO manual_pasos (manual_id, orden, texto, pictograma) VALUES (?, ?, ?, ?)",
        (manual_id, siguiente, texto, pictograma),
    )
    paso_id = cur.lastrowid
    if contenido is not None:
        ruta = os.path.join(IMAGENES_DIR, f"{paso_id}{extension}")
        with open(ruta, "wb") as f:
            f.write(contenido)
        conn.execute(
            "UPDATE manual_pasos SET imagen_ruta = ?, imagen_nombre_original = ? WHERE id = ?",
            (ruta, nombre_original, paso_id),
        )
    conn.execute("UPDATE manuales SET actualizado_en = datetime('now') WHERE id = ?", (manual_id,))
    conn.commit()
    conn.close()
    if contenido is not None and marca is not None:
        generar_spotlight(manual_id, paso_id, *marca)
    return paso_id


def get_paso(manual_id, paso_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM manual_pasos WHERE id = ? AND manual_id = ?", (paso_id, manual_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def actualizar_paso(manual_id, paso_id, texto, pictograma):
    conn = get_connection()
    conn.execute(
        "UPDATE manual_pasos SET texto = ?, pictograma = ? WHERE id = ? AND manual_id = ?",
        (texto, pictograma, paso_id, manual_id),
    )
    conn.execute("UPDATE manuales SET actualizado_en = datetime('now') WHERE id = ?", (manual_id,))
    conn.commit()
    conn.close()


def reemplazar_imagen_paso(manual_id, paso_id, nombre_original, extension, contenido):
    paso = get_paso(manual_id, paso_id)
    if paso is None:
        raise ValueError("El paso no existe")
    _borrar_imagen_fisica(paso["imagen_ruta"])
    _borrar_imagen_fisica(_ruta_spotlight(paso_id))  # marca vieja ya no aplica a la imagen nueva
    ruta = os.path.join(IMAGENES_DIR, f"{paso_id}{extension}")
    with open(ruta, "wb") as f:
        f.write(contenido)
    conn = get_connection()
    conn.execute(
        "UPDATE manual_pasos SET imagen_ruta = ?, imagen_nombre_original = ?, marca_x = NULL, marca_y = NULL, marca_radio = NULL WHERE id = ?",
        (ruta, nombre_original, paso_id),
    )
    conn.execute("UPDATE manuales SET actualizado_en = datetime('now') WHERE id = ?", (manual_id,))
    conn.commit()
    conn.close()


def eliminar_paso(manual_id, paso_id):
    paso = get_paso(manual_id, paso_id)
    if paso is None:
        return
    conn = get_connection()
    conn.execute("DELETE FROM manual_pasos WHERE id = ? AND manual_id = ?", (paso_id, manual_id))
    # Renumera para que "orden" quede siempre 1..N sin huecos -- si no, un
    # hueco en la secuencia no rompe nada funcionalmente (se ordena igual),
    # pero mover_paso (intercambia con el vecino inmediato en orden) se
    # complica de más si hay que buscar "el siguiente que exista" en vez de
    # simplemente orden+1/orden-1.
    restantes = conn.execute(
        "SELECT id FROM manual_pasos WHERE manual_id = ? ORDER BY orden", (manual_id,)
    ).fetchall()
    for i, r in enumerate(restantes, start=1):
        conn.execute("UPDATE manual_pasos SET orden = ? WHERE id = ?", (i, r["id"]))
    conn.execute("UPDATE manuales SET actualizado_en = datetime('now') WHERE id = ?", (manual_id,))
    conn.commit()
    conn.close()
    _borrar_imagen_fisica(paso["imagen_ruta"])
    _borrar_imagen_fisica(_ruta_spotlight(paso_id))


def mover_paso(manual_id, paso_id, direccion):
    """direccion: "arriba" (resta 1 a orden) o "abajo" (suma 1) -- intercambia
    con el paso vecino inmediato, sin dejar huecos (ver eliminar_paso)."""
    paso = get_paso(manual_id, paso_id)
    if paso is None:
        raise ValueError("El paso no existe")
    delta = -1 if direccion == "arriba" else 1
    vecino_orden = paso["orden"] + delta
    conn = get_connection()
    vecino = conn.execute(
        "SELECT id FROM manual_pasos WHERE manual_id = ? AND orden = ?", (manual_id, vecino_orden)
    ).fetchone()
    if vecino:
        conn.execute("UPDATE manual_pasos SET orden = ? WHERE id = ?", (paso["orden"], vecino["id"]))
        conn.execute("UPDATE manual_pasos SET orden = ? WHERE id = ?", (vecino_orden, paso_id))
        conn.commit()
    conn.close()


ensure_manuales_tables()
