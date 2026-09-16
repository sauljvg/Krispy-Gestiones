"""Dashboard de KPIs de personal -- dos fuentes de datos distintas, a
propósito (pedido explícito del usuario):

1. Plantilla ACTIVA y horas contratadas: el informe que exporta GO
   (importación puntual, ver import_excel/kpi_empleados) -- es una foto de
   "quién está en nómina ahora mismo", no cambia sola.
2. Bajas (para rotación mensual/anual y % NSPP): la tabla EN VIVO de
   Entrevista de Salida (entrevistas_salidas), que crece cada vez que RRHH
   da de alta una salida ahí -- así el dashboard se mantiene al día solo,
   sin depender de reimportar el Excel cada vez que se va alguien.

3. Movimientos internos (kpi_movimientos): traslados de centro y
   promociones de puesto, registrados a mano por código de empleado con
   fecha -- de aquí sale el % de promoción interna real, y también se usan
   para reconstruir con más precisión en qué centro estaba alguien en un
   mes pasado (si esa persona tiene movimientos registrados; si no, se
   sigue asumiendo su centro actual, la misma aproximación de siempre)."""
import calendar
import datetime
import io
import re

import xlrd
from openpyxl import load_workbook

from db import get_connection

# Los dos sistemas nombran los mismos centros de forma distinta (el Excel de
# GO trae "GO - TIENDA CALEIDO", Entrevista de Salida usa "Caleido") --
# normalizamos el nombre de GO a la forma corta al importar, para poder
# cruzar plantilla (Excel) con bajas (Entrevista de Salida) por el mismo
# nombre de centro. Confirmado 1 a 1 contra los centros reales en producción.
CENTROS_GO_A_CORTO = {
    "GO - FABRICA PARQUE SUR": "ParqueSur Fabrica",
    "GO - TIENDA PARQUE SUR": "ParqueSur Tienda",
    "GO - ADMIN CENTRAL": "Oficina Central",
    "GO - TIENDA LA GAVIA": "La Gavia",
    "GO - TIENDA PLENILUNIO": "Plenilunio",
    "GO - TIENDA PRINCESA": "Princesa",
    "GO - TIENDA CALEIDO": "Caleido",
    "GO - TIENDA GRANPLAZA2": "Gran Plaza 2",
}

# Export de Odoo (credenciales) para la plantilla activa/bajas (16/09,
# pedido explícito del usuario para poder subirlo directo en vez del Excel
# de GO) -- la columna "Compañía" trae el centro real con un prefijo de
# código de Odoo delante ("T-MD07 PLE-Plenilunio"), o el nombre genérico de
# la empresa ("Glaseados Originales S.L.") para quien trabaja en oficina.
ODOO_COMPANIA_A_CENTRO = {
    "F-MD01 PQS-Parquesur Fábrica": "ParqueSur Fabrica",
    "T-MD02 PQS-Parquesur": "ParqueSur Tienda",
    "T-MD03 PRC-Princesa": "Princesa",
    "T-MD04 CLD-Caleido": "Caleido",
    "T-MD05 LGV-La Gavia": "La Gavia",
    "T-MD06 GPZ-Gran Plaza 2": "Gran Plaza 2",
    "T-MD07 PLE-Plenilunio": "Plenilunio",
}
ODOO_COMPANIA_OFICINA = "Glaseados Originales S.L."

HORAS_JORNADA_COMPLETA = 40  # pedido explícito del usuario

# Administración central ("GO - ADMIN CENTRAL" / "Oficina Central") no cuenta
# para estos KPIs -- son de tienda/fábrica, no de oficina. Se descarta tanto
# la plantilla activa como las bajas de ese centro antes de calcular nada.
CENTROS_EXCLUIDOS = {"Oficina Central"}

# Puestos de mando de área / dirección que en el Excel figuran asignados a
# una tienda concreta pero NO son plantilla de esa tienda (p.ej. un "Area
# Coach"). No cuentan para estos KPIs ni para el Planificador de turnos
# (ver planificador.py, que reutiliza esta lista). Coincidencia por
# subcadena, sin distinguir mayúsculas.
PUESTOS_NO_OPERATIVOS = ("area coach", "area manager", "director")


def puesto_no_operativo(puesto):
    p = (puesto or "").strip().lower()
    return any(x in p for x in PUESTOS_NO_OPERATIVOS)

# Motivos SEPE de "no superó el periodo de prueba" -- por iniciativa de la
# empresa o del propio trabajador cuentan igual para este KPI (NSPP no
# distingue quién lo decidió, solo que la baja fue en periodo de prueba).
_MOTIVO_NSPP = "periodo de prueba"

