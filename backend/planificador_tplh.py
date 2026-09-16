"""TPLH (Transacciones Por Labor Hora): histórico semanal de horas
planificadas / tickets vendidos / TPLH real, por centro -- pedido explícito
del usuario 16/09.

Contexto (tal como lo explicó el usuario): cada mes finanzas le manda a cada
tienda el margen de TPLH que debe mantener; el area manager o el director de
operaciones reparte ese objetivo en un Excel semanal como el que ya vienen
usando (un bloque de 3 tablas -- horas planificadas, TSX vendidos, TPLH
resultante -- por centro). Aquí se importa ese Excel tal cual para ir
construyendo un histórico real, y "Optimización de turnos" usa ese
histórico (promedio de TSX del mismo día de la semana en semanas pasadas)
más el objetivo de transacciones/hora YA configurado por centro (ver
planificador.get_config) para sugerir cuántas horas planificar la semana
que viene -- una ESTIMACIÓN que mejora sola según se importen más meses,
nunca una certeza (nadie puede saber de antemano cuántos tickets se van a
vender, tal cual lo dijo el usuario)."""
import datetime
import io
import re

from openpyxl import load_workbook

import planificador as planificador_module
from db import get_connection

# El Excel nombra los centros en mayúsculas y sin el sufijo Tienda/Fábrica --
# "PARQUE SUR" es siempre la tienda (TPLH es un dato de venta al público, la
# fábrica no vende tickets). "GRAN PLAZA" -> "Gran Plaza 2" es la única
# diferencia real de nombre.
CENTROS_TPLH_A_CORTO = {
    "PARQUE SUR": "ParqueSur Tienda",
    "PRINCESA": "Princesa",
    "LA GAVIA": "La Gavia",
    "CALEIDO": "Caleido",
    "GRAN PLAZA": "Gran Plaza 2",
    "PLENILUNIO": "Plenilunio",
}

DIAS_COLUMNA = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]


