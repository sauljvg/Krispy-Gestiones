"""Motor genérico de "Test" — constructor de encuestas por páginas y
preguntas (identificación, escala Likert, texto abierto, opción múltiple),
con una página pública para que cualquiera responda y un panel privado para
editar la estructura en cualquier momento. Pensado para sustituir a
Microsoft Forms: mismo aspecto (fondo de imagen, tarjeta centrada, barra de
progreso, Atrás/Siguiente) y, si la encuesta se vincula a un tipo de
Informe, la respuesta se puntúa automáticamente (motor de scoring_valores)
igual que si se hubiera subido el Excel de Forms a mano."""
import datetime
import json
import os
import re
from zoneinfo import ZoneInfo

import clima as clima_module
import entrevistas as entrevistas_module
import informes as informes_module
import reclutamiento as reclutamiento_module
from db import DATA_DIR, get_connection

FONDOS_DIR = os.path.join(DATA_DIR, "uploads", "encuestas_fondos")

TIPOS_PREGUNTA = {"texto", "email", "numero", "likert", "abierta", "opcion_simple", "opcion_multiple", "prioridad", "fecha", "calificacion"}

LIKERT_OPCIONES = [
    "Totalmente en desacuerdo", "En desacuerdo", "Ni de acuerdo ni en desacuerdo",
    "De acuerdo", "Totalmente de acuerdo",
]

# El módulo de Test guarda el PUNTO (1-5) de una pregunta de escala, no el
# texto de la leyenda (igual que ya asume _likert_points_strict en
# scoring_valores.py) -- pero Clima Laboral (clima.py) espera el texto tal
# cual lo trae un Excel de Forms. Se traduce aquí, SOLO para lo que se
# manda a clima_module.ingest_respuesta_directa (ver guardar_respuesta),
# nunca dentro de clima.py: esa función recalcula en caliente TODAS las
# oleadas -- incluidas las importadas por Excel hace tiempo -- cada vez que
# se abre un informe, así que traducir números ahí tendría efecto
# retroactivo sobre informes ya entregados si algún dato histórico tuviera
# por casualidad un valor numérico suelto.
LIKERT_TEXTO_POR_PUNTO = {"1": LIKERT_OPCIONES[0], "2": LIKERT_OPCIONES[1], "3": LIKERT_OPCIONES[2], "4": LIKERT_OPCIONES[3], "5": LIKERT_OPCIONES[4]}


