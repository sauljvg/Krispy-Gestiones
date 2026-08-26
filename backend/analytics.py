import datetime
import math
import re
from collections import Counter

import personal as personal_module
from db import get_connection
from request_context import tiendas_permitidas_actual


def _compile_patterns(names_dict):
    return {
        canonical: re.compile(
            r"\b(?:" + "|".join(re.escape(v) for v in variants) + r")\b",
            re.IGNORECASE,
        )
        for canonical, variants in names_dict.items()
    }


def _store_patterns():
    """Cada tienda tiene su propio diccionario de nombres — el mismo nombre
    de pila puede ser gente distinta en tiendas distintas, así que no se
    mezclan. Se reconstruye en cada llamada desde personal.py (tabla
    editable desde el dashboard) en vez de cachearse: la tabla es pequeña y
    así una alta/salida de personal se refleja sin reiniciar el servidor."""
    return {
        tienda: {
            "current": _compile_patterns(data["current"]),
            "former": _compile_patterns(data["former"]),
            "all": _compile_patterns({**data["current"], **data["former"]}),
        }
        for tienda, data in personal_module.build_store_staff().items()
    }

STOPWORDS = {
    "que", "de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "es",
    "por", "con", "para", "muy", "no", "se", "lo", "su", "sus", "del", "al",
    "más", "pero", "como", "todo", "todos", "toda", "todas", "esta", "este",
    "estos", "estas", "ese", "esa", "eso", "fue", "ha", "he", "han", "hemos",
    "nos", "me", "mi", "mis", "te", "tu", "tus", "les", "le", "sin", "sobre",
    "ya", "o", "u", "e", "son", "eran", "era", "hay", "también", "tambien",
    "porque", "cuando", "donde", "aunque", "así", "asi", "solo", "sólo",
    "aquí", "aqui", "allí", "alli", "ahora", "siempre", "nunca", "nada",
    "algo", "alguna", "algunos", "algunas", "cada", "otro", "otra", "otros",
    "otras", "mismo", "misma", "tan", "tanto", "vez", "veces", "hace",
    "desde", "hasta", "entre", "sido", "está", "esta", "están", "estan",
    "estar", "estaba", "estaban", "puedes", "puede", "pueden", "podemos",
    "había", "habia", "habían", "habian", "bien", "mal", "si", "sí", "no",
    "les", "cual", "quien", "quienes", "cómo", "qué", "cuál", "dónde",
    "krispy", "kreme", "donuts", "donut", "sitio", "local",
}


def _combine_where(base_clause, where, params):
    """Combina una condición fija (p.ej. 'fecha_datetime IS NOT NULL') con el
    WHERE de filtros que llega desde la API (puede venir vacío)."""
    extra = where[len("WHERE "):] if where.startswith("WHERE ") else ""
    clauses = [c for c in [base_clause, extra] if c]
    sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return sql, params or []


def get_stats(where="", params=None):
    params = params or []
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) AS total, AVG(calificacion_num) AS promedio FROM reviews {where}", params)
    row = cur.fetchone()
    total = row["total"] or 0
    promedio = round(row["promedio"], 2) if row["promedio"] else 0

    cur.execute(f"""
        SELECT calificacion_num AS estrellas, COUNT(*) AS cantidad
        FROM reviews {where} GROUP BY calificacion_num ORDER BY calificacion_num DESC
    """, params)
    distribucion = dict_rows(cur)

    cur.execute(f"SELECT sentiment, COUNT(*) AS cantidad FROM reviews {where} GROUP BY sentiment", params)
    sentimiento = {r["sentiment"]: r["cantidad"] for r in cur.fetchall()}

    recientes_where, recientes_params = _combine_where("es_reciente = 1", where, params)
    cur.execute(f"SELECT COUNT(*) AS recientes FROM reviews {recientes_where}", recientes_params)
    recientes = cur.fetchone()["recientes"]

    conn.close()

    positivas = sentimiento.get("positivo", 0)
    return {
        "total": total,
        "promedio_estrellas": promedio,
        "distribucion_estrellas": distribucion,
        "sentimiento": sentimiento,
        "porcentaje_positivas": round(positivas * 100 / total, 1) if total else 0,
        "resenas_recientes": recientes,
    }