# Escalera de puestos -- pedida explícitamente por el usuario para
# reconocer una promoción real (subir de nivel) frente a un simple cambio
# de puesto lateral. Un puesto que no está aquí no se puede clasificar
# (no cuenta ni a favor ni en contra del KPI). Los nombres son los mismos
# "Posición/Puesto de trabajo" tal cual salen en el Excel de GO (confirmado
# 1 a 1 contra el archivo real) -- dos puestos con el mismo número son del
# mismo nivel (un cambio entre ellos es lateral, no promoción). Los alias
# al final son los nombres coloquiales que se usan hablando, por si alguien
# los escribe así al registrar un movimiento.
PUESTOS_NIVEL = {
    # --- Fábrica / Producción (ParqueSur Fábrica) ---
    "Auxiliar de Producción": 1,
    "Auxiliar de Decoración": 1,
    "Auxiliar de Limpieza": 1,
    "Formador Producción": 2,
    "Formador Decoración": 2,
    "JefeTurno Producción": 3,
    "Subgerente de Producción": 4,
    "Gerente de Producción": 5,
    # --- Tienda / Retail ---
    "Vendedor Retail": 1,
    "Formador Retail": 2,
    "JefeTurno Retail": 3,
    "Area Coach": 3,
    "SubGerente de Tienda": 4,
    "Gerente de Tienda": 5,
    "Gerente Senior": 6,
    # --- Alias coloquiales (tienda) ---
    "Dependiente": 1,
    "Krispy Coach": 2,
    "Jefe de Turno": 3,
    "Gerente": 5,
}
PUESTOS_JERARQUIA = list(PUESTOS_NIVEL.keys())

TIPOS_MOVIMIENTO = ("centro", "puesto")


def _normaliza(s):
    s = (s or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return s


_ALIAS_COLUMNAS = {
    "nombre del centro": "centro",
    "codigo empleado": "codigo_empleado",
    "nombre completo": "nombre",
    "fecha antiguedad": "fecha_antiguedad",
    "posicion/puesto de trabajo": "puesto",
    "porcentaje jornada": "porcentaje_jornada",
    "fecha de baja en compania": "fecha_baja",
    "motivo de baja de la compania": "motivo_baja",
}

# Export de Odoo -- ver ODOO_COMPANIA_A_CENTRO arriba. "creado el" NO se
# mapea a propósito: es la fecha en que se creó el registro de credencial en
# Odoo (una migración masiva histórica, no la fecha de alta real de la
# persona -- confirmado viendo que decenas de personas distintas comparten
# el mismo "Creado el" exacto), así que no sirve como fecha_antiguedad.
_ALIAS_COLUMNAS_ODOO = {
    "id de credencial": "codigo_empleado",
    "nombre del empleado": "nombre",
    "compania": "compania_raw",
    "horas contrato": "horas_contrato",
    "fecha de nacimiento": "fecha_nacimiento",
    "nacionalidad (pais)": "nacionalidad",
    "pais de nacimiento": "pais_nacimiento",
    "departamento": "departamento",
    "puesto de trabajo": "puesto",
    "fecha de salida": "fecha_baja",
}


def ensure_kpis_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kpi_empleados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_empleado TEXT NOT NULL UNIQUE,
            centro TEXT,
            nombre TEXT,
            fecha_antiguedad TEXT,
            puesto TEXT,
            porcentaje_jornada REAL,
            fecha_baja TEXT,
            motivo_baja TEXT
        )
    """)
    # fecha_nacimiento/nacionalidad/pais_nacimiento/departamento se añadieron
    # el 16/09 al importar por primera vez el export de Odoo (antes solo
    # existía el Excel de GO, que no trae estos datos) -- ALTER TABLE en vez
    # de recrear, para no perder lo que ya hubiera en kpi_empleados.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(kpi_empleados)")}
    for col in ("fecha_nacimiento", "nacionalidad", "pais_nacimiento", "departamento"):
        if col not in cols:
            conn.execute(f"ALTER TABLE kpi_empleados ADD COLUMN {col} TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kpi_importaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo_nombre TEXT,
            importado_por TEXT,
            importado_en TEXT NOT NULL DEFAULT (datetime('now')),
            filas INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kpi_movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_empleado TEXT NOT NULL,
            tipo TEXT NOT NULL,
            origen TEXT,
            destino TEXT NOT NULL,
            fecha TEXT NOT NULL,
            registrado_por TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _fecha_a_iso(valor):
    if valor is None:
        return None
    if isinstance(valor, (datetime.datetime, datetime.date)):
        return valor.strftime("%Y-%m-%d")
    texto = str(valor).strip()
    if not texto or texto.lower() == "nan":
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", texto)
    if m:
        d, mth, y = m.groups()
        try:
            return datetime.date(int(y), int(mth), int(d)).isoformat()
        except ValueError:
            return None
    return None


def _numero(valor):
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto or texto.lower() == "nan":
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _texto(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto if texto and texto.lower() != "nan" else None


def _codigo_empleado(valor):
    texto = _texto(valor)
    if texto and texto.endswith(".0") and texto[:-2].isdigit():
        return texto[:-2]
    return texto


def _centro_normalizado(valor):
    texto = _texto(valor)
    if texto is None:
        return None
    return CENTROS_GO_A_CORTO.get(texto, texto)


def _leer_filas_xlsx(contenido):
    wb = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    filas = list(ws.iter_rows(values_only=True))
    wb.close()
    return filas


def _leer_filas_xls(contenido):
    wb = xlrd.open_workbook(file_contents=contenido)
    ws = wb.sheet_by_index(0)
    filas = []
    for r in range(ws.nrows):
        fila = []
        for c in range(ws.ncols):
            celda = ws.cell(r, c)
            if celda.ctype == xlrd.XL_CELL_DATE:
                fila.append(datetime.datetime(*xlrd.xldate_as_tuple(celda.value, wb.datemode)))
            else:
                fila.append(celda.value)
        filas.append(fila)
    return filas


def import_excel(contenido, nombre_archivo, subido_por):
    es_xls = nombre_archivo.lower().endswith(".xls") and not nombre_archivo.lower().endswith(".xlsx")
    try:
        filas = _leer_filas_xls(contenido) if es_xls else _leer_filas_xlsx(contenido)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo Excel: {exc}")
    if not filas:
        raise ValueError("El archivo está vacío")

    encabezado = [_normaliza(str(c)) for c in filas[0]]
    indice = {}
    for i, col in enumerate(encabezado):
        clave = _ALIAS_COLUMNAS.get(col)
        if clave:
            indice[clave] = i
    faltantes = [c for c in ("centro", "codigo_empleado", "nombre") if c not in indice]
    if faltantes:
        raise ValueError(f"Faltan columnas obligatorias en el Excel: {', '.join(faltantes)}")

    registros = []
    for fila in filas[1:]:
        if fila is None or all(v is None or str(v).strip() == "" for v in fila):
            continue
        def val(clave):
            i = indice.get(clave)
            return fila[i] if i is not None and i < len(fila) else None
        codigo = _codigo_empleado(val("codigo_empleado"))
        if not codigo:
            continue
        registros.append((
            codigo, _centro_normalizado(val("centro")), _texto(val("nombre")),
            _fecha_a_iso(val("fecha_antiguedad")), _texto(val("puesto")),
            _numero(val("porcentaje_jornada")), _fecha_a_iso(val("fecha_baja")),
            _texto(val("motivo_baja")),
        ))
    if not registros:
        raise ValueError("No se encontró ninguna fila de empleado válida (falta el código de empleado)")

    conn = get_connection()
    conn.execute("DELETE FROM kpi_empleados")
    conn.executemany("""
        INSERT INTO kpi_empleados
            (codigo_empleado, centro, nombre, fecha_antiguedad, puesto, porcentaje_jornada, fecha_baja, motivo_baja)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, registros)
    conn.execute(
        "INSERT INTO kpi_importaciones (archivo_nombre, importado_por, filas) VALUES (?, ?, ?)",
        (nombre_archivo, subido_por, len(registros)),
    )
    conn.commit()
    conn.close()
    return {"filas": len(registros)}