def ensure_encuestas_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            estado TEXT NOT NULL DEFAULT 'cerrada',
            fondo_ruta TEXT,
            color_boton TEXT NOT NULL DEFAULT '#5b2a2a',
            mensaje_final TEXT NOT NULL DEFAULT 'Gracias por completar el formulario.',
            tipo_informe_clave TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # tipo_informe_clave y tipo_entrevista_empresa son mutuamente excluyentes
    # en la práctica (un test alimenta O un tipo de Informe O la Entrevista
    # de Salida de una empresa, nunca las dos) — se guardan en columnas
    # separadas en vez de una sola clave con prefijo para no tener que
    # parsear un string compuesto en cada sitio que lo usa.
    cols_encuestas = {row[1] for row in conn.execute("PRAGMA table_info(encuestas)")}
    if "tipo_entrevista_empresa" not in cols_encuestas:
        conn.execute("ALTER TABLE encuestas ADD COLUMN tipo_entrevista_empresa TEXT")
    if "enlace_corto" not in cols_encuestas:
        # Enlace acortado a mano (TinyURL o similar) para usar en emails/
        # recordatorios en vez del "enlace público" largo — puramente
        # informativo, el backend no lo usa para resolver la encuesta.
        conn.execute("ALTER TABLE encuestas ADD COLUMN enlace_corto TEXT")
    if "mensaje_no_apto" not in cols_encuestas:
        # Mensaje alternativo mostrado en vez de mensaje_final cuando la
        # respuesta recién enviada resulta "No apto" (ver guardar_respuesta)
        # -- editable en Ajustes igual que mensaje_final, con un texto
        # sugerido por defecto para no dejarlo vacío en los tests ya creados.
        conn.execute(
            "ALTER TABLE encuestas ADD COLUMN mensaje_no_apto TEXT NOT NULL DEFAULT "
            "'Gracias por contestar nuestro test. En esta ocasión no has superado el proceso, pero te deseamos mucha suerte.'"
        )
    if "evitar_duplicados" not in cols_encuestas:
        # Casilla en Ajustes de cada test: si está activa, guardar_respuesta
        # rechaza una respuesta nueva cuando coincide con una anterior de la
        # MISMA encuesta por IP, nombre completo, teléfono o email (ver
        # _es_respuesta_duplicada) -- pensado para que la misma persona no
        # pueda responder dos veces. Por defecto desactivada (0), para no
        # cambiar el comportamiento de los tests ya existentes.
        conn.execute("ALTER TABLE encuestas ADD COLUMN evitar_duplicados INTEGER NOT NULL DEFAULT 0")
    if "usar_mensaje_no_apto" not in cols_encuestas:
        # Interruptor en Ajustes: el concepto de "No apto" (por puntuación de
        # scoring_valores o por una opción marcada como descalificatoria)
        # solo tiene sentido en tests que SE EVALÚAN -- para Entrevista de
        # Salida o Clima Laboral, que son solo respuestas sin resultado
        # apto/no apto, mostrar y usar ese mensaje no encaja. Default 1
        # (activado) para no cambiar el comportamiento de los tests ya
        # existentes, que ya cuentan con este mensaje configurado.
        conn.execute("ALTER TABLE encuestas ADD COLUMN usar_mensaje_no_apto INTEGER NOT NULL DEFAULT 1")
    if "fecha_cierre" not in cols_encuestas:
        # Fecha de caducidad (opcional): el test deja de estar disponible
        # automáticamente al llegar esta fecha, a las 23:59 hora de Madrid
        # (ver _vencido) -- sin tener que acordarse de pulsar "Despublicar".
        # NO se pisa el campo "estado" al vencer: si luego se alarga la
        # fecha, el test vuelve a estar disponible solo con cambiar la
        # fecha, sin tener que volver a publicarlo a mano.
        conn.execute("ALTER TABLE encuestas ADD COLUMN fecha_cierre TEXT")
    if "clima_oleada_id" not in cols_encuestas:
        # Tercer destino posible (mutuamente excluyente con tipo_informe_clave
        # y tipo_entrevista_empresa, mismo motivo que ese comentario): un test
        # de Clima Laboral alimenta directamente una oleada del módulo
        # dedicado (backend/clima.py), reemplazando el paso de exportar de
        # Microsoft Forms y subir el Excel a mano -- ver guardar_respuesta.
        # A diferencia de los otros dos destinos (una clave fija por
        # categoría/empresa), aquí se guarda el id de una oleada concreta
        # porque cada fase de Clima (encuesta completa, pulso...) es su
        # propia oleada con su propia plantilla de empleados esperados.
        conn.execute("ALTER TABLE encuestas ADD COLUMN clima_oleada_id INTEGER REFERENCES clima_oleadas(id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_paginas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL REFERENCES encuestas(id),
            orden INTEGER NOT NULL,
            instrucciones TEXT
        )
    """)
    # Ramificación: una página puede depender de la respuesta a una pregunta
    # de una página ANTERIOR (p.ej. "Centro de Trabajo" -> mostrar solo el
    # bloque de "Puesto" que corresponda a ese centro), igual que las
    # secciones condicionales de Microsoft Forms/Google Forms. NULL en
    # condicion_pregunta_id = página siempre visible (comportamiento previo,
    # así que no hace falta migrar datos existentes).
    cols_paginas = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_paginas)")}
    if "condicion_pregunta_id" not in cols_paginas:
        conn.execute("ALTER TABLE encuesta_paginas ADD COLUMN condicion_pregunta_id INTEGER")
        conn.execute("ALTER TABLE encuesta_paginas ADD COLUMN condicion_valores TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_preguntas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pagina_id INTEGER NOT NULL REFERENCES encuesta_paginas(id),
            orden INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            etiqueta TEXT NOT NULL,
            obligatoria INTEGER NOT NULL DEFAULT 1,
            opciones_json TEXT
        )
    """)
    # mostrar_dashboard: marca explícita de "esta respuesta quiero verla en
    # Scoring/Dashboard de Informes, no solo en la hoja Respuestas" — antes
    # era automático para abierta/prioridad; ahora es una casilla que el
    # admin puede activar en CUALQUIER tipo de pregunta (p.ej. una opción
    # múltiple de una pregunta situacional también puede ser útil de ver de
    # un vistazo). Las preguntas abiertas/prioridad ya existentes se migran
    # activadas para no perder el comportamiento que ya tenían.
    cols_preguntas = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_preguntas)")}
    if "mostrar_dashboard" not in cols_preguntas:
        conn.execute("ALTER TABLE encuesta_preguntas ADD COLUMN mostrar_dashboard INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE encuesta_preguntas SET mostrar_dashboard = 1 WHERE tipo IN ('abierta', 'prioridad')")
    # "opcion_multiple" originalmente solo dejaba marcar UNA opción (radio) —
    # el nombre no correspondía al comportamiento. Se separa en dos tipos:
    # "opcion_simple" (una sola respuesta, igual que antes) y "opcion_multiple"
    # (ahora sí, varias marcadas a la vez). Todo lo que ya existía en la BD
    # con tipo 'opcion_multiple' era en realidad de una sola respuesta, así
    # que se renombra una única vez (marcador de columna para no repetir esta
    # migración si un admin crea preguntas nuevas de opción múltiple real
    # después).
    if "migrada_opcion_simple" not in cols_preguntas:
        conn.execute("ALTER TABLE encuesta_preguntas ADD COLUMN migrada_opcion_simple INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE encuesta_preguntas SET tipo = 'opcion_simple' WHERE tipo = 'opcion_multiple'")
    # opciones_descarta_json: lista de booleanos en paralelo a opciones_json
    # (misma posición = misma opción) -- marca qué opciones de una pregunta
    # de opción simple descalifican al candidato. Solo tiene sentido en
    # "opcion_simple" (ver condicionEditorHTML en tests.js, que restringe
    # igual las preguntas usables para ramificar). Si quien responde elige
    # una opción marcada así, guardar_respuesta() fuerza RESULTADO = "No
    # apto" en la fila de Informes que genera esa respuesta -- así entra en
    # el mismo filtro "Excluir/Solo no aptos" que ya existía para las
    # respuestas puntuadas por scoring_valores, sin tener que duplicar esa
    # lógica de filtro.
    if "opciones_descarta_json" not in cols_preguntas:
        conn.execute("ALTER TABLE encuesta_preguntas ADD COLUMN opciones_descarta_json TEXT")
    # Sin fila_hash/dedup a propósito: cada persona real puede responder una
    # sola vez desde el propio flujo (no hay reenvío), y a diferencia de
    # Informes esto no se alimenta por Excel donde sí hace falta deduplicar
    # una posible re-importación del mismo archivo.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_respuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL REFERENCES encuestas(id),
            datos_json TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            dispositivo TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Enlace a la fila que esta respuesta generó en Informes (o NULL si el
    # test no alimenta ningún tipo de Informe) — para poder llevar al admin
    # directamente a "cuál fue la respuesta registrada" desde "Ver respuestas"
    # en vez de solo el JSON crudo interno.
    cols_respuestas = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_respuestas)")}
    if "informe_respuesta_id" not in cols_respuestas:
        conn.execute("ALTER TABLE encuesta_respuestas ADD COLUMN informe_tipo_clave TEXT")
        conn.execute("ALTER TABLE encuesta_respuestas ADD COLUMN informe_hoja TEXT")
        conn.execute("ALTER TABLE encuesta_respuestas ADD COLUMN informe_respuesta_id INTEGER")
    # Notificación de "hay respuestas nuevas" junto al menú hamburguesa: por
    # usuario, guarda desde cuándo cuenta como "ya visto" — todo lo que llegó
    # después de esa marca es "nuevo". Al crear la tabla no hay fila para
    # nadie todavía; get_notificaciones_tests() la crea con la hora actual en
    # la primera llamada de cada usuario, así el historial ya acumulado no
    # aparece de golpe como "nuevo" la primera vez que alguien entra tras
    # desplegar esto.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notificaciones_vistas (
            usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
            visto_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Cada apertura del enlace público genera un token propio (encuesta.js lo
    # crea al cargar y lo reenvía en cada cambio de página) — a diferencia de
    # encuesta_respuestas (que solo existe si se llegó a ENVIAR el test), esto
    # deja rastro de quien abrió el enlace y en qué página se quedó, aunque
    # nunca termine. pagina_maxima es la más lejos que llegó (no se pisa hacia
    # atrás si vuelve con "Atrás"), y sirve para el embudo de abandono.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encuesta_sesiones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL REFERENCES encuestas(id),
            token TEXT NOT NULL UNIQUE,
            pagina_maxima INTEGER NOT NULL DEFAULT 1,
            completado INTEGER NOT NULL DEFAULT 0,
            iniciado_en TEXT NOT NULL DEFAULT (datetime('now')),
            ultima_actividad TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # ip: cada apertura del enlace genera un token nuevo (ver comentario de
    # arriba), así que la misma persona recargando la página o volviendo a
    # abrir el enlace varias veces contaba como varias "aperturas" distintas
    # en el embudo. Con la ip guardada, get_embudo() puede agrupar por
    # persona (misma idea que _es_respuesta_duplicada en guardar_respuesta)
    # en vez de por sesión suelta.
    cols_sesiones = {row[1] for row in conn.execute("PRAGMA table_info(encuesta_sesiones)")}
    if "ip" not in cols_sesiones:
        conn.execute("ALTER TABLE encuesta_sesiones ADD COLUMN ip TEXT")
    _deduplicar_sesiones_repetidas(conn)
    conn.commit()
    conn.close()
    os.makedirs(FONDOS_DIR, exist_ok=True)


def _deduplicar_sesiones_repetidas(conn):
    """get_embudo() ya agrupa por ip al contar (ver ahí), pero la tabla en
    sí puede seguir teniendo varias filas para la misma persona (recargó la
    página, volvió a abrir el enlace...) de antes de ese cambio. Se
    fusionan aquí una sola vez: por cada (encuesta_id, ip) con más de una
    fila, se queda la más antigua (menor id) con la página más lejana
    alcanzada por cualquiera de ellas y marcada como completada si
    CUALQUIERA llegó a enviarse, y se borran las demás. Idempotente (tras
    la primera pasada ya no queda ningún grupo con más de una fila). No
    toca las filas sin ip (de antes de que existiera esa columna): esas
    siguen contando cada una por separado, igual que en get_embudo()."""
    grupos = conn.execute("""
        SELECT encuesta_id, ip FROM encuesta_sesiones
        WHERE ip IS NOT NULL AND ip != ''
        GROUP BY encuesta_id, ip
        HAVING COUNT(*) > 1
    """).fetchall()
    for grupo in grupos:
        filas = conn.execute("""
            SELECT id, pagina_maxima, completado, iniciado_en, ultima_actividad
            FROM encuesta_sesiones WHERE encuesta_id = ? AND ip = ? ORDER BY id
        """, (grupo["encuesta_id"], grupo["ip"])).fetchall()
        superviviente = filas[0]["id"]
        conn.execute("""
            UPDATE encuesta_sesiones
            SET pagina_maxima = ?, completado = ?, iniciado_en = ?, ultima_actividad = ?
            WHERE id = ?
        """, (
            max(f["pagina_maxima"] for f in filas),
            max(f["completado"] for f in filas),
            min(f["iniciado_en"] for f in filas),
            max(f["ultima_actividad"] for f in filas),
            superviviente,
        ))
        conn.executemany(
            "DELETE FROM encuesta_sesiones WHERE id = ?",
            [(f["id"],) for f in filas if f["id"] != superviviente],
        )


# Igual que EN_LINEA_MINUTOS en auth.py (usuarios internos) — aquí es cuánto
# tiempo sin heartbeat hace que alguien deje de contar como "en vivo" en el
# test. Encuesta.js manda un heartbeat cada 20s mientras la pestaña sigue
# abierta, así que 2 min da margen de sobra sin dejar sesiones "fantasma"
# marcadas como activas mucho rato tras cerrar la pestaña sin querer.
EN_VIVO_MINUTOS = 2


def registrar_sesion(identificador, token, pagina, ip=None):
    conn = get_connection()
    row = _fila_por_slug_o_codigo(conn, identificador)
    if not row:
        conn.close()
        return
    conn.execute("""
        INSERT INTO encuesta_sesiones (encuesta_id, token, pagina_maxima, ip)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(token) DO UPDATE SET
            pagina_maxima = MAX(pagina_maxima, excluded.pagina_maxima),
            ultima_actividad = datetime('now')
    """, (row["id"], token, pagina, ip))
    conn.commit()
    conn.close()


def marcar_sesion_completada(token):
    if not token:
        return
    conn = get_connection()
    conn.execute(
        "UPDATE encuesta_sesiones SET completado = 1, ultima_actividad = datetime('now') WHERE token = ?", (token,)
    )
    conn.commit()
    conn.close()


def contar_en_vivo_por_encuesta():
    """Cuántas sesiones activas (heartbeat reciente, sin completar) hay AHORA
    MISMO por encuesta — alimenta el indicador junto a cada test en la lista."""
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT encuesta_id, COUNT(*) AS n FROM encuesta_sesiones
        WHERE completado = 0 AND ultima_actividad >= datetime('now', '-{EN_VIVO_MINUTOS} minutes')
        GROUP BY encuesta_id
    """).fetchall()
    conn.close()
    return {r["encuesta_id"]: r["n"] for r in rows}


def get_en_vivo_detalle(encuesta_id):
    """Detalle de cada sesión activa de UN test concreto (en qué página va
    cada una) — para el desplegable "quién está en vivo" del editor, a
    diferencia de contar_en_vivo_por_encuesta que solo da el total por test."""
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT pagina_maxima, iniciado_en, ultima_actividad FROM encuesta_sesiones
        WHERE encuesta_id = ? AND completado = 0
              AND ultima_actividad >= datetime('now', '-{EN_VIVO_MINUTOS} minutes')
        ORDER BY ultima_actividad DESC
    """, (encuesta_id,)).fetchall()
    conn.close()
    return [{"pagina": r["pagina_maxima"], "iniciado_en": r["iniciado_en"], "ultima_actividad": r["ultima_actividad"]} for r in rows]


