"""Gestión del personal por tienda que alimenta el matching de nombres en
reseñas (ver analytics.py). Sustituye al antiguo STORE_STAFF fijo en
staff_names.py (que se sigue usando solo como semilla de la migración) por
tablas editables desde el propio dashboard de Reseñas: alta manual de una
persona nueva, sugerencia de variantes/diminutivos con Gemini, y salida
(baja definitiva o traslado a otra tienda, que cierra la asignación actual
y abre una nueva conservando el mismo nombre/variantes).

Cada persona (tabla "personal") puede tener varias asignaciones en el
tiempo (tabla "personal_asignaciones", una por tienda en la que ha
trabajado). "activo" en la asignación es lo único que decide si cuenta
como personal actual o anterior de esa tienda — las fechas son solo
informativas, no se usan para filtrar menciones por fecha de reseña.
"""

import datetime
import json
import os
import re

import requests

from db import get_connection

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class PersonalError(Exception):
    pass


class PersonalDuplicadoError(PersonalError):
    """Ya hay alguien activo en esa tienda con el mismo nombre/variante —
    p.ej. se intenta dar de alta "Maria Pilar" en Plenilunio cuando ya había
    un "Pilar" ahí: si son la misma persona y se crean como dos fichas
    separadas, las menciones de reseñas se reparten entre las dos en vez de
    sumar en una sola. Quien llama decide si fusionar o crear aparte."""

    def __init__(self, duplicados):
        self.duplicados = duplicados
        nombres = ", ".join(d["nombre_canonico"] for d in duplicados)
        super().__init__(f"Ya hay personal con ese nombre en esa tienda: {nombres}")


def ensure_personal_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_canonico TEXT NOT NULL,
            variantes TEXT NOT NULL DEFAULT '[]',
            creado_en TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personal_asignaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            personal_id INTEGER NOT NULL REFERENCES personal(id),
            tienda TEXT NOT NULL,
            fecha_inicio TEXT,
            fecha_fin TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            motivo_fin TEXT,
            creado_en TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    # Semilla única: si "personal" está vacía (primera vez que corre esta
    # migración, típicamente el primer deploy con este código) se vuelca ahí
    # el STORE_STAFF fijo de siempre, para no perder las plantillas ya
    # validadas contra reseñas reales (p.ej. los diminutivos de ParqueSur).
    # A partir de aquí STORE_STAFF deja de leerse en caliente — analytics.py
    # ya solo lee de estas tablas.
    ya_migrado = conn.execute("SELECT COUNT(*) c FROM personal").fetchone()["c"] > 0
    if not ya_migrado:
        from staff_names import STORE_STAFF
        for tienda, data in STORE_STAFF.items():
            for nombre, variantes in data.get("current", {}).items():
                _insertar_semilla(conn, tienda, nombre, variantes, activo=1)
            for nombre, variantes in data.get("former", {}).items():
                _insertar_semilla(conn, tienda, nombre, variantes, activo=0)
        conn.commit()
    conn.close()


def _insertar_semilla(conn, tienda, nombre, variantes, activo):
    cur = conn.execute(
        "INSERT INTO personal (nombre_canonico, variantes) VALUES (?, ?)",
        (nombre, json.dumps(variantes, ensure_ascii=False)),
    )
    conn.execute(
        "INSERT INTO personal_asignaciones (personal_id, tienda, activo, motivo_fin) VALUES (?, ?, ?, ?)",
        (cur.lastrowid, tienda, activo, None if activo else "baja"),
    )


def _normalizar_variantes(variantes):
    limpio = []
    for v in variantes or []:
        v = (v or "").strip().lower()
        if v and v not in limpio:
            limpio.append(v)
    return limpio


def _buscar_posibles_duplicados(conn, tienda, nombre_canonico, variantes):
    """Personal ACTIVO en `tienda` cuyo nombre o alguna variante coincida
    (sin distinguir mayúsculas) con las de la persona que se va a dar de
    alta ahí. No mira otras tiendas -- el mismo nombre de pila en tiendas
    distintas puede ser gente distinta a propósito (ver docstring del
    módulo), el conflicto real es dentro de LA MISMA tienda."""
    propias = set(_normalizar_variantes(variantes)) | {nombre_canonico.strip().lower()}
    filas = conn.execute("""
        SELECT p.id AS personal_id, p.nombre_canonico, p.variantes
        FROM personal_asignaciones pa
        JOIN personal p ON p.id = pa.personal_id
        WHERE pa.tienda = ? AND pa.activo = 1
    """, (tienda,)).fetchall()
    duplicados = []
    for fila in filas:
        existentes = set(json.loads(fila["variantes"])) | {fila["nombre_canonico"].strip().lower()}
        if propias & existentes:
            duplicados.append({
                "personal_id": fila["personal_id"],
                "nombre_canonico": fila["nombre_canonico"],
                "variantes": sorted(existentes),
            })
    return duplicados