def _centro_odoo(compania_raw, codigo_empleado, centro_existente_por_codigo):
    """Resuelve el centro real a partir de la "Compañía" de Odoo. Si trae el
    nombre genérico de la empresa (personal de oficina, ver
    ODOO_COMPANIA_OFICINA), se respeta lo que YA teníamos en la web para esa
    persona si había algo -- pedido explícito del usuario 16/09 ("si tienes
    ese conflicto te quedas con lo que tenemos en web") -- y si no había
    nada, se asume Oficina Central (es justo lo que describe ese archivo)."""
    texto = _texto(compania_raw)
    if texto is None:
        return centro_existente_por_codigo.get(codigo_empleado)
    if texto == ODOO_COMPANIA_OFICINA:
        return centro_existente_por_codigo.get(codigo_empleado) or "Oficina Central"
    return ODOO_COMPANIA_A_CENTRO.get(texto, texto)


def import_excel_odoo(archivos, subido_por):
    """archivos: lista de (nombre_archivo, contenido_bytes) -- uno o varios
    exports de Odoo a la vez (activos de oficina, activos de tienda/fábrica,
    bajas...); cada uno se detecta solo, según traiga o no la columna "Fecha
    de salida" (ver _ALIAS_COLUMNAS_ODOO). A diferencia de import_excel (el
    Excel de GO, que sustituye TODA la tabla de golpe), aquí se hace upsert
    por codigo_empleado fila a fila: no se toca fecha_antiguedad (Odoo no la
    exporta -- su "Creado el" es de una migración masiva, no la fecha de
    alta real, ver _ALIAS_COLUMNAS_ODOO) y, si la fila viene de un archivo
    de bajas, se conserva el motivo_baja que ya hubiera (Odoo tampoco trae
    motivo, solo fecha) para no perder lo ya reconciliado a mano con
    Entrevista de Salida. Aparecer en un archivo de ACTIVOS sí limpia
    fecha_baja/motivo_baja -- confirma que esa persona sigue de alta hoy."""
    conn = get_connection()
    centro_existente = {
        r["codigo_empleado"]: r["centro"]
        for r in conn.execute("SELECT codigo_empleado, centro FROM kpi_empleados").fetchall()
    }
    motivo_existente = {
        r["codigo_empleado"]: r["motivo_baja"]
        for r in conn.execute(
            "SELECT codigo_empleado, motivo_baja FROM kpi_empleados WHERE motivo_baja IS NOT NULL"
        ).fetchall()
    }

    total_filas = 0
    for nombre_archivo, contenido in archivos:
        es_xls = nombre_archivo.lower().endswith(".xls") and not nombre_archivo.lower().endswith(".xlsx")
        try:
            filas = _leer_filas_xls(contenido) if es_xls else _leer_filas_xlsx(contenido)
        except Exception as exc:
            conn.close()
            raise ValueError(f"No se pudo leer «{nombre_archivo}»: {exc}")
        if not filas:
            continue

        encabezado = [_normaliza(str(c)) for c in filas[0]]
        indice = {}
        for i, col in enumerate(encabezado):
            clave = _ALIAS_COLUMNAS_ODOO.get(col)
            if clave:
                indice[clave] = i
        if "codigo_empleado" not in indice or "nombre" not in indice:
            conn.close()
            raise ValueError(f"«{nombre_archivo}» no tiene el formato esperado del export de Odoo")
        es_archivo_bajas = "fecha_baja" in indice

        for fila in filas[1:]:
            if fila is None or all(v is None or str(v).strip() == "" for v in fila):
                continue

            def val(clave, fila=fila):
                i = indice.get(clave)
                return fila[i] if i is not None and i < len(fila) else None

            codigo = _codigo_empleado(val("codigo_empleado"))
            if not codigo:
                continue
            centro = _centro_odoo(val("compania_raw"), codigo, centro_existente)
            horas = _numero(val("horas_contrato"))
            porcentaje = round(horas / HORAS_JORNADA_COMPLETA * 100, 1) if horas is not None else None
            fecha_baja = _fecha_a_iso(val("fecha_baja")) if es_archivo_bajas else None
            motivo_baja = motivo_existente.get(codigo) if es_archivo_bajas else None

            conn.execute("""
                INSERT INTO kpi_empleados
                    (codigo_empleado, centro, nombre, puesto, porcentaje_jornada,
                     fecha_nacimiento, nacionalidad, pais_nacimiento, departamento,
                     fecha_baja, motivo_baja)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo_empleado) DO UPDATE SET
                    centro = excluded.centro,
                    nombre = excluded.nombre,
                    puesto = excluded.puesto,
                    porcentaje_jornada = excluded.porcentaje_jornada,
                    fecha_nacimiento = excluded.fecha_nacimiento,
                    nacionalidad = excluded.nacionalidad,
                    pais_nacimiento = excluded.pais_nacimiento,
                    departamento = excluded.departamento,
                    fecha_baja = excluded.fecha_baja,
                    motivo_baja = excluded.motivo_baja
            """, (
                codigo, centro, _texto(val("nombre")), _texto(val("puesto")), porcentaje,
                _fecha_a_iso(val("fecha_nacimiento")), _texto(val("nacionalidad")), _texto(val("pais_nacimiento")),
                _texto(val("departamento")), fecha_baja, motivo_baja,
            ))
            centro_existente[codigo] = centro
            total_filas += 1

    conn.execute(
        "INSERT INTO kpi_importaciones (archivo_nombre, importado_por, filas) VALUES (?, ?, ?)",
        (", ".join(n for n, _ in archivos), subido_por, total_filas),
    )
    conn.commit()
    conn.close()
    return {"filas": total_filas}


