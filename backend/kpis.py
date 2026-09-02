"""Dashboard de KPIs de personal -- dos fuentes de datos distintas, a
propósito (pedido explícito del usuario):

1. Plantilla ACTIVA y horas contratadas: el informe que exporta GO
   (importación puntual, ver import_excel/kpi_empleados) -- es una foto de
   "quién está en nómina ahora mismo", no cambia sola.
2. Bajas (para rotación mensual/anual y % NSPP): la tabla EN VIVO de
   Entrevista de Salida (entrevistas_salidas), que crece cada vez que RRHH
   da de alta una salida ahí -- así el dashboard se mantiene al día solo,
   sin depender de reimportar el Excel cada vez que se va alguien.

% de promoción interna: NO se calcula todavía -- no hay ninguna fuente de
datos con el historial de cambios de puesto (el usuario lo confirmó: "por
ahora no lo tenemos"). Se deja como placeholder en el frontend en vez de
inventar un número."""
import datetime
import io
import re
import sqlite3

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

HORAS_JORNADA_COMPLETA = 40  # pedido explícito del usuario

# Motivos SEPE de "no superó el periodo de prueba" -- por iniciativa de la
# empresa o del propio trabajador cuentan igual para este KPI (NSPP no
# distingue quién lo decidió, solo que la baja fue en periodo de prueba).
_MOTIVO_NSPP = "periodo de prueba"


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kpi_importaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo_nombre TEXT,
            importado_por TEXT,
            importado_en TEXT NOT NULL DEFAULT (datetime('now')),
            filas INTEGER
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


def compute_resumen(meses_historico=12):
    conn = get_connection()
    empleados = [dict(r) for r in conn.execute("SELECT * FROM kpi_empleados").fetchall()]
    bajas = _get_bajas(conn)
    conn.close()

    activos = [e for e in empleados if not e["fecha_baja"]]
    headcount_activo = len(activos)

    hoy = datetime.date.today()

    # --- Rotación mensual (global): últimos `meses_historico` meses -------
    # Denominador simplificado a propósito: la plantilla activa ACTUAL, no
    # una reconstrucción histórica mes a mes (para eso haría falta un
    # histórico diario de headcount que hoy no existe) -- documentado tal
    # cual en el frontend, es la misma aproximación que usan la mayoría de
    # cuadros de mando de rotación cuando no hay ese histórico.
    serie_meses = []
    for i in range(meses_historico - 1, -1, -1):
        anio = hoy.year + (hoy.month - 1 - i) // 12
        mes = (hoy.month - 1 - i) % 12 + 1
        serie_meses.append(f"{anio:04d}-{mes:02d}")
    bajas_por_mes = {}
    bajas_centro_mes = {}
    for b in bajas:
        clave = _mes(b["fecha_baja"])
        if not clave:
            continue
        bajas_por_mes[clave] = bajas_por_mes.get(clave, 0) + 1
        centro = b["centro"] or "(sin centro)"
        bajas_centro_mes.setdefault(centro, {})
        bajas_centro_mes[centro][clave] = bajas_centro_mes[centro].get(clave, 0) + 1

    rotacion_mensual = [
        {"mes": m, "bajas": bajas_por_mes.get(m, 0),
         "pct": round(bajas_por_mes.get(m, 0) / headcount_activo * 100, 1) if headcount_activo else 0}
        for m in serie_meses
    ]

    # --- Rotación del mes en curso, por centro -----------------------------
    mes_actual = serie_meses[-1]
    headcount_por_centro = {}
    for e in activos:
        c = e["centro"] or "(sin centro)"
        headcount_por_centro[c] = headcount_por_centro.get(c, 0) + 1
    rotacion_por_centro = []
    for centro, meses in bajas_centro_mes.items():
        n = meses.get(mes_actual, 0)
        if n == 0 and centro not in headcount_por_centro:
            continue
        hc = headcount_por_centro.get(centro, 0)
        rotacion_por_centro.append((centro, round(n / hc * 100, 1) if hc else 0))
    rotacion_por_centro.sort(key=lambda x: -x[1])

    # --- Acumulado anual (año natural, desde el 1 de enero) ----------------
    inicio_anio = f"{hoy.year}-01-01"
    bajas_ytd = [b for b in bajas if b["fecha_baja"] and b["fecha_baja"] >= inicio_anio]
    acumulado_anual_pct = round(len(bajas_ytd) / headcount_activo * 100, 1) if headcount_activo else 0

    # --- % NSPP (sobre las bajas del año en curso) --------------------------
    nspp_ytd = [b for b in bajas_ytd if _es_nspp(b["motivo"])]
    nspp_pct = round(len(nspp_ytd) / len(bajas_ytd) * 100, 1) if bajas_ytd else 0

    # --- Horas contratadas por centro (Porcentaje Jornada -> horas reales) -
    horas_por_centro = {}
    for e in activos:
        c = e["centro"] or "(sin centro)"
        pct = e["porcentaje_jornada"]
        horas = (pct / 100 * HORAS_JORNADA_COMPLETA) if pct is not None else HORAS_JORNADA_COMPLETA
        horas_por_centro[c] = horas_por_centro.get(c, 0) + horas
    horas_por_centro_lista = sorted(
        [(c, round(h, 1)) for c, h in horas_por_centro.items()], key=lambda x: -x[1]
    )

    def _contar_por(campo, lista):
        conteo = {}
        for f in lista:
            clave = f.get(campo) or "(sin dato)"
            conteo[clave] = conteo.get(clave, 0) + 1
        return sorted(conteo.items(), key=lambda x: -x[1])

    return {
        "headcount_activo": headcount_activo,
        "horas_contratadas_totales": round(sum(horas_por_centro.values()), 1),
        "horas_jornada_completa": HORAS_JORNADA_COMPLETA,
        "rotacion_mensual": rotacion_mensual,
        "rotacion_por_centro_mes_actual": rotacion_por_centro,
        "mes_actual": mes_actual,
        "acumulado_anual_pct": acumulado_anual_pct,
        "bajas_ytd": len(bajas_ytd),
        "nspp_pct": nspp_pct,
        "nspp_ytd": len(nspp_ytd),
        "bajas_por_motivo_ytd": _contar_por("motivo", bajas_ytd),
        "horas_por_centro": horas_por_centro_lista,
        "sin_datos_plantilla": headcount_activo == 0,
        "sin_datos_bajas": len(bajas) == 0,
    }


ensure_kpis_tables()
