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
import io

from db import get_connection

# Reutilizamos los lectores de Excel, el mapa de centros y las utilidades de
# parseo del Dashboard KPIs -- el Excel de Odoo es exactamente el mismo.
import kpis as kpis_module

HORAS_JORNADA_COMPLETA = 40
APERTURA_DEFECTO_MIN = 8 * 60      # 08:00
CIERRE_DEFECTO_MIN = 25 * 60       # 01:00 del día siguiente (25:00)

SIN_ASIGNAR = 0  # trabajador_id de un turno/slot todavía sin persona
MIN_TURNO_MIN = 60      # un turno de trabajo dura entre 1 h...
MAX_TURNO_MIN = 600     # ...y 10 h
DESCANSO_ENTRE_JORNADAS_MIN = 12 * 60   # 12 h de descanso entre el fin de una jornada y el inicio de la siguiente
_TIPOS_NO_TRABAJO = ("libre", "vacaciones")   # bloques que no cuentan como horas trabajadas

# Convenio de Madrid (art. 16): en turnos de 6 h o más, la pausa del bocadillo
# de 20 min NO computa como trabajo efectivo. En el planificador esos 20 min se
# SUMAN a la presencia (la persona sale 20 min más tarde) pero no a las horas
# que cuentan contra el contrato. Las tiendas de Valencia tendrán otras reglas.
BOCADILLO_MIN = 20
BOCADILLO_DESDE_MIN = 6 * 60

# Horas complementarias (Estatuto de los Trabajadores art. 12): solo para
# contratos a TIEMPO PARCIAL. Sobre las horas de contrato se pueden añadir,
# con acuerdo del trabajador, hasta un +30% (pactadas) y otro +15%
# (voluntarias) -> techo del 145%. Se puede abrir a jornada completa por
# centro (config `complementarias_jornada_completa`).
COMPLEMENTARIAS_TECHO = 1.45
COMPLEMENTARIAS_VOLUNTARIAS_DESDE = 1.30

# "Dirección de trabajo" / "Rol" que espera Odoo (planning.slot) al reimportar.
# Editable por centro en "Horario del centro"; esto es solo el valor de partida.
_DIRECCION_ODOO_DEFECTO = {
    "ParqueSur Tienda": "T-MD02 PQS-Parquesur",
    "ParqueSur Fabrica": "F-MD01 PQS-Parquesur Fábrica",
    "Princesa": "T-MD03 PRC-Princesa",
    "Caleido": "T-MD04 CLD-Caleido",
    "La Gavia": "T-MD05 LGV-La Gavia",
    "Gran Plaza 2": "T-MD06 GPZ-Gran Plaza 2",
    "Plenilunio": "T-MD07 PLE-Plenilunio",
}


def _bocadillo(duracion_min):
    return BOCADILLO_MIN if int(duracion_min or 0) >= BOCADILLO_DESDE_MIN else 0


def _bocadillo_lado(inicio_min, duracion_min, cierre_min):
    """El bocadillo de 20 min de un turno de 6 h+ va al FINAL de la jornada
    (turnos de apertura / mañana) salvo que eso empujaría la presencia más allá
    del cierre de la tienda -- entonces va al PRINCIPIO (turnos de cierre)."""
    if _bocadillo(duracion_min) == 0:
        return ""
    if int(inicio_min) + int(duracion_min) + BOCADILLO_MIN > int(cierre_min):
        return "inicio"
    return "fin"


# Apertura / cierre por centro (min desde 00:00; >1440 = pasada la medianoche).
# De los patrones reales de Odoo. Solo se siembran la 1ª vez; el gerente los
# puede cambiar en "Horario del centro" sin que se vuelvan a pisar.
_CONFIG_SEED_POR_CENTRO = {
    "ParqueSur Tienda": (8 * 60, 23 * 60 + 30),
    "ParqueSur Fabrica": (6 * 60, 31 * 60 + 20),   # cierra 07:20 del día siguiente (turno de noche)
    "Princesa": (7 * 60, 23 * 60 + 30),
    "Caleido": (7 * 60 + 30, 23 * 60 + 30),
    "La Gavia": (8 * 60, 22 * 60 + 30),
    "Gran Plaza 2": (9 * 60 + 30, 23 * 60),
    "Plenilunio": (9 * 60 + 10, 22 * 60 + 30),
}

