"""Planificador de turnos: el gerente arma el horario del día de su centro en
una línea de tiempo horizontal por horas. Bloques de turno (solo horario,
sin puesto) que se arrastran y se estiran por los bordes; el contador de la
izquierda va sumando las horas de la SEMANA (lun-dom) de cada trabajador
contra sus horas de contrato.

- Roster propio (planificador_trabajadores): se puebla desde el Dashboard
  KPIs (kpi_empleados, por codigo_empleado), importando el mismo Excel de
  Odoo ("GO_report"), o a mano. Horas de contrato = % de jornada * 40.
- Proyección por franja horaria (planificador_proyeccion): transacciones y
  venta previstas que mete el gerente. El "personal ideal" de una franja se
  calcula como transacciones_previstas / objetivo_transacciones_hora (config
  por centro), con override manual opcional.
"""
import datetime

from db import get_connection

# Reutilizamos los lectores de Excel, el mapa de centros y las utilidades de
# parseo del Dashboard KPIs -- el Excel de Odoo es exactamente el mismo.
import kpis as kpis_module

HORAS_JORNADA_COMPLETA = 40
APERTURA_DEFECTO_MIN = 8 * 60      # 08:00
CIERRE_DEFECTO_MIN = 25 * 60       # 01:00 del día siguiente (25:00)