def get_ultima_importacion():
    conn = get_connection()
    row = conn.execute("SELECT * FROM kpi_importaciones ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def _tabla_existe(conn, nombre):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)
    ).fetchone() is not None


def _get_bajas(conn, empresa="kk"):
    """Todas las bajas registradas en Entrevista de Salida (cualquier oleada
    de esa empresa) -- fuente EN VIVO, crece sola cada vez que RRHH da de
    alta una salida ahí, sin depender de reimportar ningún Excel."""
    if not _tabla_existe(conn, "entrevistas_salidas") or not _tabla_existe(conn, "entrevistas_oleadas"):
        return []
    rows = conn.execute("""
        SELECT s.centro, s.fecha_baja, s.motivo
        FROM entrevistas_salidas s JOIN entrevistas_oleadas o ON o.id = s.oleada_id
        WHERE o.empresa = ? AND s.fecha_baja IS NOT NULL AND s.fecha_baja != ''
    """, (empresa,)).fetchall()
    return [dict(r) for r in rows]


def _es_nspp(motivo):
    return bool(motivo) and _MOTIVO_NSPP in motivo.lower()


def _es_nspp_empresario(motivo):
    """NSPP decidido por la empresa (motivo SEPE '07') -- el dato "malo" a
    propósito que comentó el usuario, provocado por la propia empresa para
    reducir horas, no una baja real de mercado. Se excluye para tener una
    lectura de rotación sin ese ruido."""
    if not motivo:
        return False
    m = motivo.lower()
    return _MOTIVO_NSPP in m and "instancia del empresario" in m