# Slots "de siempre" por centro. (nombre, inicio_min, duracion_min) donde
# inicio/duracion son de TRABAJO EFECTIVO (sin contar el bocadillo). El lado
# del bocadillo se calcula solo con `_bocadillo_lado`. Sacados de los patrones
# que más se repiten en la planificación real de Odoo (planning.slot).
_SLOTS_SEED_POR_CENTRO = {
    "ParqueSur Tienda": [
        ("Apertura 8h", 8 * 60, 480),
        ("Media mañana 8h", 10 * 60, 480),
        ("Cierre 8h", 15 * 60 + 30, 480),
        ("Cierre 6h", 17 * 60 + 30, 360),
        ("Tarde 5h", 17 * 60 + 30, 300),
        ("Mañana corta 3h", 10 * 60 + 30, 180),
        ("Mañana 5h", 10 * 60 + 30, 300),
        ("Refuerzo tarde 4h30", 18 * 60, 270),
        ("Refuerzo tarde 4h", 18 * 60, 240),
    ],
    "Princesa": [
        ("Apertura 8h", 7 * 60, 480),
        ("Media mañana 8h", 9 * 60, 480),
        ("Cierre 8h", 15 * 60 + 30, 480),
        ("Cierre 7h", 16 * 60 + 30, 420),
        ("Cierre 6h", 17 * 60 + 30, 360),
        ("Media mañana 6h", 10 * 60, 360),
        ("Mañana 4h", 10 * 60, 240),
        ("Tarde 5h", 17 * 60, 300),
    ],
    "Caleido": [
        ("Apertura 8h", 7 * 60 + 30, 480),
        ("Media mañana 8h", 10 * 60, 480),
        ("Mediodía 8h", 13 * 60 + 40, 480),
        ("Tarde 8h", 14 * 60 + 10, 480),
        ("Cierre 8h", 15 * 60 + 30, 480),
        ("Tarde 6h", 15 * 60 + 40, 360),
        ("Mañana 4h", 10 * 60, 240),
        ("Tarde 5h", 17 * 60, 300),
    ],
    "La Gavia": [
        ("Media mañana 8h", 9 * 60 + 30, 480),
        ("Media mañana 7h", 9 * 60 + 30, 420),
        ("Media mañana 6h", 9 * 60 + 30, 360),
        ("Mediodía cierre 8h", 14 * 60 + 30, 480),
        ("Cierre 6h", 16 * 60 + 30, 360),
        ("Mediodía 5h", 13 * 60 + 30, 300),
        ("Tarde 5h", 17 * 60 + 30, 300),
        ("Refuerzo tarde 4h", 18 * 60 + 30, 240),
    ],
    "Gran Plaza 2": [
        ("Apertura 8h", 9 * 60 + 30, 480),
        ("Mediodía 8h", 14 * 60 + 10, 480),
        ("Cierre 7h", 15 * 60 + 10, 420),
        ("Cierre 6h", 16 * 60 + 10, 360),
        ("Tarde 5h", 17 * 60 + 30, 300),
        ("Refuerzo tarde 4h30", 18 * 60, 270),
        ("Mañana 4h", 10 * 60, 240),
    ],
    "Plenilunio": [
        ("Apertura 8h", 9 * 60 + 10, 480),
        ("Mediodía cierre 8h", 14 * 60 + 30, 480),
        ("Cierre 7h", 15 * 60 + 30, 420),
        ("Cierre 6h", 16 * 60 + 30, 360),
        ("Media mañana 6h", 10 * 60, 360),
        ("Mañana 5h", 9 * 60 + 10, 300),
        ("Tarde 5h", 17 * 60 + 30, 300),
        ("Refuerzo tarde 4h", 18 * 60 + 30, 240),
    ],
    "ParqueSur Fabrica": [
        ("Mañana 8h", 7 * 60, 480),
        ("Apertura 8h", 6 * 60, 480),
        ("Tarde 8h", 15 * 60, 480),
        ("Tarde-noche 8h", 15 * 60 + 30, 480),
        ("Noche 8h", 23 * 60, 480),
        ("Mediodía 8h", 10 * 60, 480),
        ("Refuerzo tarde 6h", 17 * 60, 360),
        ("Limpieza mañana 4h", 7 * 60, 240),
        ("Limpieza mediodía 4h", 11 * 60, 240),
        ("Limpieza tarde 4h", 19 * 60, 240),
    ],
}


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planificador_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            nombre TEXT NOT NULL,
            inicio_min INTEGER NOT NULL,
            duracion_min INTEGER NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Los slots pasan a ser POR CENTRO (cada tienda tiene sus patrones). Los
    # que ya había eran los globales auto-sembrados de ParqueSur Tienda con el
    # modelo antiguo -- se descartan y se vuelven a sembrar bien más abajo.
    cols_slots = {r[1] for r in conn.execute("PRAGMA table_info(planificador_slots)")}
    if "centro" not in cols_slots:
        conn.execute("ALTER TABLE planificador_slots ADD COLUMN centro TEXT")
        conn.execute("DELETE FROM planificador_slots WHERE centro IS NULL AND empresa = 'kk'")
    # Siembra por centro: solo si ese centro todavía no tiene slots (no pisa
    # nada que el gerente haya tocado). ParqueSur Tienda ya tenía los suyos.
    for centro, patrones in _SLOTS_SEED_POR_CENTRO.items():
        ya = conn.execute(
            "SELECT COUNT(*) FROM planificador_slots WHERE empresa = 'kk' AND centro = ?", (centro,)
        ).fetchone()[0]
        if ya:
            continue
        for i, (nombre, ini, dur) in enumerate(patrones):
            conn.execute(
                "INSERT INTO planificador_slots (empresa, centro, nombre, inicio_min, duracion_min, orden) "
                "VALUES ('kk', ?, ?, ?, ?, ?)",
                (centro, nombre, ini, dur, i),
            )
    # Apertura / cierre por centro: solo si no hay fila de config todavía.
    for centro, (ap, ci) in _CONFIG_SEED_POR_CENTRO.items():
        conn.execute(
            "INSERT INTO planificador_config (empresa, centro, apertura_min, cierre_min) VALUES ('kk', ?, ?, ?) "
            "ON CONFLICT (empresa, centro) DO NOTHING",
            (centro, ap, ci),
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plan_turnos_busqueda ON planificador_turnos (empresa, centro, fecha)")
    cols_turnos = {r[1] for r in conn.execute("PRAGMA table_info(planificador_turnos)")}
    if "tipo" not in cols_turnos:
        conn.execute("ALTER TABLE planificador_turnos ADD COLUMN tipo TEXT NOT NULL DEFAULT 'trabajo'")
    # Datos para el export a Odoo (planning.slot): "Dirección de trabajo" y "Rol",
    # uno por centro. Se rellenan en "Horario del centro"; ParqueSur precargado.
    cols_config = {r[1] for r in conn.execute("PRAGMA table_info(planificador_config)")}
    if "direccion_odoo" not in cols_config:
        conn.execute("ALTER TABLE planificador_config ADD COLUMN direccion_odoo TEXT")
        for centro, direccion in _DIRECCION_ODOO_DEFECTO.items():
            conn.execute(
                "UPDATE planificador_config SET direccion_odoo = ? WHERE centro = ? AND (direccion_odoo IS NULL OR direccion_odoo = '')",
                (direccion, centro),
            )
    if "rol_odoo" not in cols_config:
        conn.execute("ALTER TABLE planificador_config ADD COLUMN rol_odoo TEXT")
    if "complementarias_jornada_completa" not in cols_config:
        conn.execute(
            "ALTER TABLE planificador_config ADD COLUMN complementarias_jornada_completa INTEGER NOT NULL DEFAULT 0"
        )
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
# figura en una tienda concreta. Misma lista que el Dashboard KPIs.
# "Gerente de Tienda/Producción", "SubGerente", "Formador", "JefeTurno"...
# SÍ son de tienda/fábrica y se quedan.
_puesto_no_operativo = kpis_module.puesto_no_operativo


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


def _admite_complementarias(contrato, jornada_completa_ok=False):
    """¿Se le pueden planificar horas complementarias a esta persona? Solo a
    tiempo parcial, salvo que el centro lo abra a jornada completa."""
    if not contrato:
        return False
    if contrato < HORAS_JORNADA_COMPLETA:
        return True
    return bool(jornada_completa_ok)


def _techo_semana_min(contrato, jornada_completa_ok=False):
    """Tope duro de minutos de trabajo efectivo por semana. Con complementarias
    es el 145 % del contrato; sin ellas no hay tope duro (pasarse solo avisa)."""
    if not _admite_complementarias(contrato, jornada_completa_ok):
        return None
    return int(round(contrato * 60 * COMPLEMENTARIAS_TECHO))


def _minutos_trabajo_semana(conn, empresa, centro, trabajador_id, fecha, excluir_id=None):
    """Minutos de trabajo efectivo ya planificados a una persona en la semana
    (lun-dom) de `fecha`. `excluir_id` deja fuera un turno (el que se está
    moviendo/reasignando)."""
    lunes = _lunes_de(fecha)
    domingo = (datetime.date.fromisoformat(lunes) + datetime.timedelta(days=6)).isoformat()
    q = ("SELECT COALESCE(SUM(duracion_min), 0) FROM planificador_turnos "
         "WHERE empresa = ? AND centro = ? AND trabajador_id = ? AND tipo = 'trabajo' "
         "AND fecha BETWEEN ? AND ?")
    p = [empresa, centro, trabajador_id, lunes, domingo]
    if excluir_id is not None:
        q += " AND id != ?"
        p.append(excluir_id)
    return conn.execute(q, p).fetchone()[0]


def _jornada_completa_ok(conn, empresa, centro):
    row = conn.execute(
        "SELECT complementarias_jornada_completa FROM planificador_config WHERE empresa = ? AND centro = ?",
        (empresa, centro),
    ).fetchone()
    return bool(row[0]) if row else False


def _chequear_techo(conn, empresa, centro, trabajador_id, fecha, nueva_dur, excluir_id=None):
    """Rechaza si planificar `nueva_dur` min a esta persona la dejaría por
    encima del 145 % de su contrato esa semana (tope de complementarias). A
    jornada completa (sin complementarias) no hay tope duro."""
    if trabajador_id == SIN_ASIGNAR:
        return
    w = conn.execute(
        "SELECT horas_contrato_semana FROM planificador_trabajadores WHERE id = ?", (trabajador_id,)
    ).fetchone()
    contrato = w["horas_contrato_semana"] if w else None
    techo = _techo_semana_min(contrato, _jornada_completa_ok(conn, empresa, centro))
    if techo is None:
        return
    total = _minutos_trabajo_semana(conn, empresa, centro, trabajador_id, fecha, excluir_id=excluir_id) + int(nueva_dur)
    if total > techo:
        raise ValueError(
            f"Llegaría a {round(total / 60, 1)} h esta semana y su tope con horas complementarias "
            f"es {round(techo / 60, 1)} h (145 % de su contrato). Recorta el turno o repártelo con otra persona."
        )


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
        "SELECT apertura_min, cierre_min, objetivo_transacciones_hora, direccion_odoo, rol_odoo, "
        "complementarias_jornada_completa "
        "FROM planificador_config WHERE empresa = ? AND centro = ?",
        (empresa, centro),
    ).fetchone()
    conn.close()
    if row is None:
        d = dict(
            apertura_min=APERTURA_DEFECTO_MIN,
            cierre_min=CIERRE_DEFECTO_MIN,
            objetivo_transacciones_hora=None,
            direccion_odoo=None,
            rol_odoo=None,
            complementarias_jornada_completa=0,
        )
    else:
        d = dict(row)
    if not d.get("direccion_odoo"):
        d["direccion_odoo"] = _DIRECCION_ODOO_DEFECTO.get(centro, "")
    if not d.get("rol_odoo"):
        d["rol_odoo"] = "Retail"
    d["complementarias_jornada_completa"] = int(d.get("complementarias_jornada_completa") or 0)
    return d