def get_distribucion_por_tienda(where="", params=None):
    """Distribución de estrellas (5★..1★) desglosada por tienda — para
    dibujar "Distribución de estrellas" como barras apiladas en la vista
    "Todas" en vez de un único agregado."""
    sql_where, sql_params = _combine_where("tienda IS NOT NULL", where, params)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT tienda, calificacion_num AS estrellas, COUNT(*) AS cantidad
        FROM reviews {sql_where}
        GROUP BY tienda, estrellas
    """, sql_params)
    filas = dict_rows(cur)
    conn.close()

    por_tienda = {}
    for f in filas:
        por_tienda.setdefault(f["tienda"], {})[f["estrellas"]] = f["cantidad"]

    orden_estrellas = [5, 4, 3, 2, 1]
    series = [
        {"tienda": tienda, "datos": [conteos.get(e, 0) for e in orden_estrellas]}
        for tienda, conteos in por_tienda.items()
    ]
    series.sort(key=lambda s: -sum(s["datos"]))
    return {"estrellas": orden_estrellas, "series": series}


def get_timeline(where="", params=None):
    sql_where, sql_params = _combine_where("fecha_datetime IS NOT NULL", where, params)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT fecha_datetime AS dia, COUNT(*) AS cantidad,
               AVG(calificacion_num) AS promedio
        FROM reviews
        {sql_where}
        GROUP BY dia
        ORDER BY dia ASC
    """, sql_params)
    data = dict_rows(cur)
    conn.close()
    return data