def borrar_sesiones(encuesta_id):
    """Vacía el rastro de aperturas/abandono de un test (deja el embudo a
    cero) — para descartar pruebas propias del staff antes de que el test
    salga de verdad, sin tener que tocar la base de datos a mano."""
    conn = get_connection()
    conn.execute("DELETE FROM encuesta_sesiones WHERE encuesta_id = ?", (encuesta_id,))
    conn.commit()
    conn.close()


def get_embudo(encuesta_id):
    """Aperturas vs completados y, página a página, cuántas personas
    llegaron al menos hasta ahí — para ver dónde se cae la gente en un test
    largo, no solo cuántos lo acaban.

    Cada apertura del enlace genera un token de sesión nuevo (ver
    ensure_encuestas_tables), así que la misma persona recargando la página
    o volviendo a abrir el enlace varias veces generaría varias filas en
    encuesta_sesiones. Para no contarla varias veces, se agrupa por ip en
    vez de por fila -- si dos sesiones comparten ip se tratan como la misma
    persona (se queda con la página más lejana a la que llegó, y cuenta
    como completada si CUALQUIERA de sus sesiones se completó). Las
    sesiones sin ip (registradas antes de que existiera esta columna) se
    cuentan cada una por separado, con COALESCE(ip, 'sesion:'||id), para no
    fusionarlas entre sí por error."""
    conn = get_connection()
    total_paginas = conn.execute(
        "SELECT COUNT(*) FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,)
    ).fetchone()[0]
    personas = conn.execute("""
        SELECT COALESCE(ip, 'sesion:' || id) AS persona,
               MAX(pagina_maxima) AS pagina_maxima,
               MAX(completado) AS completado
        FROM encuesta_sesiones WHERE encuesta_id = ?
        GROUP BY persona
    """, (encuesta_id,)).fetchall()
    aperturas = len(personas)
    completados = sum(1 for p in personas if p["completado"])
    por_pagina = []
    if aperturas:
        for pagina in range(1, total_paginas + 1):
            n = sum(1 for p in personas if p["pagina_maxima"] >= pagina)
            por_pagina.append({"pagina": pagina, "llegaron": n})
    conn.close()
    return {"aperturas": aperturas, "completados": completados, "total_paginas": total_paginas, "por_pagina": por_pagina}