def set_config(empresa, centro, apertura_min, cierre_min, objetivo_transacciones_hora,
               direccion_odoo=None, rol_odoo=None, complementarias_jornada_completa=False):
    if cierre_min <= apertura_min:
        raise ValueError("La hora de cierre debe ser posterior a la de apertura")
    conn = get_connection()
    conn.execute("""
        INSERT INTO planificador_config
            (empresa, centro, apertura_min, cierre_min, objetivo_transacciones_hora, direccion_odoo, rol_odoo,
             complementarias_jornada_completa)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (empresa, centro) DO UPDATE SET
            apertura_min = excluded.apertura_min,
            cierre_min = excluded.cierre_min,
            objetivo_transacciones_hora = excluded.objetivo_transacciones_hora,
            direccion_odoo = excluded.direccion_odoo,
            rol_odoo = excluded.rol_odoo,
            complementarias_jornada_completa = excluded.complementarias_jornada_completa
    """, (empresa, centro, apertura_min, cierre_min, objetivo_transacciones_hora,
          (direccion_odoo or "").strip() or None, (rol_odoo or "").strip() or None,
          1 if complementarias_jornada_completa else 0))
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
    [ini, fin)? Tocarse (fin == ini del otro) NO cuenta como solape. Los
    turnos sin asignar pueden solaparse entre sí libremente."""
    if trabajador_id == SIN_ASIGNAR:
        return False
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
    if tipo in _TIPOS_NO_TRABAJO:
        # Solo un "día libre"/"vacaciones" por persona y fecha -- no se duplica.
        ya = conn.execute(
            "SELECT id FROM planificador_turnos WHERE empresa = ? AND centro = ? AND trabajador_id = ? "
            "AND fecha = ? AND tipo = ?",
            (empresa, centro, trabajador_id, fecha, tipo),
        ).fetchone()
        if ya:
            conn.close()
            return ya["id"]
    else:
        if not (MIN_TURNO_MIN <= int(duracion_min) <= MAX_TURNO_MIN):
            conn.close()
            raise ValueError("Un turno debe durar entre 1 y 10 horas")
        if _solapa(conn, trabajador_id, fecha, int(inicio_min), int(inicio_min) + int(duracion_min)):
            conn.close()
            raise ValueError("El turno se solapa con otro de esa persona")
        try:
            _chequear_techo(conn, empresa, centro, trabajador_id, fecha, int(duracion_min))
        except ValueError:
            conn.close()
            raise
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
    if row["tipo"] == "trabajo":
        if not (MIN_TURNO_MIN <= dur <= MAX_TURNO_MIN):
            conn.close()
            raise ValueError("Un turno debe durar entre 1 y 10 horas")
        if _solapa(conn, row["trabajador_id"], row["fecha"], ini, ini + dur, excluir_id=turno_id):
            conn.close()
            raise ValueError("El turno se solapa con otro de esa persona")
        try:
            _chequear_techo(conn, row["empresa"], row["centro"], row["trabajador_id"], row["fecha"], dur,
                            excluir_id=turno_id)
        except ValueError:
            conn.close()
            raise
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
    # El turno unido puede ser mayor que la suma de los dos (si había un hueco).
    try:
        _chequear_techo(conn, a["empresa"], a["centro"], a["trabajador_id"], a["fecha"],
                        (fin - ini) - b["duracion_min"], excluir_id=id_a)
    except ValueError:
        conn.close()
        raise
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


def asignar_turno(turno_id, trabajador_id):
    """Pone (o quita, si trabajador_id = 0) una persona a un turno. Comprueba
    que esa persona es de este centro, que no tiene ya un turno a esa hora y
    que no tiene el día libre."""
    trabajador_id = int(trabajador_id or 0)
    conn = get_connection()
    t = conn.execute("SELECT * FROM planificador_turnos WHERE id = ?", (turno_id,)).fetchone()
    if t is None:
        conn.close()
        raise ValueError("Turno no encontrado")
    t = dict(t)
    if trabajador_id != SIN_ASIGNAR:
        w = conn.execute("SELECT id, centro, empresa FROM planificador_trabajadores WHERE id = ?", (trabajador_id,)).fetchone()
        if w is None or w["centro"] != t["centro"] or w["empresa"] != t["empresa"]:
            conn.close()
            raise ValueError("Esa persona no es de este centro")
        fin = t["inicio_min"] + t["duracion_min"]
        solapa = conn.execute(
            "SELECT id FROM planificador_turnos WHERE trabajador_id = ? AND fecha = ? AND tipo = 'trabajo' "
            "AND id != ? AND inicio_min < ? AND (inicio_min + duracion_min) > ?",
            (trabajador_id, t["fecha"], turno_id, fin, t["inicio_min"]),
        ).fetchone()
        if solapa:
            conn.close()
            raise ValueError("Esa persona ya tiene un turno a esa hora")
        libre = conn.execute(
            "SELECT tipo FROM planificador_turnos WHERE trabajador_id = ? AND fecha = ? AND tipo IN ('libre', 'vacaciones')",
            (trabajador_id, t["fecha"]),
        ).fetchone()
        if libre:
            conn.close()
            raise ValueError("Esa persona tiene " + ("vacaciones" if libre["tipo"] == "vacaciones" else "el día libre"))
        try:
            _chequear_techo(conn, t["empresa"], t["centro"], trabajador_id, t["fecha"], t["duracion_min"],
                            excluir_id=turno_id)
        except ValueError:
            conn.close()
            raise
    conn.execute(
        "UPDATE planificador_turnos SET trabajador_id = ?, actualizado_en = datetime('now') WHERE id = ?",
        (trabajador_id, turno_id),
    )
    conn.commit()
    conn.close()


def _rango_fechas(desde, hasta):
    d0 = datetime.date.fromisoformat(desde)
    d1 = datetime.date.fromisoformat(hasta)
    if d1 < d0:
        d0, d1 = d1, d0
    if (d1 - d0).days > 120:
        raise ValueError("El rango de fechas es demasiado largo")
    n = (d1 - d0).days
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n + 1)]


def set_vacaciones(empresa, centro, trabajador_id, desde, hasta, quitar=False):
    """Marca (o quita) vacaciones de una persona en un rango de fechas. Cada
    día es un bloque a jornada completa, como el día libre. No cuenta horas."""
    fechas = _rango_fechas(desde, hasta)
    cfg = get_config(empresa, centro)
    conn = get_connection()
    n = 0
    for f in fechas:
        if quitar:
            cur = conn.execute(
                "DELETE FROM planificador_turnos WHERE empresa = ? AND centro = ? AND trabajador_id = ? "
                "AND fecha = ? AND tipo = 'vacaciones'",
                (empresa, centro, trabajador_id, f),
            )
            n += cur.rowcount
        else:
            ya = conn.execute(
                "SELECT id FROM planificador_turnos WHERE empresa = ? AND centro = ? AND trabajador_id = ? "
                "AND fecha = ? AND tipo = 'vacaciones'",
                (empresa, centro, trabajador_id, f),
            ).fetchone()
            if ya:
                continue
            conn.execute(
                "INSERT INTO planificador_turnos "
                "(empresa, centro, trabajador_id, fecha, inicio_min, duracion_min, tipo, creado_por) "
                "VALUES (?, ?, ?, ?, ?, ?, 'vacaciones', 'planificador')",
                (empresa, centro, trabajador_id, f, cfg["apertura_min"], cfg["cierre_min"] - cfg["apertura_min"]),
            )
            n += 1
    conn.commit()
    conn.close()
    return n


# --- Biblioteca de slots (horarios predefinidos) ---

def list_slots(empresa, centro=None):
    conn = get_connection()
    if centro:
        rows = conn.execute(
            "SELECT * FROM planificador_slots WHERE empresa = ? AND centro = ? ORDER BY orden, inicio_min",
            (empresa, centro),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM planificador_slots WHERE empresa = ? ORDER BY orden, inicio_min", (empresa,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_slot(empresa, centro, nombre, inicio_min, duracion_min):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre del slot")
    if not centro:
        raise ValueError("Falta el centro")
    if not (MIN_TURNO_MIN <= int(duracion_min) <= MAX_TURNO_MIN):
        raise ValueError("Un slot debe durar entre 1 y 10 horas")
    conn = get_connection()
    mx = conn.execute(
        "SELECT COALESCE(MAX(orden), 0) FROM planificador_slots WHERE empresa = ? AND centro = ?", (empresa, centro)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO planificador_slots (empresa, centro, nombre, inicio_min, duracion_min, orden) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (empresa, centro, nombre, int(inicio_min), int(duracion_min), mx + 1),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def actualizar_slot(slot_id, nombre=None, inicio_min=None, duracion_min=None):
    if duracion_min is not None and not (MIN_TURNO_MIN <= int(duracion_min) <= MAX_TURNO_MIN):
        raise ValueError("Un slot debe durar entre 1 y 10 horas")
    sets, params = [], []
    if nombre is not None:
        sets.append("nombre = ?")
        params.append(nombre.strip())
    if inicio_min is not None:
        sets.append("inicio_min = ?")
        params.append(int(inicio_min))
    if duracion_min is not None:
        sets.append("duracion_min = ?")
        params.append(int(duracion_min))
    if not sets:
        return
    params.append(slot_id)
    conn = get_connection()
    conn.execute(f"UPDATE planificador_slots SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def eliminar_slot(slot_id):
    conn = get_connection()
    conn.execute("DELETE FROM planificador_slots WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()


# --- Sugerencias de a quién poner en un slot ---

def _turnos_ventana_por_trab(empresa, centro, fecha):
    """Turnos de trabajo (con persona) del centro en [fecha-1, fecha+1],
    agrupados por trabajador -- para comprobar el descanso de 12 h."""
    d = datetime.date.fromisoformat(fecha)
    ini = (d - datetime.timedelta(days=1)).isoformat()
    fin = (d + datetime.timedelta(days=1)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT trabajador_id, fecha, inicio_min, duracion_min FROM planificador_turnos "
        "WHERE empresa = ? AND centro = ? AND tipo = 'trabajo' AND trabajador_id != 0 AND fecha BETWEEN ? AND ?",
        (empresa, centro, ini, fin),
    ).fetchall()
    conn.close()
    out = {}
    for r in rows:
        out.setdefault(r["trabajador_id"], []).append(dict(r))
    return out


def _presencia(inicio_min, duracion_min, cierre_min):
    """Ventana de presencia real de un turno: el trabajo efectivo más los
    20 min de bocadillo, que van al final o al principio según la jornada."""
    lado = _bocadillo_lado(inicio_min, duracion_min, cierre_min)
    ini = inicio_min - (BOCADILLO_MIN if lado == "inicio" else 0)
    fin = inicio_min + duracion_min + (BOCADILLO_MIN if lado == "fin" else 0)
    return ini, fin


def _descanso_12h_ko(turnos_persona, fecha, ini, fin, cierre_min):
    """¿Poner [ini, fin) en `fecha` deja menos de 12 h entre esa jornada y una
    adyacente (mismo día -- turno partido lejano no --, día anterior o
    siguiente)? Se mide sobre la PRESENCIA real (con el bocadillo). Los
    solapes los pilla otro chequeo."""
    d = datetime.date.fromisoformat(fecha)
    _, fin = _presencia(ini, fin - ini, cierre_min)
    for t in turnos_persona:
        off = (datetime.date.fromisoformat(t["fecha"]) - d).days * 1440
        tini_p, tfin_p = _presencia(t["inicio_min"], t["duracion_min"], cierre_min)
        tini = tini_p + off
        tfin = tfin_p + off
        if tini >= fin and tini - fin < DESCANSO_ENTRE_JORNADAS_MIN:
            return True
        if ini >= tfin and ini - tfin < DESCANSO_ENTRE_JORNADAS_MIN:
            return True
    return False


def sugerencias(empresa, centro, fecha, inicio_min, duracion_min):
    """Para un hueco [inicio, inicio+duracion) de un día concreto, devuelve la
    plantilla del centro ordenada: primero quien está DISPONIBLE (sin turno
    solapado, día libre ni vacaciones ese día), de menos a más horas ya
    planificadas en la semana; después el resto (en gris) con el motivo. Cada
    persona lleva avisos: se pasaría de contrato, o menos de 12 h de descanso
    entre jornadas."""
    ini, fin = int(inicio_min), int(inicio_min) + int(duracion_min)
    trabajadores = list_trabajadores(empresa, centro)
    turnos_sem = turnos_semana(empresa, centro, fecha)
    min_sem = _minutos_semana(turnos_sem)
    del_dia = [t for t in turnos_sem if t["fecha"] == fecha]
    ventana = _turnos_ventana_por_trab(empresa, centro, fecha)
    cfg = get_config(empresa, centro)
    jc_ok = cfg.get("complementarias_jornada_completa")
    cierre_min = cfg.get("cierre_min", CIERRE_DEFECTO_MIN)
    out = []
    for w in trabajadores:
        wid = w["id"]
        ocupado = any(
            t["trabajador_id"] == wid and t["tipo"] == "trabajo"
            and t["inicio_min"] < fin and t["inicio_min"] + t["duracion_min"] > ini
            for t in del_dia
        )
        fuera = next(
            (t["tipo"] for t in del_dia if t["trabajador_id"] == wid and t["tipo"] in _TIPOS_NO_TRABAJO), None
        )
        ms = min_sem.get(wid, 0)
        contrato = w["horas_contrato_semana"]
        proyectado = ms + int(duracion_min)
        admite = _admite_complementarias(contrato, jc_ok)
        techo = _techo_semana_min(contrato, jc_ok)
        supera_techo = techo is not None and proyectado > techo
        complementaria = ""
        avisos = []
        if contrato and proyectado / 60 > contrato:
            if not admite:
                avisos.append("se pasaría de contrato")
            elif proyectado / 60 > contrato * COMPLEMENTARIAS_VOLUNTARIAS_DESDE:
                complementaria = "voluntaria"
                avisos.append("horas complementarias voluntarias")
            else:
                complementaria = "pactada"
                avisos.append("horas complementarias")
        if _descanso_12h_ko(ventana.get(wid, []), fecha, ini, fin, cierre_min):
            avisos.append("No cumple el descanso mínimo de 12 h entre jornadas")
        if ocupado:
            motivo = "ya trabaja ese día"
        elif fuera == "vacaciones":
            motivo = "vacaciones"
        elif fuera:
            motivo = "día libre"
        elif supera_techo:
            motivo = "supera el 145 % de su contrato"
        else:
            motivo = ""
        out.append({
            "trabajador_id": wid,
            "nombre": w["nombre"],
            "minutos_semana": ms,
            "horas_contrato": contrato,
            "disponible": not ocupado and not fuera and not supera_techo,
            "motivo": motivo,
            "aviso": " · ".join(avisos),
            "complementaria": complementaria,
            "supera_techo": supera_techo,
        })
    out.sort(key=lambda x: (not x["disponible"], bool(x["aviso"]), x["minutos_semana"], x["nombre"].lower()))
    return out


# --- Export a Odoo (planning.slot) ---

def exportar_odoo_xlsx(empresa, centro, desde, hasta):
    """Genera un .xlsx con el mismo formato que exporta Odoo (planning.slot),
    para poder reimportarlo allí: una fila por turno de trabajo con persona
    en el rango [desde, hasta]. Columnas: Descanso, Dirección de trabajo,
    Fecha de inicio, Recurso, Rol, Tiempo asignado, Color, Color del recurso.
    'Tiempo asignado' son las horas efectivas; 'Descanso' = 20 min (0,333 h)
    en turnos de 6 h o más (bocadillo)."""
    from openpyxl import Workbook

    fechas = _rango_fechas(desde, hasta)
    cfg = get_config(empresa, centro)
    direccion = (cfg.get("direccion_odoo") or "").strip()
    rol = (cfg.get("rol_odoo") or "Retail").strip() or "Retail"
    cierre_min = cfg.get("cierre_min", CIERRE_DEFECTO_MIN)
    trabajadores = {w["id"]: w for w in list_trabajadores(empresa, centro, incluir_inactivos=True)}
    conn = get_connection()
    rows = conn.execute(
        "SELECT trabajador_id, fecha, inicio_min, duracion_min FROM planificador_turnos "
        "WHERE empresa = ? AND centro = ? AND tipo = 'trabajo' AND trabajador_id != 0 "
        "AND fecha BETWEEN ? AND ? ORDER BY fecha, inicio_min",
        (empresa, centro, fechas[0], fechas[-1]),
    ).fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "planning.slot"
    ws.append([
        "Descanso", "Dirección de trabajo", "Fecha de inicio", "Recurso",
        "Rol", "Tiempo asignado", "Color", "Color del recurso",
    ])
    for r in rows:
        w = trabajadores.get(r["trabajador_id"])
        if not w:
            continue
        dur = int(r["duracion_min"])
        descanso = round(_bocadillo(dur) / 60, 10)
        # "Fecha de inicio" en Odoo es el inicio de PRESENCIA -- si el bocadillo
        # va al principio (turno de cierre), empieza 20 min antes del trabajo.
        pres_ini, _ = _presencia(int(r["inicio_min"]), dur, cierre_min)
        d = datetime.date.fromisoformat(r["fecha"])
        ini = datetime.datetime(d.year, d.month, d.day) + datetime.timedelta(minutes=pres_ini)
        ws.append([
            descanso,
            direccion,
            ini,
            (w["nombre"] or "").upper(),
            rol,
            round(dur / 60, 6),
            1,
            1,
        ])
    for cell in ws["C"][1:]:
        cell.number_format = "YYYY-MM-DD HH:MM:SS"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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

def _es_trabajo(t):
    return t.get("tipo", "trabajo") == "trabajo" and t["trabajador_id"] != SIN_ASIGNAR


def _minutos_semana(turnos_sem):
    """Suma de minutos de trabajo por trabajador -- días libres, vacaciones y
    turnos sin asignar NO cuentan como horas trabajadas."""
    out = {}
    for t in turnos_sem:
        if not _es_trabajo(t):
            continue
        out[t["trabajador_id"]] = out.get(t["trabajador_id"], 0) + t["duracion_min"]
    return out


def _dias_trabajados_semana(turnos_sem):
    """Nº de días distintos de la semana en que cada trabajador tiene algún
    turno de trabajo -- para avisar si le quedan menos de 2 días de descanso."""
    dias = {}
    for t in turnos_sem:
        if not _es_trabajo(t):
            continue
        dias.setdefault(t["trabajador_id"], set()).add(t["fecha"])
    return {str(k): len(v) for k, v in dias.items()}


def dia_completo(empresa, centro, fecha):
    turnos_sem = turnos_semana(empresa, centro, fecha)
    return {
        "config": get_config(empresa, centro),
        "trabajadores": list_trabajadores(empresa, centro),
        "turnos": [t for t in turnos_sem if t["fecha"] == fecha],
        "minutos_semana": {str(k): v for k, v in _minutos_semana(turnos_sem).items()},
        "dias_trabajados": _dias_trabajados_semana(turnos_sem),
        "proyeccion": {str(k): v for k, v in get_proyeccion(empresa, centro, fecha).items()},
        "slots": list_slots(empresa, centro),
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
        "dias_trabajados": _dias_trabajados_semana(turnos_sem),
        "slots": list_slots(empresa, centro),
        "lunes": lunes,
        "dias": dias,
    }


ensure_planificador_tables()