def ensure_planificador_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planificador_trabajadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            centro TEXT NOT NULL,
            codigo_empleado TEXT,
            nombre TEXT NOT NULL,
            horas_contrato_semana REAL,
            origen TEXT NOT NULL DEFAULT 'manual',
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planificador_turnos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            centro TEXT NOT NULL,
            trabajador_id INTEGER NOT NULL REFERENCES planificador_trabajadores(id) ON DELETE CASCADE,
            fecha TEXT NOT NULL,
            inicio_min INTEGER NOT NULL,
            duracion_min INTEGER NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'trabajo',
            creado_por TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now')),
            actualizado_en TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planificador_proyeccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            centro TEXT NOT NULL,
            fecha TEXT NOT NULL,
            franja_min INTEGER NOT NULL,
            transacciones_prevista REAL,
            venta_prevista REAL,
            personal_ideal_manual REAL,
            UNIQUE (empresa, centro, fecha, franja_min)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planificador_config (
            empresa TEXT NOT NULL DEFAULT 'kk',
            centro TEXT NOT NULL,
            apertura_min INTEGER NOT NULL DEFAULT 480,
            cierre_min INTEGER NOT NULL DEFAULT 1500,
            objetivo_transacciones_hora REAL,
            PRIMARY KEY (empresa, centro)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plan_turnos_busqueda ON planificador_turnos (empresa, centro, fecha)")
    cols_turnos = {r[1] for r in conn.execute("PRAGMA table_info(planificador_turnos)")}
    if "tipo" not in cols_turnos:
        conn.execute("ALTER TABLE planificador_turnos ADD COLUMN tipo TEXT NOT NULL DEFAULT 'trabajo'")
    # Todo el mundo tiene contrato: quien se quedó sin horas (sin % de jornada
    # en el Excel) pasa a jornada completa. Idempotente.
    conn.execute(
        "UPDATE planificador_trabajadores SET horas_contrato_semana = ? WHERE horas_contrato_semana IS NULL",
        (HORAS_JORNADA_COMPLETA,),
    )
    # Nombres "APELLIDOS, NOMBRE" (formato del Excel) -> "NOMBRE APELLIDOS".
    # Idempotente: tras darle la vuelta ya no queda ", ".
    for row in conn.execute("SELECT id, nombre FROM planificador_trabajadores WHERE nombre LIKE '%, %'").fetchall():
        conn.execute(
            "UPDATE planificador_trabajadores SET nombre = ? WHERE id = ?",
            (_nombre_directo(row["nombre"]), row["id"]),
        )
    # Limpieza: si antes del filtro de puestos entró en la plantilla algún
    # mando de área (Area Coach...), se saca cruzando por codigo_empleado con
    # kpi_empleados. Idempotente.
    for row in conn.execute(
        "SELECT pt.id AS id, ke.puesto AS puesto FROM planificador_trabajadores pt "
        "JOIN kpi_empleados ke ON ke.codigo_empleado = pt.codigo_empleado "
        "WHERE pt.codigo_empleado IS NOT NULL AND pt.codigo_empleado != ''"
    ).fetchall():
        if _puesto_no_operativo(row["puesto"]):
            conn.execute("DELETE FROM planificador_turnos WHERE trabajador_id = ?", (row["id"],))
            conn.execute("DELETE FROM planificador_trabajadores WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()


# Puestos que aparecen asignados a un centro en el Excel pero NO se
# planifican ahí (mando de área / dirección) -- p.ej. un "Area Coach" que
# figura en una tienda concreta. Coincidencia por subcadena, sin distinguir
# mayúsculas. "Gerente de Tienda/Producción", "SubGerente", "Formador",
# "JefeTurno"... SÍ son de tienda/fábrica y se quedan.
_PUESTOS_NO_OPERATIVOS = ("area coach", "area manager", "director")


def _puesto_no_operativo(puesto):
    p = (puesto or "").strip().lower()
    return any(x in p for x in _PUESTOS_NO_OPERATIVOS)


def _nombre_directo(nombre):
    """El Excel trae "APELLIDO1 APELLIDO2, NOMBRE"; se muestra "NOMBRE
    APELLIDO1 APELLIDO2". Si no hay coma se deja tal cual (alta manual)."""
    nombre = (nombre or "").strip()
    if ", " in nombre:
        apellidos, pila = nombre.split(", ", 1)
        return f"{pila.strip()} {apellidos.strip()}".strip()
    return nombre


def _horas_contrato(pct):
    # Sin "Porcentaje Jornada" en el Excel se asume jornada completa (40 h),
    # mismo criterio que el Dashboard KPIs -- todo el mundo tiene contrato.
    if pct is None:
        return HORAS_JORNADA_COMPLETA
    h = round(pct / 100 * HORAS_JORNADA_COMPLETA, 1)
    return int(h) if h == int(h) else h


# --- Centros ---

def centros_disponibles(empresa):
    """Centros para los que se puede planificar. En KK salen de kpi_empleados
    (misma fuente que el roster); en Saona, de lo que ya se haya dado de alta
    en el propio planificador (kpi_empleados es solo KK). En ambos casos se
    añaden los centros dados de alta a mano que no estén ya en la lista."""
    conn = get_connection()
    centros = set()
    if empresa != "saona":
        rows = conn.execute(
            "SELECT DISTINCT centro FROM kpi_empleados WHERE centro IS NOT NULL AND centro != ''"
        ).fetchall()
        for r in rows:
            if r["centro"] not in kpis_module.CENTROS_EXCLUIDOS:
                centros.add(r["centro"])
    rows = conn.execute(
        "SELECT DISTINCT centro FROM planificador_trabajadores WHERE empresa = ? AND centro IS NOT NULL AND centro != ''",
        (empresa,),
    ).fetchall()
    for r in rows:
        centros.add(r["centro"])
    conn.close()
    return sorted(centros)


# --- Config del centro ---

def get_config(empresa, centro):
    conn = get_connection()
    row = conn.execute(
        "SELECT apertura_min, cierre_min, objetivo_transacciones_hora FROM planificador_config WHERE empresa = ? AND centro = ?",
        (empresa, centro),
    ).fetchone()
    conn.close()
    if row is None:
        return {
            "apertura_min": APERTURA_DEFECTO_MIN,
            "cierre_min": CIERRE_DEFECTO_MIN,
            "objetivo_transacciones_hora": None,
        }
    return dict(row)


def set_config(empresa, centro, apertura_min, cierre_min, objetivo_transacciones_hora):
    if cierre_min <= apertura_min:
        raise ValueError("La hora de cierre debe ser posterior a la de apertura")
    conn = get_connection()
    conn.execute("""
        INSERT INTO planificador_config (empresa, centro, apertura_min, cierre_min, objetivo_transacciones_hora)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (empresa, centro) DO UPDATE SET
            apertura_min = excluded.apertura_min,
            cierre_min = excluded.cierre_min,
            objetivo_transacciones_hora = excluded.objetivo_transacciones_hora
    """, (empresa, centro, apertura_min, cierre_min, objetivo_transacciones_hora))
    conn.commit()
    conn.close()


# --- Roster ---

def list_trabajadores(empresa, centro, incluir_inactivos=False):
    conn = get_connection()
    sql = "SELECT * FROM planificador_trabajadores WHERE empresa = ? AND centro = ?"
    params = [empresa, centro]
    if not incluir_inactivos:
        sql += " AND activo = 1"
    sql += " ORDER BY nombre COLLATE NOCASE"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cargar_desde_kpis(empresa, centro):
    """Trae los empleados activos de ese centro desde kpi_empleados (solo KK).
    Upsert por codigo_empleado: crea los que faltan, actualiza nombre de los
    que ya están y reactiva los inactivos. No pisa las horas de contrato si el
    gerente ya las editó (COALESCE), ni toca a los de alta manual."""
    if empresa != "kk":
        return {"creados": 0, "actualizados": 0}
    conn = get_connection()
    empleados = conn.execute(
        "SELECT codigo_empleado, nombre, porcentaje_jornada, puesto FROM kpi_empleados "
        "WHERE centro = ? AND (fecha_baja IS NULL OR fecha_baja = '')",
        (centro,),
    ).fetchall()
    creados = actualizados = 0
    for e in empleados:
        if _puesto_no_operativo(e["puesto"]):
            continue
        cod = str(e["codigo_empleado"]).strip()
        nombre = _nombre_directo(e["nombre"])
        horas = _horas_contrato(e["porcentaje_jornada"])
        existente = conn.execute(
            "SELECT id FROM planificador_trabajadores WHERE empresa = 'kk' AND centro = ? AND codigo_empleado = ?",
            (centro, cod),
        ).fetchone()
        if existente:
            conn.execute(
                "UPDATE planificador_trabajadores SET nombre = ?, "
                "horas_contrato_semana = COALESCE(horas_contrato_semana, ?), activo = 1 WHERE id = ?",
                (nombre, horas, existente["id"]),
            )
            actualizados += 1
        else:
            conn.execute(
                "INSERT INTO planificador_trabajadores "
                "(empresa, centro, codigo_empleado, nombre, horas_contrato_semana, origen) "
                "VALUES ('kk', ?, ?, ?, ?, 'kpis')",
                (centro, cod, nombre, horas),
            )
            creados += 1
    conn.commit()
    conn.close()
    return {"creados": creados, "actualizados": actualizados}


def importar_odoo_excel(empresa, contenido, nombre_archivo):
    """El mismo Excel que el Dashboard KPIs (GO_report). Da de alta / actualiza
    en el roster a los empleados activos, cada uno en su centro. Solo KK (el
    Excel de Odoo es de GO)."""
    es_xls = nombre_archivo.lower().endswith(".xls") and not nombre_archivo.lower().endswith(".xlsx")
    try:
        filas = kpis_module._leer_filas_xls(contenido) if es_xls else kpis_module._leer_filas_xlsx(contenido)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo Excel: {exc}")
    if not filas:
        raise ValueError("El archivo está vacío")
    encabezado = [kpis_module._normaliza(str(c)) for c in filas[0]]
    indice = {}
    for i, col in enumerate(encabezado):
        clave = kpis_module._ALIAS_COLUMNAS.get(col)
        if clave:
            indice[clave] = i
    faltan = [c for c in ("centro", "codigo_empleado", "nombre") if c not in indice]
    if faltan:
        raise ValueError(f"Faltan columnas obligatorias en el Excel: {', '.join(faltan)}")

    conn = get_connection()
    creados = actualizados = 0
    for fila in filas[1:]:
        def val(clave):
            i = indice.get(clave)
            return fila[i] if i is not None and i < len(fila) else None

        cod = kpis_module._codigo_empleado(val("codigo_empleado"))
        nombre = _nombre_directo(kpis_module._texto(val("nombre")))
        centro = kpis_module._centro_normalizado(val("centro"))
        baja = kpis_module._fecha_a_iso(val("fecha_baja"))
        if (
            not cod or not nombre or not centro
            or centro in kpis_module.CENTROS_EXCLUIDOS or baja
            or _puesto_no_operativo(kpis_module._texto(val("puesto")))
        ):
            continue
        horas = _horas_contrato(kpis_module._numero(val("porcentaje_jornada")))
        existente = conn.execute(
            "SELECT id FROM planificador_trabajadores WHERE empresa = 'kk' AND codigo_empleado = ?",
            (cod,),
        ).fetchone()
        if existente:
            conn.execute(
                "UPDATE planificador_trabajadores SET nombre = ?, centro = ?, "
                "horas_contrato_semana = COALESCE(horas_contrato_semana, ?), activo = 1 WHERE id = ?",
                (nombre, centro, horas, existente["id"]),
            )
            actualizados += 1
        else:
            conn.execute(
                "INSERT INTO planificador_trabajadores "
                "(empresa, centro, codigo_empleado, nombre, horas_contrato_semana, origen) "
                "VALUES ('kk', ?, ?, ?, ?, 'odoo')",
                (centro, cod, nombre, horas),
            )
            creados += 1
    conn.commit()
    conn.close()
    return {"creados": creados, "actualizados": actualizados}


def crear_trabajador_manual(empresa, centro, nombre, horas_contrato_semana):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre")
    if horas_contrato_semana is None:
        horas_contrato_semana = HORAS_JORNADA_COMPLETA
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO planificador_trabajadores (empresa, centro, nombre, horas_contrato_semana, origen) "
        "VALUES (?, ?, ?, ?, 'manual')",
        (empresa, centro, nombre, horas_contrato_semana),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def actualizar_trabajador(trabajador_id, nombre=None, horas_contrato_semana=None, activo=None):
    sets, params = [], []
    if nombre is not None:
        sets.append("nombre = ?")
        params.append(nombre.strip())
    if horas_contrato_semana is not None:
        sets.append("horas_contrato_semana = ?")
        params.append(horas_contrato_semana)
    if activo is not None:
        sets.append("activo = ?")
        params.append(1 if activo else 0)
    if not sets:
        return
    params.append(trabajador_id)
    conn = get_connection()
    conn.execute(f"UPDATE planificador_trabajadores SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def eliminar_trabajador(trabajador_id):
    conn = get_connection()
    conn.execute("DELETE FROM planificador_turnos WHERE trabajador_id = ?", (trabajador_id,))
    conn.execute("DELETE FROM planificador_trabajadores WHERE id = ?", (trabajador_id,))
    conn.commit()
    conn.close()


def get_trabajador(trabajador_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM planificador_trabajadores WHERE id = ?", (trabajador_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Turnos ---

def _lunes_de(fecha_iso):
    d = datetime.date.fromisoformat(fecha_iso)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def turnos_semana(empresa, centro, fecha_iso):
    lunes = _lunes_de(fecha_iso)
    domingo = (datetime.date.fromisoformat(lunes) + datetime.timedelta(days=6)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM planificador_turnos WHERE empresa = ? AND centro = ? AND fecha BETWEEN ? AND ? "
        "ORDER BY inicio_min",
        (empresa, centro, lunes, domingo),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_turno(turno_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM planificador_turnos WHERE id = ?", (turno_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _solapa(conn, trabajador_id, fecha, ini, fin, excluir_id=None):
    """¿Hay ya un turno de trabajo de esta persona ese día que se PISE con
    [ini, fin)? Tocarse (fin == ini del otro) NO cuenta como solape."""
    q = (
        "SELECT id FROM planificador_turnos WHERE trabajador_id = ? AND fecha = ? AND tipo = 'trabajo' "
        "AND inicio_min < ? AND (inicio_min + duracion_min) > ?"
    )
    params = [trabajador_id, fecha, fin, ini]
    if excluir_id is not None:
        q += " AND id != ?"
        params.append(excluir_id)
    return conn.execute(q, params).fetchone() is not None


def crear_turno(empresa, centro, trabajador_id, fecha, inicio_min, duracion_min, creado_por, tipo="trabajo"):
    conn = get_connection()
    if tipo == "libre":
        # Solo un "día libre" por persona y fecha -- si ya hay uno, no se duplica.
        ya = conn.execute(
            "SELECT id FROM planificador_turnos WHERE empresa = ? AND centro = ? AND trabajador_id = ? "
            "AND fecha = ? AND tipo = 'libre'",
            (empresa, centro, trabajador_id, fecha),
        ).fetchone()
        if ya:
            conn.close()
            return ya["id"]
    elif _solapa(conn, trabajador_id, fecha, int(inicio_min), int(inicio_min) + int(duracion_min)):
        conn.close()
        raise ValueError("El turno se solapa con otro de esa persona")
    cur = conn.execute(
        "INSERT INTO planificador_turnos "
        "(empresa, centro, trabajador_id, fecha, inicio_min, duracion_min, tipo, creado_por) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (empresa, centro, trabajador_id, fecha, int(inicio_min), int(duracion_min), tipo, creado_por),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def actualizar_turno(turno_id, inicio_min=None, duracion_min=None):
    if inicio_min is None and duracion_min is None:
        return
    conn = get_connection()
    row = conn.execute("SELECT * FROM planificador_turnos WHERE id = ?", (turno_id,)).fetchone()
    if row is None:
        conn.close()
        return
    row = dict(row)
    ini = int(inicio_min) if inicio_min is not None else row["inicio_min"]
    dur = int(duracion_min) if duracion_min is not None else row["duracion_min"]
    if row["tipo"] == "trabajo" and _solapa(conn, row["trabajador_id"], row["fecha"], ini, ini + dur, excluir_id=turno_id):
        conn.close()
        raise ValueError("El turno se solapa con otro de esa persona")
    conn.execute(
        "UPDATE planificador_turnos SET inicio_min = ?, duracion_min = ?, actualizado_en = datetime('now') WHERE id = ?",
        (ini, dur, turno_id),
    )
    conn.commit()
    conn.close()


def fusionar_turnos(id_a, id_b):
    """Une dos turnos de trabajo (de la misma persona y día) en uno solo que
    va del inicio más temprano al fin más tardío. Sobrevive `id_a`."""
    conn = get_connection()
    a = conn.execute("SELECT * FROM planificador_turnos WHERE id = ?", (id_a,)).fetchone()
    b = conn.execute("SELECT * FROM planificador_turnos WHERE id = ?", (id_b,)).fetchone()
    if a is None or b is None:
        conn.close()
        raise ValueError("Turno no encontrado")
    a, b = dict(a), dict(b)
    mismos = (a["empresa"], a["centro"], a["trabajador_id"], a["fecha"]) == (
        b["empresa"], b["centro"], b["trabajador_id"], b["fecha"]
    )
    if not mismos or a["tipo"] != "trabajo" or b["tipo"] != "trabajo":
        conn.close()
        raise ValueError("Esos turnos no se pueden unir")
    ini = min(a["inicio_min"], b["inicio_min"])
    fin = max(a["inicio_min"] + a["duracion_min"], b["inicio_min"] + b["duracion_min"])
    conn.execute(
        "UPDATE planificador_turnos SET inicio_min = ?, duracion_min = ?, actualizado_en = datetime('now') WHERE id = ?",
        (ini, fin - ini, id_a),
    )
    conn.execute("DELETE FROM planificador_turnos WHERE id = ?", (id_b,))
    conn.commit()
    conn.close()
    return id_a


def eliminar_turno(turno_id):
    conn = get_connection()
    conn.execute("DELETE FROM planificador_turnos WHERE id = ?", (turno_id,))
    conn.commit()
    conn.close()


# --- Proyección ---

_CAMPOS_PROYECCION = ("transacciones_prevista", "venta_prevista", "personal_ideal_manual")


def get_proyeccion(empresa, centro, fecha):
    conn = get_connection()
    rows = conn.execute(
        "SELECT franja_min, transacciones_prevista, venta_prevista, personal_ideal_manual "
        "FROM planificador_proyeccion WHERE empresa = ? AND centro = ? AND fecha = ?",
        (empresa, centro, fecha),
    ).fetchall()
    conn.close()
    return {r["franja_min"]: dict(r) for r in rows}


def set_proyeccion_celda(empresa, centro, fecha, franja_min, campo, valor):
    if campo not in _CAMPOS_PROYECCION:
        raise ValueError("Campo inválido")
    conn = get_connection()
    conn.execute(
        f"INSERT INTO planificador_proyeccion (empresa, centro, fecha, franja_min, {campo}) "
        f"VALUES (?, ?, ?, ?, ?) "
        f"ON CONFLICT (empresa, centro, fecha, franja_min) DO UPDATE SET {campo} = excluded.{campo}",
        (empresa, centro, fecha, int(franja_min), valor),
    )
    conn.commit()
    conn.close()


# --- Vista de un día (todo junto) ---

def _minutos_semana(turnos_sem):
    """Suma de minutos de trabajo por trabajador -- los bloques 'libre' (días
    libres) NO cuentan como horas trabajadas."""
    out = {}
    for t in turnos_sem:
        if t.get("tipo") == "libre":
            continue
        out[t["trabajador_id"]] = out.get(t["trabajador_id"], 0) + t["duracion_min"]
    return out


def dia_completo(empresa, centro, fecha):
    turnos_sem = turnos_semana(empresa, centro, fecha)
    return {
        "config": get_config(empresa, centro),
        "trabajadores": list_trabajadores(empresa, centro),
        "turnos": [t for t in turnos_sem if t["fecha"] == fecha],
        "minutos_semana": {str(k): v for k, v in _minutos_semana(turnos_sem).items()},
        "proyeccion": {str(k): v for k, v in get_proyeccion(empresa, centro, fecha).items()},
        "lunes": _lunes_de(fecha),
    }


def semana_completa(empresa, centro, fecha):
    lunes = _lunes_de(fecha)
    dias = [(datetime.date.fromisoformat(lunes) + datetime.timedelta(days=i)).isoformat() for i in range(7)]
    turnos_sem = turnos_semana(empresa, centro, fecha)
    return {
        "config": get_config(empresa, centro),
        "trabajadores": list_trabajadores(empresa, centro),
        "turnos": turnos_sem,
        "minutos_semana": {str(k): v for k, v in _minutos_semana(turnos_sem).items()},
        "lunes": lunes,
        "dias": dias,
    }


ensure_planificador_tables()