def build_store_staff():
    """{tienda: {"current": {nombre: [variantes]}, "former": {...}}} —
    misma forma que el antiguo STORE_STAFF fijo, reconstruida desde la BD en
    cada llamada (la tabla es pequeña, no hace falta cachear)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT pa.tienda, pa.activo, p.nombre_canonico, p.variantes
        FROM personal_asignaciones pa
        JOIN personal p ON p.id = pa.personal_id
    """).fetchall()
    conn.close()

    result = {}
    for row in rows:
        estado = "current" if row["activo"] else "former"
        tienda_dict = result.setdefault(row["tienda"], {"current": {}, "former": {}})
        tienda_dict[estado][row["nombre_canonico"]] = json.loads(row["variantes"])
    return result


def list_personal(tienda=None):
    conn = get_connection()
    sql = """
        SELECT pa.id AS asignacion_id, pa.tienda, pa.fecha_inicio, pa.fecha_fin, pa.activo, pa.motivo_fin,
               p.id AS personal_id, p.nombre_canonico, p.variantes
        FROM personal_asignaciones pa
        JOIN personal p ON p.id = pa.personal_id
    """
    params = []
    if tienda:
        sql += " WHERE pa.tienda = ?"
        params.append(tienda)
    sql += " ORDER BY pa.tienda, pa.activo DESC, p.nombre_canonico"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        {
            "asignacion_id": r["asignacion_id"],
            "personal_id": r["personal_id"],
            "tienda": r["tienda"],
            "nombre_canonico": r["nombre_canonico"],
            "variantes": json.loads(r["variantes"]),
            "fecha_inicio": r["fecha_inicio"],
            "fecha_fin": r["fecha_fin"],
            "activo": bool(r["activo"]),
            "motivo_fin": r["motivo_fin"],
        }
        for r in rows
    ]


def crear_personal(tienda, nombre_canonico, variantes, fecha_inicio=None,
                    confirmar_duplicado=False, fusionar_con_personal_id=None):
    tienda = (tienda or "").strip()
    nombre_canonico = (nombre_canonico or "").strip()
    if not tienda:
        raise PersonalError("Falta la tienda")
    if not nombre_canonico:
        raise PersonalError("Falta el nombre")

    variantes = _normalizar_variantes(variantes)
    if nombre_canonico.lower() not in variantes:
        variantes.insert(0, nombre_canonico.lower())

    conn = get_connection()

    if fusionar_con_personal_id:
        destino = conn.execute("SELECT id, variantes FROM personal WHERE id = ?", (fusionar_con_personal_id,)).fetchone()
        if not destino:
            conn.close()
            raise PersonalError("La persona con la que fusionar ya no existe")
        variantes_unidas = _normalizar_variantes(json.loads(destino["variantes"]) + variantes)
        conn.execute(
            "UPDATE personal SET variantes = ? WHERE id = ?",
            (json.dumps(variantes_unidas, ensure_ascii=False), fusionar_con_personal_id),
        )
        # Si ya tiene una asignación activa en esa tienda (el caso normal:
        # se fusiona precisamente porque ya estaba ahí) no se crea otra --
        # dejaría dos filas activas de la misma persona en la misma tienda.
        ya_activa_aqui = conn.execute(
            "SELECT 1 FROM personal_asignaciones WHERE personal_id = ? AND tienda = ? AND activo = 1",
            (fusionar_con_personal_id, tienda),
        ).fetchone()
        if not ya_activa_aqui:
            conn.execute(
                "INSERT INTO personal_asignaciones (personal_id, tienda, fecha_inicio, activo) VALUES (?, ?, ?, 1)",
                (fusionar_con_personal_id, tienda, fecha_inicio or None),
            )
        conn.commit()
        conn.close()
        return {"personal_id": fusionar_con_personal_id, "fusionado": True}

    if not confirmar_duplicado:
        duplicados = _buscar_posibles_duplicados(conn, tienda, nombre_canonico, variantes)
        if duplicados:
            conn.close()
            raise PersonalDuplicadoError(duplicados)

    cur = conn.execute(
        "INSERT INTO personal (nombre_canonico, variantes) VALUES (?, ?)",
        (nombre_canonico, json.dumps(variantes, ensure_ascii=False)),
    )
    personal_id = cur.lastrowid
    conn.execute(
        "INSERT INTO personal_asignaciones (personal_id, tienda, fecha_inicio, activo) VALUES (?, ?, ?, 1)",
        (personal_id, tienda, fecha_inicio or None),
    )
    conn.commit()
    conn.close()
    return {"personal_id": personal_id}