def get_timeline_por_tienda(where="", params=None, date_from=None, date_to=None):
    """Como get_timeline pero con una línea ACUMULADA por tienda en vez de
    un único agregado global — para la vista "Todas" del timeline, donde
    interesa ver el crecimiento de cada tienda por separado, no solo el
    volumen total día a día.

    `where`/`params` NO deben traer ya el filtro de fecha (se calcula el
    acumulado sobre el histórico COMPLETO a propósito): si un rango
    Desde/Hasta reseteara el acumulado a 0 en el día de inicio, esta línea
    dejaría de coincidir con la tabla de "cambio" que se muestra debajo
    (esa sí calcula el total real acumulado hasta cada fecha). `date_from`/
    `date_to`, si se pasan, solo recortan qué días se DEVUELVEN — el valor
    acumulado de cada uno sigue siendo el histórico real hasta ese día."""
    sql_where, sql_params = _combine_where("fecha_datetime IS NOT NULL AND tienda IS NOT NULL", where, params)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT tienda, fecha_datetime AS dia, COUNT(*) AS cantidad
        FROM reviews
        {sql_where}
        GROUP BY tienda, dia
        ORDER BY dia ASC
    """, sql_params)
    filas = dict_rows(cur)
    conn.close()

    todos_los_dias = sorted({f["dia"] for f in filas})
    por_tienda = {}
    for f in filas:
        por_tienda.setdefault(f["tienda"], {})[f["dia"]] = f["cantidad"]

    dias_visibles = [
        d for d in todos_los_dias
        if (not date_from or d >= date_from) and (not date_to or d <= date_to)
    ]
    set_dias_visibles = set(dias_visibles)

    series = []
    for tienda, conteos_por_dia in por_tienda.items():
        acumulado = 0
        puntos = []
        for dia in todos_los_dias:
            acumulado += conteos_por_dia.get(dia, 0)
            if dia in set_dias_visibles:
                puntos.append(acumulado)
        series.append({"tienda": tienda, "acumulado": puntos})
    series.sort(key=lambda s: -(s["acumulado"][-1] if s["acumulado"] else 0))
    return {"dias": dias_visibles, "series": series}


def get_keywords(limit=20, where="", params=None):
    params = params or []
    conn = get_connection()
    cur = conn.cursor()
    text_where, text_params = _combine_where("texto IS NOT NULL", where, params)
    cur.execute(f"SELECT texto FROM reviews {text_where}", text_params)
    counter = Counter()
    for row in cur.fetchall():
        palabras = re.findall(r"[a-záéíóúñü]{4,}", row["texto"].lower())
        counter.update(p for p in palabras if p not in STOPWORDS)
    conn.close()
    return [{"palabra": palabra, "frecuencia": freq} for palabra, freq in counter.most_common(limit)]


def _tally_staff(rows, patterns):
    stats = {name: {"menciones": 0, "suma_estrellas": 0, "positivas": 0} for name in patterns}
    for row in rows:
        texto = row["texto"] or ""
        for name, pattern in patterns.items():
            if pattern.search(texto):
                stats[name]["menciones"] += 1
                if row["calificacion_num"] is not None:
                    stats[name]["suma_estrellas"] += row["calificacion_num"]
                if row["sentiment"] == "positivo":
                    stats[name]["positivas"] += 1

    result = []
    for name, s in stats.items():
        if s["menciones"] == 0:
            continue
        result.append({
            "nombre": name,
            "menciones": s["menciones"],
            "promedio_estrellas": round(s["suma_estrellas"] / s["menciones"], 2),
            "porcentaje_positivas": round(s["positivas"] * 100 / s["menciones"], 1),
        })
    result.sort(key=lambda r: r["menciones"], reverse=True)
    return result


def get_staff_mentions(tienda, where="", params=None):
    """Cuenta en cuántas reseñas (distintas) se menciona a cada empleado DE
    ESA TIENDA (el ranking de personal solo tiene sentido por tienda: el
    mismo nombre de pila puede ser una persona distinta en cada local).

    Busca SOLO en el texto de la reseña (nunca en el nombre de quien la
    escribió), por palabra completa y sin distinguir mayúsculas/acentos.
    Devuelve personal actual y personal que ya no trabaja ahí por separado.
    """
    store_patterns = _store_patterns()
    if tienda not in store_patterns:
        return {"actuales": [], "anteriores": []}

    text_where, text_params = _combine_where("texto IS NOT NULL", where, params)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT texto, calificacion_num, sentiment FROM reviews {text_where}", text_params)
    rows = cur.fetchall()
    conn.close()

    patterns = store_patterns[tienda]
    actuales = _tally_staff(rows, patterns["current"])
    anteriores = _tally_staff(rows, patterns["former"])
    for entry in actuales + anteriores:
        entry["tienda"] = tienda
    return {"actuales": actuales, "anteriores": anteriores}


def get_staff_mentions_all_stores(where="", params=None):
    """Como get_staff_mentions pero para TODAS las tiendas a la vez (cuando
    el selector está en "Todas"). Cada nombre se cuenta SOLO dentro de su
    propia tienda — nunca se mezcla "Andrea de ParqueSur" con "Andrea de
    Caleido" — y cada fila del resultado indica de qué tienda es, para que
    el dashboard pueda distinguirlas."""
    params = list(params or [])
    extra = where[len("WHERE "):] if where.startswith("WHERE ") else ""
    actuales, anteriores = [], []
    conn = get_connection()
    cur = conn.cursor()
    store_patterns = _store_patterns()
    permitidas = tiendas_permitidas_actual.get()
    tiendas_a_recorrer = (
        {t: p for t, p in store_patterns.items() if t in permitidas} if permitidas else store_patterns
    )
    for tienda, patterns in tiendas_a_recorrer.items():
        clauses = ["tienda = ?", "texto IS NOT NULL"] + ([extra] if extra else [])
        sql_where = "WHERE " + " AND ".join(clauses)
        cur.execute(f"SELECT texto, calificacion_num, sentiment FROM reviews {sql_where}", [tienda] + params)
        rows = cur.fetchall()
        for entry in _tally_staff(rows, patterns["current"]):
            entry["tienda"] = tienda
            actuales.append(entry)
        for entry in _tally_staff(rows, patterns["former"]):
            entry["tienda"] = tienda
            anteriores.append(entry)
    conn.close()

    actuales.sort(key=lambda r: r["menciones"], reverse=True)
    anteriores.sort(key=lambda r: r["menciones"], reverse=True)
    return {"actuales": actuales, "anteriores": anteriores}


def staff_matching_review_ids(tienda, canonical_name, where="", params=None):
    """IDs de reseñas cuyo TEXTO menciona a `canonical_name` (palabra completa)
    dentro de la plantilla de personal de `tienda`."""
    pattern = _store_patterns().get(tienda, {}).get("all", {}).get(canonical_name)
    if pattern is None:
        return []
    text_where, text_params = _combine_where("texto IS NOT NULL", where, params)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT review_id, texto FROM reviews {text_where}", text_params)
    ids = [row["review_id"] for row in cur.fetchall() if pattern.search(row["texto"] or "")]
    conn.close()
    return ids


def get_rating_progress(where="", params=None):
    """'True rating' (media exacta, sin redondear a 1 decimal como hace
    Google en la ficha pública) + cuántas reseñas de 5★ harían falta para
    subir al siguiente nivel público (tramos de 0.1), al estilo Gastro
    Ranking. También compara contra la media de hace 90 días para mostrar
    tendencia.
    """
    params = list(params or [])
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) AS total, SUM(calificacion_num) AS suma FROM reviews {where}", params)
    row = cur.fetchone()
    total = row["total"] or 0
    suma = row["suma"] or 0

    extra = where[len("WHERE "):] if where.startswith("WHERE ") else ""
    cutoff_clauses = ["fecha_datetime <= ?"] + ([extra] if extra else [])
    cutoff_where = "WHERE " + " AND ".join(cutoff_clauses)
    cutoff = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    cur.execute(f"SELECT COUNT(*) AS total, SUM(calificacion_num) AS suma FROM reviews {cutoff_where}", [cutoff] + params)
    row90 = cur.fetchone()
    total90 = row90["total"] or 0
    suma90 = row90["suma"] or 0

    conn.close()

    if not total:
        return {
            "true_rating": 0, "tier_actual": 0, "tier_siguiente": 0, "progreso_pct": 0,
            "resenas_necesarias": 0, "true_rating_90d": None, "tendencia_90d": None,
        }

    true_rating = round(suma / total, 3)
    true_rating_90d = round(suma90 / total90, 3) if total90 else None

    # Nivel actual = la décima truncada (no redondeada) del true rating, para
    # que el "siguiente nivel" sea siempre el escalón de 0.1 inmediatamente
    # superior — nunca dos escalones arriba porque el valor exacto redondease
    # hacia arriba (p.ej. 4.469 → nivel actual 4.4, siguiente 4.5, no 4.6).
    tier_actual = math.floor(round(true_rating * 10, 6)) / 10
    tier_actual = round(min(tier_actual, 5.0), 1)
    tier_siguiente = round(min(tier_actual + 0.1, 5.0), 1)

    progreso_pct = 100.0
    if tier_siguiente > tier_actual:
        progreso_pct = round((true_rating - tier_actual) / (tier_siguiente - tier_actual) * 100, 1)
        progreso_pct = max(0.0, min(100.0, progreso_pct))

    if tier_siguiente <= tier_actual:
        resenas_necesarias = 0
    else:
        # Llegar a una media de 5.0 EXACTO exigiría infinitas reseñas de 5★
        # (la fórmula de abajo dividiría por "5 - target" = 0). En vez de
        # rendirnos y decir "ya está en el máximo", usamos un objetivo
        # prácticamente-5.0 (4.995) para seguir mostrando un número real de
        # cuántas 5★ seguidas harían falta para acercarse al máximo.
        target = min(tier_siguiente, 4.995)
        if true_rating >= target:
            resenas_necesarias = 0
        else:
            x = (target * total - suma) / (5 - target)
            resenas_necesarias = max(0, math.ceil(x - 1e-9))

    tendencia = round(true_rating - true_rating_90d, 3) if true_rating_90d is not None else None

    return {
        "true_rating": true_rating,
        "tier_actual": tier_actual,
        "tier_siguiente": tier_siguiente,
        "progreso_pct": progreso_pct,
        "resenas_necesarias": resenas_necesarias,
        "true_rating_90d": true_rating_90d,
        "tendencia_90d": tendencia,
    }


DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def get_hourly_distribution(where, params):
    """Reseñas agrupadas por hora del día (0-23, hora de Madrid) y por día
    de la semana, usando fecha_hora. Ese campo solo lo rellena la
    importación de Google Takeout (el scraping de Maps no trae hora exacta),
    así que esto puede cubrir menos reseñas que el total general — se
    informa cuántas sí tienen hora exacta para que quede claro."""
    conn = get_connection()
    clause = where + (" AND" if where else " WHERE") + " fecha_hora IS NOT NULL"

    por_hora_rows = conn.execute(f"""
        SELECT CAST(strftime('%H', fecha_hora) AS INTEGER) AS hora, COUNT(*) AS n
        FROM reviews {clause}
        GROUP BY hora
    """, params).fetchall()
    por_hora_map = {row["hora"]: row["n"] for row in por_hora_rows}
    por_hora = [{"hora": h, "cantidad": por_hora_map.get(h, 0)} for h in range(24)]

    # strftime('%w', ...) en SQLite: 0=domingo..6=sábado. Se reordena para
    # que la semana empiece en lunes, como es habitual en España.
    por_dia_rows = conn.execute(f"""
        SELECT CAST(strftime('%w', fecha_hora) AS INTEGER) AS dow, COUNT(*) AS n
        FROM reviews {clause}
        GROUP BY dow
    """, params).fetchall()
    por_dia_map = {row["dow"]: row["n"] for row in por_dia_rows}
    orden_lunes_primero = [1, 2, 3, 4, 5, 6, 0]
    por_dia_semana = [
        {"dia": DIAS_ES[i], "cantidad": por_dia_map.get(dow, 0)}
        for i, dow in enumerate(orden_lunes_primero)
    ]

    con_hora_exacta = sum(por_hora_map.values())
    conn.close()
    return {
        "por_hora": por_hora,
        "por_dia_semana": por_dia_semana,
        "con_hora_exacta": con_hora_exacta,
    }


def get_hourly_distribution_por_tienda(where, params):
    """Como get_hourly_distribution pero una serie por tienda en vez de un
    único agregado — para dibujar "Horario de reseñas" (por hora y por día
    de la semana) como barras apiladas en la vista "Todas"."""
    conn = get_connection()
    clause = where + (" AND" if where else " WHERE") + " fecha_hora IS NOT NULL AND tienda IS NOT NULL"

    filas_hora = conn.execute(f"""
        SELECT tienda, CAST(strftime('%H', fecha_hora) AS INTEGER) AS hora, COUNT(*) AS n
        FROM reviews {clause}
        GROUP BY tienda, hora
    """, params).fetchall()
    filas_dia = conn.execute(f"""
        SELECT tienda, CAST(strftime('%w', fecha_hora) AS INTEGER) AS dow, COUNT(*) AS n
        FROM reviews {clause}
        GROUP BY tienda, dow
    """, params).fetchall()
    conn.close()

    tiendas = sorted({r["tienda"] for r in filas_hora} | {r["tienda"] for r in filas_dia})

    por_hora_map = {}
    for r in filas_hora:
        por_hora_map.setdefault(r["tienda"], {})[r["hora"]] = r["n"]
    series_hora = [
        {"tienda": t, "datos": [por_hora_map.get(t, {}).get(h, 0) for h in range(24)]}
        for t in tiendas
    ]
    series_hora.sort(key=lambda s: -sum(s["datos"]))

    orden_lunes_primero = [1, 2, 3, 4, 5, 6, 0]
    por_dia_map = {}
    for r in filas_dia:
        por_dia_map.setdefault(r["tienda"], {})[r["dow"]] = r["n"]
    series_dia = [
        {"tienda": t, "datos": [por_dia_map.get(t, {}).get(dow, 0) for dow in orden_lunes_primero]}
        for t in tiendas
    ]
    series_dia.sort(key=lambda s: -sum(s["datos"]))

    return {"por_hora": series_hora, "por_dia_semana": series_dia}


def get_evolucion_por_tienda(date_from, date_to):
    """Para la vista "Todas" con Desde/Hasta puestos: cuántas reseñas y qué
    valoración media tenía cada tienda ACUMULADO hasta cada fecha límite —
    así se ve cuánto creció cada una en ese periodo (al estilo del
    comparativo "22 de mayo vs 26 de julio"), no solo el total agregado que
    ya muestra el timeline por mes.

    Se ignoran a propósito los filtros de estrellas/sentimiento/búsqueda —
    no tienen sentido para un comparativo de crecimiento — pero si respeta
    las tiendas permitidas del usuario.
    """
    conn = get_connection()
    permitidas = tiendas_permitidas_actual.get()
    clause_tienda = ""
    params = []
    if permitidas:
        placeholders = ",".join("?" * len(permitidas))
        clause_tienda = f" AND tienda IN ({placeholders})"
        params = list(permitidas)
    rows = conn.execute(f"""
        SELECT tienda, fecha_datetime, calificacion_num
        FROM reviews
        WHERE tienda IS NOT NULL AND fecha_datetime IS NOT NULL{clause_tienda}
    """, params).fetchall()
    conn.close()

    por_tienda = {}
    for r in rows:
        d = por_tienda.setdefault(r["tienda"], {"inicio": [], "final": []})
        if r["fecha_datetime"] <= date_to:
            d["final"].append(r["calificacion_num"])
        if r["fecha_datetime"] <= date_from:
            d["inicio"].append(r["calificacion_num"])

    def _promedio(calificaciones):
        con_nota = [c for c in calificaciones if c is not None]
        return round(sum(con_nota) / len(con_nota), 2) if con_nota else None

    resultado = []
    for tienda, d in por_tienda.items():
        if not d["final"]:
            continue  # sin ninguna reseña hasta la fecha final, no aporta nada al comparativo
        resultado.append({
            "tienda": tienda,
            "total_inicio": len(d["inicio"]),
            "total_final": len(d["final"]),
            "promedio_inicio": _promedio(d["inicio"]),
            "promedio_final": _promedio(d["final"]),
        })
    resultado.sort(key=lambda r: -r["total_final"])
    return resultado


def get_store_stats(order_by="total", mes=None):
    """Reseñas, promedio y (si se han cargado) transacciones + tasa por
    tienda — para el selector de tienda y el ranking comparativo entre
    locales.

    Sin `mes`: `total` es el acumulado histórico y `transacciones` es la SUMA
    de todos los meses cargados (acumulado contra acumulado).

    Con `mes` (YYYY-MM): tanto `total` como `transacciones` se acotan a ESE
    mes concreto — así el ranking de tiendas refleja el rendimiento de ese
    mes, no el histórico completo, igual que ya hacían las transacciones.

    `tasa` = reseñas / transacciones * 100: mide qué proporción de las
    transacciones terminan en una reseña, así una tienda pequeña con pocas
    reseñas pero también pocas transacciones puede rankear mejor que una
    tienda grande con muchas reseñas pero muchísimas más transacciones.
    """
    conn = get_connection()
    cur = conn.cursor()
    if mes:
        cur.execute(f"""
            SELECT r.tienda AS tienda, COUNT(*) AS total, AVG(r.calificacion_num) AS promedio,
                   t.transacciones AS transacciones
            FROM reviews r
            LEFT JOIN store_transactions t ON t.tienda = r.tienda AND t.mes = ?
            WHERE r.tienda IS NOT NULL AND substr(r.fecha_datetime, 1, 7) = ?
            GROUP BY r.tienda
        """, (mes, mes))
    else:
        cur.execute(f"""
            SELECT r.tienda AS tienda, COUNT(*) AS total, AVG(r.calificacion_num) AS promedio,
                   t.transacciones AS transacciones
            FROM reviews r
            LEFT JOIN (
                SELECT tienda, SUM(transacciones) AS transacciones
                FROM store_transactions
                GROUP BY tienda
            ) t ON t.tienda = r.tienda
            WHERE r.tienda IS NOT NULL
            GROUP BY r.tienda
        """)
    rows = dict_rows(cur)
    conn.close()

    if mes:
        # Si una tienda no tuvo reseñas ESE mes no aparece en la consulta de
        # arriba — la añadimos en 0 para que no desaparezca del ranking.
        vistas = {r["tienda"] for r in rows}
        conn2 = get_connection()
        todas_tiendas = conn2.execute("SELECT DISTINCT tienda FROM reviews WHERE tienda IS NOT NULL").fetchall()
        conn2.close()
        for row in todas_tiendas:
            if row["tienda"] not in vistas:
                rows.append({"tienda": row["tienda"], "total": 0, "promedio": 0, "transacciones": None})

    permitidas = tiendas_permitidas_actual.get()
    if permitidas:
        rows = [r for r in rows if r["tienda"] in permitidas]

    for r in rows:
        r["promedio"] = round(r["promedio"], 2) if r["promedio"] else 0
        r["tasa"] = round(r["total"] * 100 / r["transacciones"], 2) if r["transacciones"] else None

    if order_by == "tasa":
        rows.sort(key=lambda r: (r["tasa"] is None, -(r["tasa"] or 0)))
    else:
        rows.sort(key=lambda r: -r["total"])
    return rows


def get_month_transactions(mes):
    """Transacciones cargadas para un mes concreto (YYYY-MM), por tienda —
    para rellenar los inputs editables del ranking cuando se cambia de mes."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT tienda, transacciones FROM store_transactions WHERE mes = ?", (mes,))
    data = {row["tienda"]: row["transacciones"] for row in cur.fetchall()}
    conn.close()
    return data


def set_store_transactions(tienda, mes, transacciones):
    conn = get_connection()
    conn.execute("""
        INSERT INTO store_transactions (tienda, mes, transacciones, actualizado)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(tienda, mes) DO UPDATE SET
            transacciones=excluded.transacciones, actualizado=excluded.actualizado
    """, (tienda, mes, transacciones))
    conn.commit()
    conn.close()


def bulk_set_store_transactions(rows):
    """`rows`: iterable de (tienda, mes, transacciones)."""
    conn = get_connection()
    conn.executemany("""
        INSERT INTO store_transactions (tienda, mes, transacciones, actualizado)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(tienda, mes) DO UPDATE SET
            transacciones=excluded.transacciones, actualizado=excluded.actualizado
    """, list(rows))
    conn.commit()
    conn.close()


def dict_rows(cursor):
    return [dict(row) for row in cursor.fetchall()]