def buscar_empleado(codigo_empleado):
    """Nombre/centro/puesto actuales de un empleado por su código -- para
    que al registrar un movimiento se pueda confirmar que es la persona
    correcta antes de guardar nada."""
    conn = get_connection()
    row = conn.execute(
        "SELECT codigo_empleado, nombre, centro, puesto, fecha_baja FROM kpi_empleados WHERE codigo_empleado = ?",
        (str(codigo_empleado).strip(),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def marcar_baja_manual(codigo_empleado, fecha_baja, motivo_baja):
    """Corrige a mano un registro de kpi_empleados que el Excel de GO todavía
    trae como activo pero que Entrevista de Salida ya tiene registrado como
    baja (el Excel es una foto puntual, puede ir por detrás). Se pierde en
    la próxima importación -- si el Excel sigue sin traer la baja hay que
    volver a aplicarla."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE kpi_empleados SET fecha_baja = ?, motivo_baja = ? WHERE codigo_empleado = ?",
        (fecha_baja, motivo_baja, str(codigo_empleado)),
    )
    conn.commit()
    afectado = cur.rowcount
    conn.close()
    if not afectado:
        raise ValueError(f"No se encontró ningún empleado con código {codigo_empleado}")
    return {"ok": True}


def agregar_movimiento(codigo_empleado, tipo, origen, destino, fecha, registrado_por):
    """Traslado de centro o promoción/cambio de puesto -- se registra a mano
    por código de empleado (más preciso que por nombre). Con esto se
    reconstruye mejor el centro histórico de esa persona y se puede calcular
    el % de promoción interna real."""
    codigo_empleado = (codigo_empleado or "").strip()
    tipo = (tipo or "").strip().lower()
    destino = (destino or "").strip()
    fecha = (fecha or "").strip()
    origen = (origen or "").strip() or None
    if not codigo_empleado:
        raise ValueError("Falta el código de empleado")
    if tipo not in TIPOS_MOVIMIENTO:
        raise ValueError("Tipo de movimiento no válido")
    if not destino:
        raise ValueError("Falta el destino")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha):
        raise ValueError("Fecha no válida")
    conn = get_connection()
    conn.execute(
        "INSERT INTO kpi_movimientos (codigo_empleado, tipo, origen, destino, fecha, registrado_por) VALUES (?, ?, ?, ?, ?, ?)",
        (codigo_empleado, tipo, origen, destino, fecha, registrado_por),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def listar_movimientos(tipo=None):
    conn = get_connection()
    if tipo:
        rows = conn.execute(
            "SELECT * FROM kpi_movimientos WHERE tipo = ? ORDER BY fecha DESC, id DESC", (tipo,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM kpi_movimientos ORDER BY fecha DESC, id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_movimiento(movimiento_id):
    conn = get_connection()
    cur = conn.execute("DELETE FROM kpi_movimientos WHERE id = ?", (movimiento_id,))
    conn.commit()
    afectado = cur.rowcount
    conn.close()
    if not afectado:
        raise ValueError("No se encontró ese movimiento")
    return {"ok": True}


def _movimientos_centro_por_codigo(conn):
    """{codigo_empleado: [{fecha, origen, destino}, ...]} ordenados por
    fecha ascendente -- para poder ir "aplicando" cada traslado en orden y
    saber en qué centro estaba alguien en una fecha concreta."""
    if not _tabla_existe(conn, "kpi_movimientos"):
        return {}
    rows = conn.execute(
        "SELECT codigo_empleado, origen, destino, fecha FROM kpi_movimientos WHERE tipo = 'centro' ORDER BY fecha ASC, id ASC"
    ).fetchall()
    por_codigo = {}
    for r in rows:
        por_codigo.setdefault(r["codigo_empleado"], []).append(dict(r))
    return por_codigo


def _centro_en_fecha(centro_actual, movimientos, fecha_corte):
    if not movimientos:
        return centro_actual
    aplicados = [m for m in movimientos if m["fecha"] <= fecha_corte]
    if not aplicados:
        # El primer traslado registrado es posterior al corte -- antes de
        # ese traslado, la persona estaba en su centro de origen.
        return movimientos[0]["origen"] or centro_actual
    return aplicados[-1]["destino"] or centro_actual


def _nivel_puesto(puesto):
    return PUESTOS_NIVEL.get((puesto or "").strip())


def _es_promocion(origen, destino):
    """True si subió de nivel, False si fue lateral o bajó, None si alguno
    de los dos puestos no está en PUESTOS_NIVEL (no se puede clasificar,
    no cuenta ni a favor ni en contra del KPI)."""
    nivel_origen = _nivel_puesto(origen)
    nivel_destino = _nivel_puesto(destino)
    if nivel_origen is None or nivel_destino is None:
        return None
    return nivel_destino > nivel_origen


def _mes(fecha_iso):
    """'2026-03-15' -> '2026-03' -- agrupa por mes calendario. Tolera fechas
    en otros formatos sueltos (dd/mm/aaaa) que a veces se cuelan al registrar
    una salida a mano."""
    if not fecha_iso:
        return None
    if re.match(r"^\d{4}-\d{2}", fecha_iso):
        return fecha_iso[:7]
    m = re.match(r"^\d{1,2}/(\d{1,2})/(\d{4})$", fecha_iso)
    if m:
        mth, y = m.groups()
        return f"{y}-{int(mth):02d}"
    return None


def _fin_de_mes(clave_mes):
    anio, mes = (int(x) for x in clave_mes.split("-"))
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return f"{anio:04d}-{mes:02d}-{ultimo_dia:02d}"


def _dia_antes_de_mes(clave_mes):
    """Último día del mes anterior -- la plantilla "al inicio" de un mes es
    la misma que "al final" del mes de antes."""
    anio, mes = (int(x) for x in clave_mes.split("-"))
    primer_dia = datetime.date(anio, mes, 1)
    return (primer_dia - datetime.timedelta(days=1)).isoformat()


def _activos_a_fecha(empleados, fecha_corte):
    """Quiénes estaban de alta en una fecha concreta -- se reconstruye con
    la fecha de antigüedad (alta) y la fecha de baja que ya trae el Excel de
    plantilla para cada empleado, así se puede saber la plantilla/horas de
    cualquier mes pasado, no solo la de ahora mismo. Un empleado sin fecha
    de antigüedad se asume de alta desde siempre (dato que a veces falta en
    el Excel) en vez de excluirlo."""
    activos = []
    for e in empleados:
        antiguedad = e.get("fecha_antiguedad")
        baja = e.get("fecha_baja")
        if antiguedad and antiguedad > fecha_corte:
            continue
        if baja and baja <= fecha_corte:
            continue
        activos.append(e)
    return activos


def _headcount_y_horas_por_centro(empleados_activos, movimientos_por_codigo=None, fecha_corte=None):
    hc_centro = {}
    horas_centro = {}
    for e in empleados_activos:
        centro_actual = e["centro"] or "(sin centro)"
        if movimientos_por_codigo is not None and fecha_corte:
            movs = movimientos_por_codigo.get(e["codigo_empleado"], [])
            c = _centro_en_fecha(centro_actual, movs, fecha_corte) or "(sin centro)"
        else:
            c = centro_actual
        hc_centro[c] = hc_centro.get(c, 0) + 1
        pct = e["porcentaje_jornada"]
        horas = (pct / 100 * HORAS_JORNADA_COMPLETA) if pct is not None else HORAS_JORNADA_COMPLETA
        horas_centro[c] = horas_centro.get(c, 0) + horas
    return (
        sorted(hc_centro.items(), key=lambda x: -x[1]),
        sorted([(c, round(h, 1)) for c, h in horas_centro.items()], key=lambda x: -x[1]),
    )


def _por_jornada(empleados_activos):
    """Cuántas personas hay en cada tipo de jornada (horas/semana) -- a
    partir del "Porcentaje Jornada" real del Excel, no de valores fijos
    inventados (25% -> 10h, 50% -> 20h, 60% -> 24h...). Cuando el Excel no
    trae ese dato se sigue asumiendo jornada completa (40h, mismo criterio
    que el resto del dashboard), pero se cuenta aparte para que quede claro
    que es un supuesto, no un dato real."""
    conteo = {}
    sin_dato = 0
    for e in empleados_activos:
        pct = e["porcentaje_jornada"]
        if pct is None:
            sin_dato += 1
            horas = HORAS_JORNADA_COMPLETA
        else:
            horas = round(pct / 100 * HORAS_JORNADA_COMPLETA, 1)
        horas = int(horas) if horas == int(horas) else horas
        conteo[horas] = conteo.get(horas, 0) + 1
    return sorted(conteo.items(), key=lambda x: x[0]), sin_dato


def _edad(fecha_nacimiento, hoy):
    if not fecha_nacimiento:
        return None
    try:
        anio, mes, dia = (int(x) for x in fecha_nacimiento[:10].split("-"))
    except ValueError:
        return None
    edad = hoy.year - anio
    if (hoy.month, hoy.day) < (mes, dia):
        edad -= 1
    return edad


def _nacionalidad_y_edad(empleados_activos, hoy):
    """Gráfico de tarta de nacionalidades + edad media, general y por centro
    -- pedido explícito del usuario 16/09 tras añadir estos campos al
    importar el export de Odoo. Ambos se calculan solo sobre quien tiene el
    dato (una plantilla mixta, con gente del Excel viejo de GO sin estos
    campos todavía, no debe salir con "(sin dato)" contando como si fuera
    una nacionalidad real, ni bajar la edad media a 0)."""
    nacionalidades = {}
    edades = []
    edades_por_centro = {}
    for e in empleados_activos:
        nac = (e.get("nacionalidad") or "").strip()
        if nac:
            nacionalidades[nac] = nacionalidades.get(nac, 0) + 1
        edad = _edad(e.get("fecha_nacimiento"), hoy)
        if edad is not None:
            edades.append(edad)
            centro = e.get("centro") or "(sin centro)"
            edades_por_centro.setdefault(centro, []).append(edad)
    edad_media_por_centro = sorted(
        ((c, round(sum(es) / len(es), 1)) for c, es in edades_por_centro.items()),
        key=lambda x: x[0],
    )
    return {
        "nacionalidades": sorted(nacionalidades.items(), key=lambda x: -x[1]),
        "edad_media": round(sum(edades) / len(edades), 1) if edades else None,
        "edad_media_por_centro": edad_media_por_centro,
        "con_dato_nacionalidad": sum(nacionalidades.values()),
        "con_dato_edad": len(edades),
    }


def compute_resumen(segmento="operativa"):
    """segmento="operativa" (por defecto, comportamiento de siempre): tienda
    y fábrica, sin Oficina Central ni puestos de mando de área/dirección.
    segmento="oficina" (16/09, pedido explícito del usuario para poder ver
    los KPIs de oficina por separado en vez de solo descartarlos): justo lo
    contrario, SOLO Oficina Central."""
    conn = get_connection()
    empleados = [dict(r) for r in conn.execute("SELECT * FROM kpi_empleados").fetchall()]
    bajas = _get_bajas(conn)
    movimientos_centro = _movimientos_centro_por_codigo(conn)
    movimientos_puesto = (
        conn.execute("SELECT * FROM kpi_movimientos WHERE tipo = 'puesto'").fetchall()
        if _tabla_existe(conn, "kpi_movimientos") else []
    )
    movimientos_puesto = [dict(r) for r in movimientos_puesto]
    conn.close()

    if segmento == "oficina":
        codigos_excluidos = {e["codigo_empleado"] for e in empleados if e["centro"] not in CENTROS_EXCLUIDOS}
    else:
        codigos_excluidos = {
            e["codigo_empleado"] for e in empleados
            if e["centro"] in CENTROS_EXCLUIDOS or puesto_no_operativo(e.get("puesto"))
        }
    empleados = [e for e in empleados if e["codigo_empleado"] not in codigos_excluidos]
    if segmento == "oficina":
        bajas = [b for b in bajas if b["centro"] in CENTROS_EXCLUIDOS]
    else:
        bajas = [b for b in bajas if b["centro"] not in CENTROS_EXCLUIDOS]
    movimientos_puesto = [m for m in movimientos_puesto if m["codigo_empleado"] not in codigos_excluidos]

    hoy = datetime.date.today()
    hoy_str = hoy.isoformat()

    activos = _activos_a_fecha(empleados, hoy_str)
    headcount_activo = len(activos)
    headcount_por_centro_lista, horas_por_centro_lista = _headcount_y_horas_por_centro(
        activos, movimientos_centro, hoy_str
    )
    nacionalidad_y_edad = _nacionalidad_y_edad(activos, hoy)

    # --- Serie mensual completa (todo el histórico de Entrevista de Salida) -
    # Se calcula para TODOS los meses con datos (no solo los últimos 12) para
    # que el frontend pueda filtrar por un rango de fechas cualquiera. Cada
    # mes recalcula también su propia plantilla/horas "a fecha de fin de ese
    # mes" (con fecha_antiguedad/fecha_baja) -- no es una foto fija, así el
    # gráfico de horas por centro también responde al filtro de fechas.
    bajas_por_mes = {}
    bajas_centro_mes = {}
    bajas_motivo_mes = {}
    nspp_por_mes = {}
    sin_empresario_por_mes = {}
    for b in bajas:
        clave = _mes(b["fecha_baja"])
        if not clave:
            continue
        bajas_por_mes[clave] = bajas_por_mes.get(clave, 0) + 1
        centro = b["centro"] or "(sin centro)"
        bajas_centro_mes.setdefault(clave, {})
        bajas_centro_mes[clave][centro] = bajas_centro_mes[clave].get(centro, 0) + 1
        motivo = b["motivo"] or "(sin dato)"
        bajas_motivo_mes.setdefault(clave, {})
        bajas_motivo_mes[clave][motivo] = bajas_motivo_mes[clave].get(motivo, 0) + 1
        if _es_nspp(motivo):
            nspp_por_mes[clave] = nspp_por_mes.get(clave, 0) + 1
        if not _es_nspp_empresario(motivo):
            sin_empresario_por_mes[clave] = sin_empresario_por_mes.get(clave, 0) + 1

    promociones_por_mes = {}
    for m in movimientos_puesto:
        clave = _mes(m["fecha"])
        if clave and _es_promocion(m["origen"], m["destino"]) is True:
            promociones_por_mes[clave] = promociones_por_mes.get(clave, 0) + 1

    # Altas (contrataciones) -- reconstruidas con la fecha de antigüedad de
    # cada empleado del Excel. OJO: el Excel es una foto de "quién está hoy
    # en nómina" (más las bajas recientes que trae) -- si alguien entró y
    # salió hace tiempo y ya no aparece en la última importación, esa alta
    # no se cuenta aquí. Para gente activa ahora mismo (o de baja reciente,
    # ya cubierta por el Excel) es fiable.
    altas_por_mes = {}
    for e in empleados:
        clave = _mes(e.get("fecha_antiguedad"))
        if clave:
            altas_por_mes[clave] = altas_por_mes.get(clave, 0) + 1

    # El rango del calendario sigue marcado solo por las bajas (no por las
    # altas) -- si se incluyeran altas antiguas (alguien con muchísima
    # antigüedad) el calendario se iría años atrás sin necesidad real, que
    # es justo lo que se quería evitar con el selector tipo calendario.
    mes_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    claves_con_datos = sorted(bajas_por_mes.keys())
    inicio = min(claves_con_datos[0], mes_actual) if claves_con_datos else mes_actual
    fin = max(claves_con_datos[-1], mes_actual) if claves_con_datos else mes_actual

    meses_disponibles = []
    anio_i, mes_i = (int(x) for x in inicio.split("-"))
    anio_f, mes_f = (int(x) for x in fin.split("-"))
    while (anio_i, mes_i) <= (anio_f, mes_f):
        meses_disponibles.append(f"{anio_i:04d}-{mes_i:02d}")
        mes_i += 1
        if mes_i > 12:
            mes_i = 1
            anio_i += 1

    # Fórmula estándar de rotación: bajas / plantilla PROMEDIO del periodo
    # (media entre la plantilla al inicio y al final), no solo la de "Hasta"
    # -- usar solo el final infla mucho el % cuando la plantilla creció
    # durante el periodo (p.ej. apertura de una tienda nueva).
    serie_mensual = {}
    for clave in meses_disponibles:
        n = bajas_por_mes.get(clave, 0)
        fecha_corte_mes = _fin_de_mes(clave)
        activos_mes = _activos_a_fecha(empleados, fecha_corte_mes)
        activos_inicio_mes = _activos_a_fecha(empleados, _dia_antes_de_mes(clave))
        hc_centro_mes, horas_centro_mes = _headcount_y_horas_por_centro(
            activos_mes, movimientos_centro, fecha_corte_mes
        )
        hc_centro_inicio_mes, _ = _headcount_y_horas_por_centro(
            activos_inicio_mes, movimientos_centro, _dia_antes_de_mes(clave)
        )
        por_jornada_mes, sin_dato_jornada_mes = _por_jornada(activos_mes)
        headcount_promedio_mes = (len(activos_inicio_mes) + len(activos_mes)) / 2
        serie_mensual[clave] = {
            "bajas": n,
            "pct": round(n / headcount_promedio_mes * 100, 1) if headcount_promedio_mes else 0,
            "por_centro": sorted(bajas_centro_mes.get(clave, {}).items(), key=lambda x: -x[1]),
            "por_motivo": sorted(bajas_motivo_mes.get(clave, {}).items(), key=lambda x: -x[1]),
            "headcount_activo": len(activos_mes),
            "headcount_inicio": len(activos_inicio_mes),
            "headcount_por_centro": hc_centro_mes,
            "headcount_por_centro_inicio": hc_centro_inicio_mes,
            "horas_por_centro": horas_centro_mes,
            "horas_totales": round(sum(h for _, h in horas_centro_mes), 1),
            "nspp": nspp_por_mes.get(clave, 0),
            "sin_nspp_empresario": sin_empresario_por_mes.get(clave, 0),
            "promociones": promociones_por_mes.get(clave, 0),
            "altas": altas_por_mes.get(clave, 0),
            "por_jornada": por_jornada_mes,
            "sin_dato_jornada": sin_dato_jornada_mes,
        }
    anios_disponibles = sorted({m[:4] for m in meses_disponibles}) or [str(hoy.year)]

    # --- Acumulado anual (año natural, desde el 1 de enero) ----------------
    inicio_anio = f"{hoy.year}-01-01"
    bajas_ytd = [b for b in bajas if b["fecha_baja"] and b["fecha_baja"] >= inicio_anio]
    acumulado_anual_pct = round(len(bajas_ytd) / headcount_activo * 100, 1) if headcount_activo else 0

    # --- % NSPP (sobre las bajas del año en curso) --------------------------
    nspp_ytd = [b for b in bajas_ytd if _es_nspp(b["motivo"])]
    nspp_pct = round(len(nspp_ytd) / len(bajas_ytd) * 100, 1) if bajas_ytd else 0

    # --- Rotación anual quitando los NSPP decididos por la empresa ---------
    # Mismo acumulado anual, pero sin los "07 Cese en periodo de prueba a
    # instancia del empresario" -- ese es el dato "malo a propósito" que
    # comentó el usuario (provocado por la empresa para bajar horas), así se
    # puede ver la rotación real sin ese ruido.
    bajas_ytd_sin_empresario = [b for b in bajas_ytd if not _es_nspp_empresario(b["motivo"])]
    rotacion_sin_nspp_empresario_pct = (
        round(len(bajas_ytd_sin_empresario) / headcount_activo * 100, 1) if headcount_activo else 0
    )

    # --- % de promoción interna (año en curso) ------------------------------
    # Solo cuenta como promoción un movimiento de puesto que sube de nivel en
    # PUESTOS_JERARQUIA -- un puesto que no está en esa lista no se puede
    # clasificar (no suma ni resta). Requiere que alguien vaya registrando
    # los movimientos en "Movimientos internos"; sin datos ahí, sale 0.
    promociones_ytd = [
        m for m in movimientos_puesto
        if m["fecha"] and m["fecha"] >= inicio_anio and _es_promocion(m["origen"], m["destino"]) is True
    ]
    promocion_interna_pct = round(len(promociones_ytd) / headcount_activo * 100, 1) if headcount_activo else 0

    return {
        "headcount_activo": headcount_activo,
        "horas_contratadas_totales": round(sum(h for _, h in horas_por_centro_lista), 1),
        "horas_jornada_completa": HORAS_JORNADA_COMPLETA,
        "mes_actual": mes_actual,
        "serie_mensual": serie_mensual,
        "meses_disponibles": meses_disponibles,
        "anios_disponibles": anios_disponibles,
        "headcount_por_centro": headcount_por_centro_lista,
        "acumulado_anual_pct": acumulado_anual_pct,
        "bajas_ytd": len(bajas_ytd),
        "nspp_pct": nspp_pct,
        "nspp_ytd": len(nspp_ytd),
        "rotacion_sin_nspp_empresario_pct": rotacion_sin_nspp_empresario_pct,
        "bajas_sin_nspp_empresario_ytd": len(bajas_ytd_sin_empresario),
        "promocion_interna_pct": promocion_interna_pct,
        "promociones_ytd": len(promociones_ytd),
        "puestos_jerarquia": PUESTOS_JERARQUIA,
        "centros_disponibles": sorted(set(CENTROS_GO_A_CORTO.values())),
        "horas_por_centro": horas_por_centro_lista,
        "sin_datos_plantilla": headcount_activo == 0,
        "sin_datos_bajas": len(bajas) == 0,
        "segmento": segmento,
        **nacionalidad_y_edad,
    }


ensure_kpis_tables()