def actualizar_personal(personal_id, nombre_canonico, variantes):
    nombre_canonico = (nombre_canonico or "").strip()
    if not nombre_canonico:
        raise PersonalError("Falta el nombre")
    variantes = _normalizar_variantes(variantes)
    if nombre_canonico.lower() not in variantes:
        variantes.insert(0, nombre_canonico.lower())

    conn = get_connection()
    existe = conn.execute("SELECT id FROM personal WHERE id = ?", (personal_id,)).fetchone()
    if not existe:
        conn.close()
        raise PersonalError("Esa persona no existe")
    conn.execute(
        "UPDATE personal SET nombre_canonico = ?, variantes = ? WHERE id = ?",
        (nombre_canonico, json.dumps(variantes, ensure_ascii=False), personal_id),
    )
    conn.commit()
    conn.close()


def dar_salida(asignacion_id, fecha, tipo, tienda_destino=None,
                confirmar_duplicado=False, fusionar_con_personal_id=None):
    if tipo not in ("baja", "traslado"):
        raise PersonalError("Tipo de salida no válido")
    fecha = (fecha or "").strip()
    if not fecha:
        raise PersonalError("Falta la fecha de salida")

    conn = get_connection()
    asignacion = conn.execute(
        "SELECT * FROM personal_asignaciones WHERE id = ?", (asignacion_id,)
    ).fetchone()
    if not asignacion:
        conn.close()
        raise PersonalError("Esa asignación no existe")
    if not asignacion["activo"]:
        conn.close()
        raise PersonalError("Esa persona ya no está activa en esa tienda")

    destino_existente = None
    if tipo == "traslado":
        tienda_destino = (tienda_destino or "").strip()
        if not tienda_destino:
            conn.close()
            raise PersonalError("Falta la tienda de destino del traslado")
        if tienda_destino == asignacion["tienda"]:
            conn.close()
            raise PersonalError("La tienda de destino tiene que ser distinta de la actual")

        persona = conn.execute(
            "SELECT nombre_canonico, variantes FROM personal WHERE id = ?", (asignacion["personal_id"],)
        ).fetchone()

        if fusionar_con_personal_id:
            destino_existente = conn.execute(
                "SELECT id, variantes FROM personal WHERE id = ?", (fusionar_con_personal_id,)
            ).fetchone()
            if not destino_existente:
                conn.close()
                raise PersonalError("La persona con la que fusionar ya no existe")
        elif not confirmar_duplicado:
            # Al trasladarla, ¿ya hay alguien con ese nombre en la tienda de
            # destino? (el caso que motivó esto: "Pilar" ya existía en
            # Plenilunio y al trasladar a otra "Pilar"/"Maria Pilar" desde
            # otra tienda se creaba una ficha aparte, partiendo en dos las
            # menciones de la misma persona en vez de sumarlas en una sola).
            duplicados = _buscar_posibles_duplicados(conn, tienda_destino, persona["nombre_canonico"], json.loads(persona["variantes"]))
            if duplicados:
                conn.close()
                raise PersonalDuplicadoError(duplicados)

    conn.execute(
        "UPDATE personal_asignaciones SET fecha_fin = ?, activo = 0, motivo_fin = ? WHERE id = ?",
        (fecha, tipo, asignacion_id),
    )

    nueva_asignacion_id = None
    if tipo == "traslado":
        personal_id_destino = asignacion["personal_id"]
        crear_asignacion_destino = True
        if fusionar_con_personal_id:
            variantes_unidas = _normalizar_variantes(json.loads(destino_existente["variantes"]) + json.loads(persona["variantes"]))
            conn.execute(
                "UPDATE personal SET variantes = ? WHERE id = ?",
                (json.dumps(variantes_unidas, ensure_ascii=False), fusionar_con_personal_id),
            )
            personal_id_destino = fusionar_con_personal_id
            # Si ya tenía una asignación activa ahí (el caso normal: por eso
            # se detectó como duplicado) no se crea otra encima.
            ya_activa_aqui = conn.execute(
                "SELECT 1 FROM personal_asignaciones WHERE personal_id = ? AND tienda = ? AND activo = 1",
                (fusionar_con_personal_id, tienda_destino),
            ).fetchone()
            crear_asignacion_destino = not ya_activa_aqui
        if crear_asignacion_destino:
            cur = conn.execute(
                "INSERT INTO personal_asignaciones (personal_id, tienda, fecha_inicio, activo) VALUES (?, ?, ?, 1)",
                (personal_id_destino, tienda_destino, fecha),
            )
            nueva_asignacion_id = cur.lastrowid

    conn.commit()
    conn.close()
    return {"ok": True, "nueva_asignacion_id": nueva_asignacion_id}