def get_notificaciones_tests(usuario_id):
    conn = get_connection()
    row = conn.execute("SELECT visto_en FROM notificaciones_vistas WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO notificaciones_vistas (usuario_id, visto_en) VALUES (?, datetime('now'))", (usuario_id,)
        )
        conn.commit()
        conn.close()
        return {"total": 0, "tests": []}
    visto_en = row["visto_en"]
    rows = conn.execute("""
        SELECT e.id, e.titulo, COUNT(r.id) AS nuevas
        FROM encuesta_respuestas r
        JOIN encuestas e ON e.id = r.encuesta_id
        WHERE r.creado_en > ?
        GROUP BY e.id
        ORDER BY MAX(r.creado_en) DESC
    """, (visto_en,)).fetchall()
    conn.close()
    tests = [{"id": r["id"], "titulo": r["titulo"], "nuevas": r["nuevas"]} for r in rows]
    return {"total": sum(t["nuevas"] for t in tests), "tests": tests}


def marcar_notificaciones_vistas(usuario_id):
    conn = get_connection()
    conn.execute("""
        INSERT INTO notificaciones_vistas (usuario_id, visto_en) VALUES (?, datetime('now'))
        ON CONFLICT(usuario_id) DO UPDATE SET visto_en = excluded.visto_en
    """, (usuario_id,))
    conn.commit()
    conn.close()


def _slugify(titulo):
    s = titulo.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "encuesta"


def _slug_disponible(conn, slug, excluir_id=None):
    row = conn.execute("SELECT id FROM encuestas WHERE slug = ?", (slug,)).fetchone()
    return row is None or row["id"] == excluir_id


def _generar_slug_unico(conn, titulo, excluir_id=None):
    base = _slugify(titulo)
    slug = base
    i = 2
    while not _slug_disponible(conn, slug, excluir_id):
        slug = f"{base}-{i}"
        i += 1
    return slug


def _vencido(fecha_cierre):
    """True si la fecha de caducidad (YYYY-MM-DD) ya pasó -- disponible
    hasta las 23:59:59 de ese día, hora de Madrid (mismo huso que "Fecha
    del test" en guardar_respuesta, para que caducidad y fecha del test
    hablen del mismo día para quien lo administra)."""
    if not fecha_cierre:
        return False
    try:
        limite = datetime.datetime.strptime(fecha_cierre, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=ZoneInfo("Europe/Madrid")
        )
    except ValueError:
        return False
    return datetime.datetime.now(ZoneInfo("Europe/Madrid")) > limite


def _row_encuesta(r):
    d = dict(r)
    d["tiene_fondo"] = d.pop("fondo_ruta", None) is not None
    d["evitar_duplicados"] = bool(d["evitar_duplicados"])
    d["vencido"] = _vencido(d.get("fecha_cierre"))
    return d