def ensure_tplh_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planificador_tplh_dias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL DEFAULT 'kk',
            centro TEXT NOT NULL,
            semana_etiqueta TEXT NOT NULL,
            fecha TEXT NOT NULL,
            dow INTEGER NOT NULL,
            horas REAL,
            tsx REAL,
            importado_por TEXT,
            importado_en TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(empresa, centro, fecha)
        )
    """)
    conn.commit()
    conn.close()


def _normaliza(s):
    s = (s or "").strip().upper()
    for a, b in (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("Ü", "U")):
        s = s.replace(a, b)
    return s


_SEMANA_RE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})$")


def _fechas_semana(semana_etiqueta, anio):
    """"27 - 02/08" + año -> (fecha_lunes, fecha_domingo) ISO. El Excel no
    trae año (solo el mes en el nombre del archivo, p.ej. "TPLH AGOSTO"), lo
    da quien importa. La semana puede cruzar de mes (día de inicio > día de
    fin de semana), en cuyo caso el inicio es del mes anterior."""
    m = _SEMANA_RE.match((semana_etiqueta or "").strip())
    if not m:
        return None, None
    d_ini, d_fin, mes_fin = (int(x) for x in m.groups())
    try:
        fin = datetime.date(anio, mes_fin, d_fin)
    except ValueError:
        return None, None
    if d_ini > d_fin:
        mes_ini = mes_fin - 1 if mes_fin > 1 else 12
        anio_ini = anio if mes_fin > 1 else anio - 1
    else:
        mes_ini, anio_ini = mes_fin, anio
    try:
        inicio = datetime.date(anio_ini, mes_ini, d_ini)
    except ValueError:
        return None, None
    return inicio.isoformat(), fin.isoformat()


def _leer_filas(contenido):
    wb = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    filas = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return filas


def importar_tplh_excel(contenido, nombre_archivo, anio, subido_por, empresa="kk"):
    """El Excel trae, para cada centro, un bloque de 3 tablas lado a lado
    (mismas filas = mismas semanas): horas planificadas, TSX vendidos, TPLH
    resultante (ya calculado en el Excel, aquí se recalcula por si acaso en
    vez de fiarse del valor de la celda). Un centro nuevo empieza en la
    columna A con su nombre; sus cabeceras de columna (LUNES..DOMINGO) están
    2 filas más abajo, en 3 bloques de columnas."""
    try:
        filas = _leer_filas(contenido)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo Excel: {exc}")
    if not filas:
        raise ValueError("El archivo está vacío")

    conn = get_connection()
    total_filas = 0
    centros_vistos = set()
    semanas_sin_reconocer = set()
    i = 0
    while i < len(filas):
        fila = filas[i]
        nombre_centro = _normaliza(fila[0]) if fila and fila[0] else None
        if nombre_centro in CENTROS_TPLH_A_CORTO:
            centro = CENTROS_TPLH_A_CORTO[nombre_centro]
            centros_vistos.add(centro)
            # Cabecera de columnas 1 fila más abajo: L2.. trae "SEMANA" en la
            # columna que marca el inicio de cada uno de los 3 bloques.
            cab = filas[i + 1] if i + 1 < len(filas) else []
            idx_horas = 1  # columna B: "SEMANA" del bloque de horas
            idx_tsx = next((j for j, v in enumerate(cab) if _normaliza(v) == "SEMANA" and j > idx_horas), None)
            if idx_tsx is None:
                i += 1
                continue
            j = i + 2
            while j < len(filas):
                fila_semana = filas[j]
                if not fila_semana or not fila_semana[idx_horas]:
                    break
                semana_etiqueta = str(fila_semana[idx_horas]).strip()
                fecha_lunes, _ = _fechas_semana(semana_etiqueta, anio)
                if fecha_lunes is None:
                    semanas_sin_reconocer.add(semana_etiqueta)
                    j += 1
                    continue
                lunes = datetime.date.fromisoformat(fecha_lunes)
                for dow in range(7):
                    horas = fila_semana[idx_horas + 1 + dow] if idx_horas + 1 + dow < len(fila_semana) else None
                    tsx = fila_semana[idx_tsx + 1 + dow] if idx_tsx + 1 + dow < len(fila_semana) else None
                    if horas is None and tsx is None:
                        continue
                    fecha = (lunes + datetime.timedelta(days=dow)).isoformat()
                    conn.execute("""
                        INSERT INTO planificador_tplh_dias
                            (empresa, centro, semana_etiqueta, fecha, dow, horas, tsx, importado_por)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(empresa, centro, fecha) DO UPDATE SET
                            semana_etiqueta = excluded.semana_etiqueta,
                            horas = excluded.horas,
                            tsx = excluded.tsx,
                            importado_por = excluded.importado_por,
                            importado_en = datetime('now')
                    """, (empresa, centro, semana_etiqueta, fecha, dow,
                          float(horas) if horas is not None else None,
                          float(tsx) if tsx is not None else None, subido_por))
                    total_filas += 1
                j += 1
            i = j
        else:
            i += 1
    conn.commit()
    conn.close()
    if not centros_vistos:
        raise ValueError(
            "No se reconoció ningún centro en el archivo. Se esperaba el formato del TPLH "
            "mensual (un bloque por centro, con PARQUE SUR/PRINCESA/LA GAVIA/CALEIDO/GRAN PLAZA/PLENILUNIO)."
        )
    return {
        "filas": total_filas,
        "centros": sorted(centros_vistos),
        "semanas_sin_reconocer": sorted(semanas_sin_reconocer),
    }


def get_historico(empresa, centro, meses=6):
    """Semanas ya importadas para un centro, más recientes primero --
    agrupadas por semana_etiqueta para que el frontend pinte la misma tabla
    de 3 bloques que el Excel original (horas/tsx/tplh)."""
    conn = get_connection()
    desde = (datetime.date.today() - datetime.timedelta(days=meses * 31)).isoformat()
    rows = conn.execute("""
        SELECT semana_etiqueta, fecha, dow, horas, tsx FROM planificador_tplh_dias
        WHERE empresa = ? AND centro = ? AND fecha >= ?
        ORDER BY fecha
    """, (empresa, centro, desde)).fetchall()
    conn.close()
    semanas = {}
    for r in rows:
        s = semanas.setdefault(r["semana_etiqueta"], {"semana": r["semana_etiqueta"], "dias": [None] * 7})
        s["dias"][r["dow"]] = {"fecha": r["fecha"], "horas": r["horas"], "tsx": r["tsx"]}
    out = []
    for s in semanas.values():
        horas_tot = sum(d["horas"] for d in s["dias"] if d and d["horas"] is not None)
        tsx_tot = sum(d["tsx"] for d in s["dias"] if d and d["tsx"] is not None)
        s["horas_totales"] = round(horas_tot, 1)
        s["tsx_totales"] = round(tsx_tot, 1)
        s["tplh_medio"] = round(tsx_tot / horas_tot, 2) if horas_tot else None
        out.append(s)
    out.sort(key=lambda s: s["dias"][0]["fecha"] if s["dias"][0] else "")
    return out


def proyeccion(empresa, centro, fecha_lunes, semanas_atras=12):
    """Para la semana que empieza en `fecha_lunes`: TSX medio histórico de
    cada día de la semana (mismas fechas de años anteriores cuentan igual
    que semanas recientes -- no hay datos suficientes todavía para separar
    por temporada, ver docstring del módulo) dividido entre el objetivo de
    transacciones/hora YA configurado en "Horario del centro" -> horas
    sugeridas por día. Sin objetivo configurado, o sin histórico, no hay
    proyección posible (se avisa en vez de inventar un número)."""
    cfg = planificador_module.get_config(empresa, centro)
    objetivo = cfg.get("objetivo_transacciones_hora")
    conn = get_connection()
    desde = (datetime.date.fromisoformat(fecha_lunes) - datetime.timedelta(days=semanas_atras * 7)).isoformat()
    rows = conn.execute("""
        SELECT dow, AVG(tsx) AS tsx_medio, COUNT(*) AS n
        FROM planificador_tplh_dias
        WHERE empresa = ? AND centro = ? AND fecha >= ? AND fecha < ? AND tsx IS NOT NULL
        GROUP BY dow
    """, (empresa, centro, desde, fecha_lunes)).fetchall()
    conn.close()
    por_dow = {r["dow"]: {"tsx_medio": round(r["tsx_medio"], 1), "n_semanas": r["n"]} for r in rows}
    dias = []
    lunes = datetime.date.fromisoformat(fecha_lunes)
    for dow in range(7):
        info = por_dow.get(dow)
        tsx_medio = info["tsx_medio"] if info else None
        horas_sugeridas = round(tsx_medio / objetivo, 1) if (tsx_medio is not None and objetivo) else None
        dias.append({
            "fecha": (lunes + datetime.timedelta(days=dow)).isoformat(),
            "tsx_previsto": tsx_medio,
            "n_semanas_con_dato": info["n_semanas"] if info else 0,
            "horas_sugeridas": horas_sugeridas,
        })
    return {
        "objetivo_transacciones_hora": objetivo,
        "sin_objetivo": objetivo is None,
        "dias": dias,
    }


ensure_tplh_tables()