def fusionar_personal(personal_id_origen, personal_id_destino):
    """Une dos fichas que resultan ser la misma persona (p.ej. dadas de alta
    por separado antes de que existiera la detección automática de
    duplicados): todo el historial de asignaciones de `origen` pasa a
    `destino`, sus variantes se unen, y la ficha `origen` (ya sin
    asignaciones) se borra."""
    if personal_id_origen == personal_id_destino:
        raise PersonalError("No se puede fusionar una persona consigo misma")

    conn = get_connection()
    origen = conn.execute("SELECT id, variantes FROM personal WHERE id = ?", (personal_id_origen,)).fetchone()
    destino = conn.execute("SELECT id, variantes FROM personal WHERE id = ?", (personal_id_destino,)).fetchone()
    if not origen or not destino:
        conn.close()
        raise PersonalError("Alguna de las dos personas ya no existe")

    variantes_unidas = _normalizar_variantes(json.loads(destino["variantes"]) + json.loads(origen["variantes"]))
    conn.execute(
        "UPDATE personal SET variantes = ? WHERE id = ?",
        (json.dumps(variantes_unidas, ensure_ascii=False), personal_id_destino),
    )

    # Si origen y destino tienen las dos una asignación ACTIVA en la misma
    # tienda (el caso típico: por eso se detectaron como la misma persona),
    # reasignar sin más dejaría dos filas activas de destino en esa tienda.
    # Se cierra la de origen (como si fuera la que "se traslada" a la ficha
    # de destino) en vez de dejarla activa por duplicado.
    tiendas_activas_destino = {
        row["tienda"] for row in conn.execute(
            "SELECT tienda FROM personal_asignaciones WHERE personal_id = ? AND activo = 1", (personal_id_destino,)
        ).fetchall()
    }
    asignaciones_origen = conn.execute(
        "SELECT id, tienda, activo FROM personal_asignaciones WHERE personal_id = ?", (personal_id_origen,)
    ).fetchall()
    hoy = datetime.date.today().isoformat()
    for a in asignaciones_origen:
        if a["activo"] and a["tienda"] in tiendas_activas_destino:
            conn.execute(
                "UPDATE personal_asignaciones SET personal_id = ?, activo = 0, fecha_fin = ?, motivo_fin = 'fusion' WHERE id = ?",
                (personal_id_destino, hoy, a["id"]),
            )
        else:
            conn.execute("UPDATE personal_asignaciones SET personal_id = ? WHERE id = ?", (personal_id_destino, a["id"]))

    conn.execute("DELETE FROM personal WHERE id = ?", (personal_id_origen,))
    conn.commit()
    conn.close()


def eliminar_personal(personal_id):
    """Borra a la persona y TODAS sus asignaciones (histórico incluido) —
    pensado para deshacer una alta hecha por error, no para una salida
    normal (eso es dar_salida)."""
    conn = get_connection()
    conn.execute("DELETE FROM personal_asignaciones WHERE personal_id = ?", (personal_id,))
    conn.execute("DELETE FROM personal WHERE id = ?", (personal_id,))
    conn.commit()
    conn.close()


def sugerir_variantes(nombre):
    """Le pide a Gemini diminutivos/hipocorísticos y erratas típicas de un
    nombre de pila en español, para no tener que pensarlos todos a mano al
    dar de alta a alguien (p.ej. Pilar -> Pili). Devuelve una lista de
    strings en minúsculas; si Gemini falla, la persona puede seguir
    escribiendo variantes a mano en el formulario igualmente."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise PersonalError("Falta el nombre")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise PersonalError("Falta configurar GEMINI_API_KEY en el entorno del servidor")

    prompt = (
        f"Nombre de pila español: \"{nombre}\".\n"
        "Dame sus variantes de escritura habituales en España: diminutivos, hipocorísticos "
        "y erratas típicas de tildes/teclado que la gente usaría al escribir una reseña sobre "
        "esta persona. Responde SOLO un array JSON de strings en minúsculas, sin explicación "
        "ni markdown, máximo 8 elementos. Ejemplo de formato: [\"variante1\",\"variante2\"]"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 200,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    try:
        resp = requests.post(GEMINI_URL, params={"key": api_key}, json=body, timeout=20)
    except requests.RequestException as exc:
        raise PersonalError(f"No se pudo contactar con Gemini: {exc}") from exc
    if resp.status_code != 200:
        raise PersonalError(f"Gemini devolvió un error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    candidatos = data.get("candidates") or []
    if not candidatos:
        raise PersonalError("Gemini no devolvió variantes")
    texto = "".join(p.get("text", "") for p in candidatos[0].get("content", {}).get("parts", [])).strip()
    texto = texto.strip("`")
    if texto.lower().startswith("json"):
        texto = texto[4:].strip()

    try:
        variantes = json.loads(texto)
    except (ValueError, TypeError):
        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if not match:
            raise PersonalError("Gemini no devolvió un formato reconocible")
        variantes = json.loads(match.group(0))

    return _normalizar_variantes(variantes)


ensure_personal_tables()