def list_encuestas():
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.*, (SELECT COUNT(*) FROM encuesta_respuestas r WHERE r.encuesta_id = e.id) AS num_respuestas
        FROM encuestas e ORDER BY e.id DESC
    """).fetchall()
    conn.close()
    return [_row_encuesta(r) for r in rows]


def get_enlace_corto_entrevista(empresa):
    """El enlace corto (TinyURL) del test que alimenta la Entrevista de
    Salida de esta empresa — para el botón "Enviar Recordatorio" de
    Entrevista de Salida, que no tiene por qué tener acceso al módulo Test.
    Si hay más de un test marcado para la misma empresa (no debería, pero no
    hay constraint que lo impida), se usa el más reciente."""
    conn = get_connection()
    row = conn.execute(
        "SELECT enlace_corto FROM encuestas WHERE tipo_entrevista_empresa = ? ORDER BY id DESC LIMIT 1",
        (empresa,),
    ).fetchone()
    conn.close()
    return row["enlace_corto"] if row else None


def _fetch_estructura(conn, encuesta_id):
    paginas = conn.execute(
        "SELECT * FROM encuesta_paginas WHERE encuesta_id = ? ORDER BY orden", (encuesta_id,)
    ).fetchall()
    resultado = []
    for p in paginas:
        preguntas = conn.execute(
            "SELECT * FROM encuesta_preguntas WHERE pagina_id = ? ORDER BY orden", (p["id"],)
        ).fetchall()
        preguntas_dict = []
        for q in preguntas:
            qd = dict(q)
            qd["opciones"] = json.loads(qd.pop("opciones_json") or "[]")
            qd["opciones_descarta"] = json.loads(qd.pop("opciones_descarta_json") or "[]")
            qd["obligatoria"] = bool(qd["obligatoria"])
            qd["mostrar_dashboard"] = bool(qd["mostrar_dashboard"])
            preguntas_dict.append(qd)
        pd = dict(p)
        pd["condicion_valores"] = json.loads(pd.get("condicion_valores") or "[]")
        pd["preguntas"] = preguntas_dict
        resultado.append(pd)
    return resultado


def get_encuesta(encuesta_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM encuestas WHERE id = ?", (encuesta_id,)).fetchone()
    if not row:
        conn.close()
        return None
    encuesta = _row_encuesta(row)
    encuesta["paginas"] = _fetch_estructura(conn, encuesta_id)
    conn.close()
    return encuesta


def _fila_por_slug_o_codigo(conn, identificador):
    """El enlace público acepta tanto el slug de texto (enlaces ya
    compartidos, siguen funcionando) como el código corto numérico — el id
    de la propia encuesta, mostrado con 4 cifras (p.ej. "0008") — para que
    el enlace sea corto y correlativo sin tener que añadir una columna
    nueva ni mantener dos identificadores en sincronía."""
    if identificador.isdigit():
        return conn.execute("SELECT * FROM encuestas WHERE id = ?", (int(identificador),)).fetchone()
    return conn.execute("SELECT * FROM encuestas WHERE slug = ?", (identificador,)).fetchone()


def get_encuesta_publica(identificador):
    """Igual que get_encuesta pero solo si está abierta, y sin exponer
    tipo_informe_clave (detalle interno de administración, no le hace falta
    al candidato)."""
    conn = get_connection()
    row = _fila_por_slug_o_codigo(conn, identificador)
    if not row or row["estado"] != "abierta" or _vencido(row["fecha_cierre"]):
        conn.close()
        return None
    encuesta = _row_encuesta(row)
    encuesta["paginas"] = _fetch_estructura(conn, row["id"])
    conn.close()
    encuesta.pop("tipo_informe_clave", None)
    encuesta.pop("tipo_entrevista_empresa", None)
    encuesta.pop("clima_oleada_id", None)
    return encuesta


def create_encuesta(titulo):
    conn = get_connection()
    slug = _generar_slug_unico(conn, titulo)
    cur = conn.execute(
        "INSERT INTO encuestas (titulo, slug) VALUES (?, ?)", (titulo.strip(), slug)
    )
    encuesta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return encuesta_id


def update_encuesta(encuesta_id, titulo, mensaje_final, color_boton, tipo_informe_clave, tipo_entrevista_empresa=None, enlace_corto=None, evitar_duplicados=False, mensaje_no_apto=None, clima_oleada_id=None, usar_mensaje_no_apto=True, fecha_cierre=None):
    conn = get_connection()
    conn.execute(
        "UPDATE encuestas SET titulo = ?, mensaje_final = ?, color_boton = ?, tipo_informe_clave = ?, "
        "tipo_entrevista_empresa = ?, enlace_corto = ?, evitar_duplicados = ?, mensaje_no_apto = ?, "
        "clima_oleada_id = ?, usar_mensaje_no_apto = ?, fecha_cierre = ? WHERE id = ?",
        (titulo.strip(), mensaje_final.strip(), color_boton.strip(), tipo_informe_clave or None,
         tipo_entrevista_empresa or None, (enlace_corto or "").strip() or None,
         1 if evitar_duplicados else 0, (mensaje_no_apto or "").strip() or mensaje_final.strip(),
         clima_oleada_id or None, 1 if usar_mensaje_no_apto else 0, (fecha_cierre or "").strip() or None,
         encuesta_id),
    )
    conn.commit()
    conn.close()


def set_estado(encuesta_id, abierta):
    conn = get_connection()
    conn.execute("UPDATE encuestas SET estado = ? WHERE id = ?", ("abierta" if abierta else "cerrada", encuesta_id))
    conn.commit()
    conn.close()


def guardar_fondo(encuesta_id, contenido, extension):
    ruta = os.path.join(FONDOS_DIR, f"{encuesta_id}{extension}")
    with open(ruta, "wb") as f:
        f.write(contenido)
    conn = get_connection()
    conn.execute("UPDATE encuestas SET fondo_ruta = ? WHERE id = ?", (ruta, encuesta_id))
    conn.commit()
    conn.close()


def get_fondo_ruta(encuesta_id):
    conn = get_connection()
    row = conn.execute("SELECT fondo_ruta FROM encuestas WHERE id = ?", (encuesta_id,)).fetchone()
    conn.close()
    return row["fondo_ruta"] if row and row["fondo_ruta"] else None


def delete_encuesta(encuesta_id):
    conn = get_connection()
    pagina_ids = [r["id"] for r in conn.execute("SELECT id FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,)).fetchall()]
    for pid in pagina_ids:
        conn.execute("DELETE FROM encuesta_preguntas WHERE pagina_id = ?", (pid,))
    conn.execute("DELETE FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,))
    conn.execute("DELETE FROM encuesta_respuestas WHERE encuesta_id = ?", (encuesta_id,))
    conn.execute("DELETE FROM encuestas WHERE id = ?", (encuesta_id,))
    conn.commit()
    conn.close()
    ruta = get_fondo_ruta(encuesta_id)
    if ruta and os.path.exists(ruta):
        os.remove(ruta)


def add_pagina(encuesta_id, instrucciones="", condicion_pregunta_id=None, condicion_valores=None):
    conn = get_connection()
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 FROM encuesta_paginas WHERE encuesta_id = ?", (encuesta_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO encuesta_paginas (encuesta_id, orden, instrucciones, condicion_pregunta_id, condicion_valores) "
        "VALUES (?, ?, ?, ?, ?)",
        (encuesta_id, orden, instrucciones, condicion_pregunta_id,
         json.dumps(condicion_valores or [], ensure_ascii=False)),
    )
    pagina_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pagina_id


def update_pagina(pagina_id, instrucciones, condicion_pregunta_id=None, condicion_valores=None):
    conn = get_connection()
    conn.execute(
        "UPDATE encuesta_paginas SET instrucciones = ?, condicion_pregunta_id = ?, condicion_valores = ? WHERE id = ?",
        (instrucciones, condicion_pregunta_id, json.dumps(condicion_valores or [], ensure_ascii=False), pagina_id),
    )
    conn.commit()
    conn.close()


def delete_pagina(pagina_id):
    conn = get_connection()
    actual = conn.execute("SELECT encuesta_id FROM encuesta_paginas WHERE id = ?", (pagina_id,)).fetchone()
    conn.execute("DELETE FROM encuesta_preguntas WHERE pagina_id = ?", (pagina_id,))
    conn.execute("DELETE FROM encuesta_paginas WHERE id = ?", (pagina_id,))
    if actual:
        _renumerar_paginas(conn, actual["encuesta_id"])
    conn.commit()
    conn.close()


def _renumerar_paginas(conn, encuesta_id):
    """Tras borrar una página quedaría un hueco en "orden" (p.ej. 1,3,4) que
    haría que mover_pagina no encontrara vecino exacto en algunos casos —
    se recompacta a 1..N en el mismo orden relativo."""
    filas = conn.execute(
        "SELECT id FROM encuesta_paginas WHERE encuesta_id = ? ORDER BY orden", (encuesta_id,)
    ).fetchall()
    for i, f in enumerate(filas, start=1):
        conn.execute("UPDATE encuesta_paginas SET orden = ? WHERE id = ?", (i, f["id"]))


def mover_pagina(pagina_id, direccion):
    """direccion: -1 (subir) o 1 (bajar) — intercambia el "orden" con la
    página vecina en esa dirección."""
    conn = get_connection()
    actual = conn.execute("SELECT * FROM encuesta_paginas WHERE id = ?", (pagina_id,)).fetchone()
    if not actual:
        conn.close()
        return
    vecino_orden = actual["orden"] + direccion
    vecino = conn.execute(
        "SELECT * FROM encuesta_paginas WHERE encuesta_id = ? AND orden = ?", (actual["encuesta_id"], vecino_orden)
    ).fetchone()
    if vecino:
        conn.execute("UPDATE encuesta_paginas SET orden = ? WHERE id = ?", (vecino_orden, actual["id"]))
        conn.execute("UPDATE encuesta_paginas SET orden = ? WHERE id = ?", (actual["orden"], vecino["id"]))
        conn.commit()
    conn.close()


def add_pregunta(pagina_id, tipo, etiqueta, obligatoria=True, opciones=None, mostrar_dashboard=False, opciones_descarta=None):
    if tipo not in TIPOS_PREGUNTA:
        raise ValueError(f"Tipo de pregunta desconocido: {tipo}")
    conn = get_connection()
    orden = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 FROM encuesta_preguntas WHERE pagina_id = ?", (pagina_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO encuesta_preguntas (pagina_id, orden, tipo, etiqueta, obligatoria, opciones_json, mostrar_dashboard, opciones_descarta_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (pagina_id, orden, tipo, etiqueta.strip(), 1 if obligatoria else 0,
         json.dumps(opciones or [], ensure_ascii=False), 1 if mostrar_dashboard else 0,
         json.dumps(opciones_descarta or [], ensure_ascii=False)),
    )
    pregunta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pregunta_id


# Cuestionario real de "Clima Laboral — Encuesta completa" (Krispy Kreme):
# centro de trabajo + 25 preguntas de escala en 5 secciones (5+5+5+4+6) + 2
# abiertas, mismo texto y orden que el PDF que se usaba en Microsoft Forms.
# Cada pregunta se etiqueta "Sección.Pregunta" -- mismo formato que ya
# reconoce clima._column_roles() para los Excel de Forms, así que Clima
# Laboral categoriza bien "Resultados de Engagement" (primera sección) vs
# "Impulsores de Engagement" (el resto) sin ningún cambio en ese lado.
CLIMA_CENTROS = ["ParqueSur Tienda", "ParqueSur Fábrica", "Princesa", "Caleido", "La Gavia", "Gran Plaza 2", "Oficinas"]
CLIMA_SECCIONES = [
    ("Satisfacción y compromiso", [
        "Estoy contento/a con mi trabajo en Krispy Kreme",
        "Recomendaría Krispy Kreme como un gran lugar para trabajar",
        "Espero seguir trabajando en Krispy Kreme en los próximos seis meses",
        "Me siento personalmente comprometido a ayudar a Krispy Kreme a alcanzar el éxito",
        "Me siento lleno de energía cuando hago mi trabajo",
    ]),
    ("Desarrollo y apoyo al desempeño", [
        "Tengo oportunidades de aprender y crecer en mi trabajo",
        "Recibo la capacitación que necesito para hacer bien mi trabajo",
        "Mi gerente valora mis opiniones y comentarios",
        "Mi gerente me brinda comentarios oportunos que ayudan a mejorar mi desempeño",
        "Tengo oportunidades constantes de utilizar mis fortalezas en el trabajo",
    ]),
    ("Recursos y reconocimiento", [
        "Recibo la información que necesito para tener un buen desempeño",
        "Recibo reconocimiento por el trabajo que hago",
        "Confío en los otros miembros del equipo de mi tienda/fábrica/oficina",
        "Considero que mi trabajo es gratificante",
        "Mis compañeros de trabajo están comprometidos a brindar una gran experiencia a nuestros clientes",
    ]),
    ("Liderazgo y cultura de equipo", [
        "Mi gerente está comprometido a brindar una gran experiencia a cada cliente",
        "Recomendaría a otras personas a trabajar para mi gerente",
        "El equipo gerencial habla a menudo con nuestro equipo sobre los comentarios de los clientes",
        "Mi gerente se preocupa por mí",
    ]),
    ("Bienestar, condiciones y pertenencia", [
        "En mi tienda, todos se tratan con respeto",
        "Siento que estoy trabajando en un lugar seguro",
        "Considero mi retribución competitiva en comparación con el mercado",
        "Tengo un equilibrio adecuado entre el trabajo y la vida personal",
        "Me siento identificado con los valores de Krispy Kreme",
        "Me siento orgulloso de trabajar en Krispy Kreme",
    ]),
]
CLIMA_ABIERTAS = [
    "¿Qué es lo que más te gusta de trabajar con nosotros?",
    "¿Qué consideras que podemos mejorar?",
]


def crear_plantilla_clima_encuesta_completa(encuesta_id):
    """Rellena un test recién creado (y todavía vacío) con la Encuesta
    completa estándar de Clima Laboral -- para "+ Nueva Encuesta completa de
    Clima Laboral" en el editor de Test (ver tests.js): en vez de partir de
    un test en blanco, ya queda con las 26 preguntas reales listas para
    revisar/editar antes de publicar. No se usa para "+ Nuevo Pulso" (un
    pulso normalmente lleva un subconjunto más corto, decidido caso a
    caso -- ver conversación con el usuario)."""
    pagina_centro = add_pagina(encuesta_id, "")
    add_pregunta(
        pagina_centro, "opcion_simple", "¿Cuál es tu centro de trabajo?", True,
        CLIMA_CENTROS, False, [False] * len(CLIMA_CENTROS),
    )
    for nombre_seccion, preguntas in CLIMA_SECCIONES:
        pagina_id = add_pagina(encuesta_id, "")
        for pregunta in preguntas:
            add_pregunta(pagina_id, "likert", f"{nombre_seccion}.{pregunta}", True, LIKERT_OPCIONES, False)
    pagina_abiertas = add_pagina(encuesta_id, "")
    for pregunta in CLIMA_ABIERTAS:
        add_pregunta(pagina_abiertas, "abierta", pregunta, True)


def update_pregunta(pregunta_id, etiqueta, obligatoria, opciones=None, mostrar_dashboard=False, opciones_descarta=None):
    conn = get_connection()
    conn.execute(
        "UPDATE encuesta_preguntas SET etiqueta = ?, obligatoria = ?, opciones_json = ?, mostrar_dashboard = ?, opciones_descarta_json = ? WHERE id = ?",
        (etiqueta.strip(), 1 if obligatoria else 0, json.dumps(opciones or [], ensure_ascii=False),
         1 if mostrar_dashboard else 0, json.dumps(opciones_descarta or [], ensure_ascii=False), pregunta_id),
    )
    conn.commit()
    conn.close()


def _renumerar_preguntas(conn, pagina_id):
    filas = conn.execute(
        "SELECT id FROM encuesta_preguntas WHERE pagina_id = ? ORDER BY orden", (pagina_id,)
    ).fetchall()
    for i, f in enumerate(filas, start=1):
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (i, f["id"]))


def delete_pregunta(pregunta_id):
    conn = get_connection()
    actual = conn.execute("SELECT pagina_id FROM encuesta_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    conn.execute("DELETE FROM encuesta_preguntas WHERE id = ?", (pregunta_id,))
    if actual:
        _renumerar_preguntas(conn, actual["pagina_id"])
    conn.commit()
    conn.close()


def mover_pregunta(pregunta_id, direccion):
    conn = get_connection()
    actual = conn.execute("SELECT * FROM encuesta_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    if not actual:
        conn.close()
        return
    vecino_orden = actual["orden"] + direccion
    vecino = conn.execute(
        "SELECT * FROM encuesta_preguntas WHERE pagina_id = ? AND orden = ?", (actual["pagina_id"], vecino_orden)
    ).fetchone()
    if vecino:
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (vecino_orden, actual["id"]))
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (actual["orden"], vecino["id"]))
        conn.commit()
    conn.close()


def mover_pregunta_a_pagina(pregunta_id, pagina_destino_id, antes_de_pregunta_id=None):
    """Mueve una pregunta a `pagina_destino_id` (puede ser la misma página en
    la que ya está, para simplemente reordenarla) e inserta justo antes de
    `antes_de_pregunta_id`, o al final si es None. Reconstruye el orden 1..N
    de la página destino entera (y de la de origen, si es distinta) en vez de
    solo desplazar huecos, para que quede siempre contiguo sin duplicados."""
    conn = get_connection()
    actual = conn.execute("SELECT * FROM encuesta_preguntas WHERE id = ?", (pregunta_id,)).fetchone()
    if not actual:
        conn.close()
        return
    pagina_origen_id = actual["pagina_id"]

    destino_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM encuesta_preguntas WHERE pagina_id = ? AND id != ? ORDER BY orden",
            (pagina_destino_id, pregunta_id),
        ).fetchall()
    ]
    indice = destino_ids.index(antes_de_pregunta_id) if antes_de_pregunta_id in destino_ids else len(destino_ids)
    destino_ids.insert(indice, pregunta_id)

    conn.execute("UPDATE encuesta_preguntas SET pagina_id = ? WHERE id = ?", (pagina_destino_id, pregunta_id))
    for i, pid in enumerate(destino_ids, start=1):
        conn.execute("UPDATE encuesta_preguntas SET orden = ? WHERE id = ?", (i, pid))
    if pagina_origen_id != pagina_destino_id:
        _renumerar_preguntas(conn, pagina_origen_id)
    conn.commit()
    conn.close()


def _detectar_dispositivo(user_agent):
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "Tablet"
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return "Móvil"
    if ua:
        return "Escritorio"
    return "Desconocido"


def _normalizar_telefono(v):
    return re.sub(r"\D", "", v or "")


def _es_respuesta_duplicada(conn, encuesta_id, ip, campos_contacto):
    """Compara esta respuesta contra TODAS las anteriores de la misma
    encuesta por IP, nombre completo, teléfono o email -- suelen ser datos
    únicos por persona, así que coincidir en cualquiera de ellos es buena
    señal de que es la MISMA persona respondiendo otra vez. Solo se llama
    si el test tiene la casilla "evitar_duplicados" activada (ver Ajustes
    en tests.js)."""
    nombre = (campos_contacto.get("nombre_completo") or "").strip().lower()
    telefono = _normalizar_telefono(campos_contacto.get("telefono"))
    email = (campos_contacto.get("email") or "").strip().lower()
    if not (nombre or telefono or email or ip):
        return False
    filas = conn.execute(
        "SELECT ip, datos_json FROM encuesta_respuestas WHERE encuesta_id = ?", (encuesta_id,)
    ).fetchall()
    for fila in filas:
        if ip and fila["ip"] == ip:
            return True
        campos_previos, _ = reclutamiento_module.mapear_datos_a_candidato(json.loads(fila["datos_json"]))
        nombre_previo = (campos_previos.get("nombre_completo") or "").strip().lower()
        telefono_previo = _normalizar_telefono(campos_previos.get("telefono"))
        email_previo = (campos_previos.get("email") or "").strip().lower()
        if nombre and nombre == nombre_previo:
            return True
        if telefono and telefono == telefono_previo:
            return True
        if email and email == email_previo:
            return True
    return False


def guardar_respuesta(identificador, respuestas_por_pregunta, ip, user_agent, token=None):
    """respuestas_por_pregunta: {pregunta_id (str o int): valor}. Se guarda
    tal cual (por id) para la vista de administración, y además se arma un
    segundo dict keyed por ETIQUETA de pregunta — así, si la encuesta
    alimenta un tipo de Informe, encaja tal cual con lo que espera
    scoring_valores.calcular() (que reconoce las preguntas por el texto de
    su enunciado, igual que en el Excel de Forms)."""
    conn = get_connection()
    row = _fila_por_slug_o_codigo(conn, identificador)
    if not row or row["estado"] != "abierta" or _vencido(row["fecha_cierre"]):
        conn.close()
        raise ValueError("Esta encuesta no está abierta actualmente")
    encuesta_id = row["id"]
    tipo_informe_clave = row["tipo_informe_clave"]

    preguntas = conn.execute("""
        SELECT eq.id, eq.etiqueta, eq.mostrar_dashboard, eq.tipo, eq.opciones_json, eq.opciones_descarta_json
        FROM encuesta_preguntas eq
        JOIN encuesta_paginas ep ON ep.id = eq.pagina_id
        WHERE ep.encuesta_id = ?
        ORDER BY ep.orden, eq.orden
    """, (encuesta_id,)).fetchall()
    etiqueta_por_id = {str(p["id"]): p["etiqueta"] for p in preguntas}
    mostrar_dashboard_por_id = {str(p["id"]): bool(p["mostrar_dashboard"]) for p in preguntas}

    # ¿Alguna respuesta eligió una opción marcada como descalificatoria? Solo
    # se mira en preguntas de opción simple (ver opciones_descarta_json) --
    # si es así, la fila que esto genere en Informes se fuerza a "No apto"
    # más abajo, sin importar lo que calcule scoring_valores.
    es_no_apto = False
    for pid, valor in respuestas_por_pregunta.items():
        pid = str(pid)
        pregunta = next((p for p in preguntas if str(p["id"]) == pid), None)
        if not pregunta or pregunta["tipo"] != "opcion_simple":
            continue
        opciones = json.loads(pregunta["opciones_json"] or "[]")
        descarta = json.loads(pregunta["opciones_descarta_json"] or "[]")
        if valor in opciones:
            idx = opciones.index(valor)
            if idx < len(descarta) and descarta[idx]:
                es_no_apto = True
                break

    # Dos preguntas pueden compartir el mismo enunciado a propósito (p.ej. la
    # misma pregunta de "Ordena las siguientes afirmaciones..." repetida en
    # varias páginas con distintas frases, tal cual el test real de Krispy
    # Kreme) — un dict simple perdería todas menos la última. Se numeran las
    # repetidas; el motor de scoring solo busca que el texto CONTENGA la
    # palabra clave, así que el sufijo no rompe la detección.
    #
    # columnas_extra: preguntas marcadas por el admin como "mostrar en el
    # dashboard" — no cambia su puntuación, pero Informes las copia tal cual
    # a Scoring/Dashboard para verlas de un vistazo (ver
    # scoring_valores.calcular()).
    fila_por_etiqueta = {}
    clave_a_pid = {}
    columnas_extra = set()
    for pid, etiqueta in etiqueta_por_id.items():
        if pid not in respuestas_por_pregunta:
            continue
        valor = respuestas_por_pregunta[pid]
        clave = etiqueta
        sufijo = 2
        while clave in fila_por_etiqueta:
            clave = f"{etiqueta} ({sufijo})"
            sufijo += 1
        fila_por_etiqueta[clave] = valor
        clave_a_pid[clave] = pid
        if mostrar_dashboard_por_id[pid]:
            columnas_extra.add(clave)

    if row["evitar_duplicados"]:
        campos_contacto, _ = reclutamiento_module.mapear_datos_a_candidato(fila_por_etiqueta)
        if _es_respuesta_duplicada(conn, encuesta_id, ip, campos_contacto):
            conn.close()
            raise ValueError("Ya has respondido este test anteriormente. Si crees que es un error, contacta con quien te lo compartió.")

    # Se valida ANTES de insertar (a diferencia de Informes/Entrevista de
    # Salida, que se resuelven después): si falta la pregunta de centro de
    # trabajo, mejor rechazar el envío con un error claro que aceptarlo y
    # perder en silencio la única forma de que esta respuesta anónima cuente
    # para su tienda en Clima Laboral.
    centro_clima = None
    if row["clima_oleada_id"]:
        centro_clima = clima_module.detectar_centro(fila_por_etiqueta)
        if not centro_clima:
            conn.close()
            raise ValueError('Falta la pregunta "¿Cuál es tu centro de trabajo?" en este test -- contacta con quien lo configuró.')

    dispositivo = _detectar_dispositivo(user_agent)
    cur = conn.execute(
        "INSERT INTO encuesta_respuestas (encuesta_id, datos_json, ip, user_agent, dispositivo) VALUES (?, ?, ?, ?, ?)",
        (encuesta_id, json.dumps(fila_por_etiqueta, ensure_ascii=False, default=str), ip, user_agent, dispositivo),
    )
    respuesta_id = cur.lastrowid
    conn.commit()
    conn.close()

    if tipo_informe_clave:
        # "Fecha del test" solo se manda a Informes (no se guarda en el
        # datos_json interno de encuesta_respuestas, que ya tiene su propio
        # creado_en) — scoring_valores._detectar_fecha la reconoce por su
        # nombre exacto y así no confunde con ella ninguna pregunta cuyo
        # enunciado contenga "fecha"/"hora" de pasada.
        fila_para_informes = dict(fila_por_etiqueta)
        # A diferencia de creado_en (que se guarda en UTC y se convierte a
        # hora local en el navegador al mostrarlo, ver tests.js
        # formatearFechaHoraLocal), esta columna se copia tal cual dentro de
        # datos_json y se muestra literal en Informes — por eso aquí hace
        # falta calcular ya la hora local, o se ve 2h por detrás de la real.
        fila_para_informes["Fecha del test"] = datetime.datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")
        enlace = informes_module.ingest_fila_directa(
            tipo_informe_clave, fila_para_informes, origen=f"Test web: {row['titulo']}", columnas_extra=columnas_extra
        )
        if enlace.get("respuesta_id"):
            conn2 = get_connection()
            conn2.execute(
                "UPDATE encuesta_respuestas SET informe_tipo_clave = ?, informe_hoja = ?, informe_respuesta_id = ? WHERE id = ?",
                (enlace["tipo_clave"], enlace["hoja"], enlace["respuesta_id"], respuesta_id),
            )
            conn2.commit()
            conn2.close()
            if es_no_apto:
                # Se fuerza DESPUÉS de ingest_fila_directa (que puede haber
                # calculado su propio RESULTADO vía scoring_valores si la
                # pregunta encajaba con el cuestionario de Valores y
                # Competencias) para que la respuesta descalificatoria gane
                # siempre, sin importar el score.
                informes_module.forzar_no_apto(enlace["respuesta_id"])
            else:
                # scoring_valores puede haber calculado "No apto" por su
                # cuenta (cuestionario de Valores y Competencias) sin que
                # ninguna opción estuviera marcada como descalificatoria --
                # también cuenta para decidir qué mensaje mostrar.
                resp_final = informes_module.get_respuesta(enlace["respuesta_id"])
                if resp_final and "No apto" in (json.loads(resp_final["datos_json"]).get("RESULTADO") or ""):
                    es_no_apto = True
            # Si quien acaba de responder ya está en la base de Reclutamiento
            # (creado a mano, por CV, o desde una vacante) pero todavía sin
            # test enlazado, se conecta automáticamente con esta respuesta en
            # vez de quedar como una ficha aparte hasta que alguien la
            # comparta a mano — así el resultado aparece directo en su ficha.
            campos_contacto, _ = reclutamiento_module.mapear_datos_a_candidato(fila_por_etiqueta)
            candidato_id = reclutamiento_module.buscar_candidato_sin_respuesta_por_contacto(
                campos_contacto.get("telefono"), campos_contacto.get("email")
            )
            if candidato_id:
                reclutamiento_module.enlazar_respuesta_a_candidato(candidato_id, enlace["respuesta_id"])
    if row["tipo_entrevista_empresa"]:
        entrevistas_module.ingest_fila_directa(
            row["tipo_entrevista_empresa"], fila_por_etiqueta, origen=f"Test web: {row['titulo']}"
        )
    if row["clima_oleada_id"]:
        # centro_clima ya se validó arriba, antes de insertar. Clima Laboral
        # es completamente anónimo: fila_por_etiqueta se reenvía tal cual
        # (solo el centro y las respuestas de escala/abiertas) igual que si
        # viniera del Excel de Forms -- un test de Clima real no tiene
        # pregunta de nombre/teléfono/email que reenviar. Las preguntas de
        # tipo "likert" sí se traducen de punto (1-5) a texto de leyenda
        # antes de mandarlas (ver LIKERT_TEXTO_POR_PUNTO) -- clima.py espera
        # el texto tal cual trae un Excel de Forms, no el punto crudo. Se
        # identifica la pregunta por id (clave_a_pid), no por su texto, para
        # que dos preguntas de escala con el mismo enunciado (posible si se
        # repite la misma frase en dos páginas) no se confundan entre sí.
        tipo_por_id = {str(p["id"]): p["tipo"] for p in preguntas}
        fila_para_clima = {
            clave: (LIKERT_TEXTO_POR_PUNTO.get(str(valor), valor) if tipo_por_id.get(clave_a_pid[clave]) == "likert" else valor)
            for clave, valor in fila_por_etiqueta.items()
        }
        clima_module.ingest_respuesta_directa(row["clima_oleada_id"], centro_clima, fila_para_clima)

    marcar_sesion_completada(token)
    mostrar_no_apto = es_no_apto and bool(row["usar_mensaje_no_apto"])
    return {"ok": True, "mensaje": row["mensaje_no_apto"] if mostrar_no_apto else row["mensaje_final"]}


def list_respuestas(encuesta_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, datos_json, ip, user_agent, dispositivo, creado_en, "
        "informe_tipo_clave, informe_hoja, informe_respuesta_id FROM encuesta_respuestas "
        "WHERE encuesta_id = ? ORDER BY creado_en DESC",
        (encuesta_id,),
    ).fetchall()
    conn.close()
    resultado = []
    for r in rows:
        d = dict(r)
        d["datos"] = json.loads(d.pop("datos_json"))
        resultado.append(d)
    return resultado


def borrar_respuesta(respuesta_id):
    conn = get_connection()
    conn.execute("DELETE FROM encuesta_respuestas WHERE id = ?", (respuesta_id,))
    conn.commit()
    conn.close()


ensure_encuestas_tables()
