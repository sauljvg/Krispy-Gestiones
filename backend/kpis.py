"""Dashboard de KPIs de personal -- se alimenta del informe de plantilla que
exporta GO (columnas: Centro, Código Empleado, Nombre, Fecha Antigüedad,
Puesto, % Jornada, Fecha de baja, Motivo de baja). Cada fila puede ser un
empleado ACTIVO (sin fecha de baja) o ya DADO DE BAJA (con fecha y motivo) --
el propio informe trae la plantilla completa, así que cada importación
reemplaza los datos anteriores por completo (no hace falta llevar un
histórico de "oleadas" como en Entrevista de Salida/Clima, esto es una foto
del estado actual, no una encuesta)."""
import datetime
import io
import re

import xlrd
from openpyxl import load_workbook

from db import get_connection

COLUMNAS_ESPERADAS = (
    "centro", "codigo_empleado", "nombre", "fecha_antiguedad",
    "puesto", "porcentaje_jornada", "fecha_baja", "motivo_baja",
)

# Nombre de columna del Excel (normalizado: sin tildes/mayúsculas) -> clave
# interna -- para no depender de que el orden de columnas sea exacto.
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


def _normaliza(s):
    s = (s or "").strip().lower()
    # "Antigüedad" lleva ü (diéresis), no una vocal con tilde normal -- sin
    # esto la columna "Fecha Antigüedad" nunca hacía match con el alias y la
    # fecha de antigüedad se perdía en silencio para TODOS los activos
    # (confirmado con el archivo real: 89/89 sin fecha_antiguedad).
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return s


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
    """Acepta datetime/date (celdas de fecha reales) o texto dd/mm/aaaa
    (lo habitual cuando la fecha llega como texto plano) -- None si está
    vacía o no se puede interpretar."""
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
    """xlrd (y a veces openpyxl) lee una celda numérica como float de
    Python, así que un código "40004" llega como 40004.0 -- sin esto se
    guardaría el ".0" pegado, rompiendo cualquier futuro cruce por código
    con otro archivo."""
    texto = _texto(valor)
    if texto and texto.endswith(".0") and texto[:-2].isdigit():
        return texto[:-2]
    return texto


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
            codigo, _texto(val("centro")), _texto(val("nombre")),
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
    row = conn.execute(
        "SELECT * FROM kpi_importaciones ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _edad_dias(fecha_iso, hasta_iso=None):
    if not fecha_iso:
        return None
    inicio = datetime.date.fromisoformat(fecha_iso)
    fin = datetime.date.fromisoformat(hasta_iso) if hasta_iso else datetime.date.today()
    return (fin - inicio).days


def compute_resumen(dias_rotacion=365):
    """Calcula todos los KPIs de golpe a partir de la foto actual de
    kpi_empleados -- nada se guarda calculado, siempre en vivo sobre los
    datos de la última importación."""
    conn = get_connection()
    filas = [dict(r) for r in conn.execute("SELECT * FROM kpi_empleados").fetchall()]
    conn.close()

    activos = [f for f in filas if not f["fecha_baja"]]
    bajas = [f for f in filas if f["fecha_baja"]]

    hoy = datetime.date.today()
    limite_rotacion = (hoy - datetime.timedelta(days=dias_rotacion)).isoformat()
    bajas_periodo = [f for f in bajas if f["fecha_baja"] >= limite_rotacion]

    # Antigüedad media de la plantilla activa (en meses, más legible que días).
    antig_dias = [_edad_dias(f["fecha_antiguedad"]) for f in activos if f["fecha_antiguedad"]]
    antig_media_meses = round((sum(antig_dias) / len(antig_dias)) / 30.44, 1) if antig_dias else None

    # Tasa de rotación simple: bajas en el periodo / headcount medio del
    # periodo (activos ahora + bajas del periodo, como aproximación del
    # tamaño de plantilla durante esa ventana -- sin un histórico diario de
    # headcount no se puede calcular la media exacta día a día).
    headcount_medio = len(activos) + len(bajas_periodo)
    tasa_rotacion = round(len(bajas_periodo) / headcount_medio * 100, 1) if headcount_medio else 0

    # Bajas en periodo de prueba (motivos SEPE 07/09, ver el Excel real) vs
    # el resto -- para separar "no encajó" de rotación en plantilla asentada.
    bajas_prueba = [f for f in bajas_periodo if f["motivo_baja"] and "periodo de prueba" in f["motivo_baja"].lower()]

    def _contar_por(campo, lista):
        conteo = {}
        for f in lista:
            clave = f.get(campo) or "(sin dato)"
            conteo[clave] = conteo.get(clave, 0) + 1
        return sorted(conteo.items(), key=lambda x: -x[1])

    por_centro = _contar_por("centro", activos)
    bajas_por_centro = _contar_por("centro", bajas_periodo)
    bajas_por_motivo = _contar_por("motivo_baja", bajas_periodo)
    por_puesto = _contar_por("puesto", activos)

    jornada_completa = len([f for f in activos if f["porcentaje_jornada"] is None or f["porcentaje_jornada"] >= 100])
    jornada_parcial = len(activos) - jornada_completa

    altas_recientes = len([
        f for f in activos
        if f["fecha_antiguedad"] and f["fecha_antiguedad"] >= (hoy - datetime.timedelta(days=90)).isoformat()
    ])

    return {
        "headcount_activo": len(activos),
        "bajas_periodo": len(bajas_periodo),
        "bajas_totales_historico": len(bajas),
        "tasa_rotacion_pct": tasa_rotacion,
        "dias_rotacion": dias_rotacion,
        "antiguedad_media_meses": antig_media_meses,
        "bajas_prueba_pct": round(len(bajas_prueba) / len(bajas_periodo) * 100, 1) if bajas_periodo else 0,
        "altas_ultimos_90_dias": altas_recientes,
        "jornada_completa": jornada_completa,
        "jornada_parcial": jornada_parcial,
        "por_centro": por_centro,
        "bajas_por_centro": bajas_por_centro,
        "bajas_por_motivo": bajas_por_motivo,
        "por_puesto": por_puesto[:12],  # top 12, para no desbordar el gráfico
    }


ensure_kpis_tables()
