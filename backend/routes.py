import os
import shutil
import sys
import tempfile
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

import analytics
import personal as personal_module
from auth_routes import require_admin
from db import dict_rows, get_connection, get_ultima_importacion_takeout, set_ultima_importacion_takeout
from request_context import tiendas_permitidas_actual
from utils import paginate, read_transactions_xlsx, rows_to_csv, rows_to_xlsx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scraper")))
import import_takeout as import_takeout_module  # noqa: E402

router = APIRouter()


def build_filters(rating, sentiment, date_from, date_to, q, staff=None, tienda=None, solo_google=False):
    clauses = []
    params = []

    if solo_google:
        # NULL cuenta como "visible" (valor por defecto antes de reconciliar
        # nunca esa tienda) — solo se excluye lo marcado explícitamente 0.
        clauses.append("(visible_en_google IS NULL OR visible_en_google = 1)")

    # Gerentes/area managers con tiendas asignadas solo pueden ver esas
    # tiendas, sin importar qué pida el query param — si piden una que no
    # les corresponde, la consulta no devuelve nada en vez de filtrar mal.
    tiendas_permitidas = tiendas_permitidas_actual.get()
    if tiendas_permitidas:
        if tienda:
            if tienda not in tiendas_permitidas:
                clauses.append("1=0")
            else:
                clauses.append("tienda = ?")
                params.append(tienda)
        else:
            placeholders = ",".join(["?"] * len(tiendas_permitidas))
            clauses.append(f"tienda IN ({placeholders})")
            params.extend(tiendas_permitidas)
    elif tienda:
        clauses.append("tienda = ?")
        params.append(tienda)

    if rating is not None:
        clauses.append("calificacion_num = ?")
        params.append(rating)
    if sentiment:
        clauses.append("sentiment = ?")
        params.append(sentiment)
    if date_from:
        clauses.append("fecha_datetime >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("fecha_datetime <= ?")
        params.append(date_to)
    if q:
        clauses.append("(texto LIKE ? OR autor LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    if staff:
        # El filtro por empleado usa coincidencia de palabra completa sobre
        # el TEXTO (nunca el autor), igual que el ranking de "Personal
        # mencionado" — así los números siempre coinciden. Requiere tienda
        # porque el mismo nombre puede ser una persona distinta en cada local;
        # sin tienda no hay forma de saber a qué plantilla pertenece.
        ids = analytics.staff_matching_review_ids(tienda, staff, where, params) if tienda else []
        if ids:
            placeholders = ",".join(["?"] * len(ids))
            clauses.append(f"review_id IN ({placeholders})")
            params.extend(ids)
        else:
            clauses.append("1=0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    return where, params


# Mismo orden que analytics.DIAS_ES (lunes primero) -> valor que devuelve
# strftime('%w', ...) en SQLite (0=domingo..6=sábado).
DIA_ES_A_SQLITE = {
    "Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4,
    "Viernes": 5, "Sábado": 6, "Domingo": 0,
}


def apply_hora_dia(where, params, hora, dia_semana):
    """Añade el filtro de hora del día / día de la semana (clic en el
    gráfico de "Horario de reseñas") sobre lo que ya calculó build_filters.
    Solo afecta a reseñas con fecha_hora (las importadas de Takeout)."""
    clauses = []
    extra_params = []
    if hora is not None:
        clauses.append("CAST(strftime('%H', fecha_hora) AS INTEGER) = ?")
        extra_params.append(hora)
    if dia_semana:
        dow = DIA_ES_A_SQLITE.get(dia_semana)
        if dow is None:
            raise HTTPException(400, f"Día de la semana no reconocido: '{dia_semana}'")
        clauses.append("CAST(strftime('%w', fecha_hora) AS INTEGER) = ?")
        extra_params.append(dow)
    if not clauses:
        return where, params
    joined = " AND ".join(clauses)
    new_where = where + (" AND " if where else " WHERE ") + joined
    return new_where, params + extra_params


@router.get("/reviews")
def list_reviews(
    page: int = 1,
    page_size: int = 20,
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    hora: int | None = Query(default=None, ge=0, le=23),
    dia_semana: str | None = None,
    sort: str = Query(default="recientes", pattern="^(recientes|antiguas|mejor|peor)$"),
    solo_google: bool = False,
):
    page, page_size, offset = paginate(page, page_size)
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    where, params = apply_hora_dia(where, params, hora, dia_semana)

    order_by = {
        "recientes": "fecha_datetime DESC",
        "antiguas": "fecha_datetime ASC",
        "mejor": "calificacion_num DESC",
        "peor": "calificacion_num ASC",
    }[sort]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS total FROM reviews {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(
        f"""
        SELECT review_id, tienda, autor, fecha, fecha_datetime, fecha_hora, fecha_categoria,
               calificacion, calificacion_num, texto, es_reciente, sentiment, sentiment_score,
               respuesta_texto, respuesta_fecha, visible_en_google
        FROM reviews {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    )
    reviews = dict_rows(cur)
    conn.close()

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_paginas": (total + page_size - 1) // page_size if page_size else 0,
        "reviews": reviews,
    }


def _filtered_rows(rating, sentiment, date_from, date_to, q, staff=None, tienda=None, hora=None, dia_semana=None, solo_google=False):
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    where, params = apply_hora_dia(where, params, hora, dia_semana)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM reviews {where} ORDER BY fecha_datetime DESC", params)
    rows = dict_rows(cur)
    conn.close()
    return rows


@router.get("/reviews/export")
def export_reviews_csv(
    rating: int | None = None,
    sentiment: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    hora: int | None = Query(default=None, ge=0, le=23),
    dia_semana: str | None = None,
    solo_google: bool = False,
):
    rows = _filtered_rows(rating, sentiment, date_from, date_to, q, staff, tienda, hora, dia_semana, solo_google)
    csv_text = rows_to_csv(rows)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=krispy_kreme_reviews.csv"},
    )


@router.get("/reviews/export/xlsx")
def export_reviews_xlsx(
    rating: int | None = None,
    sentiment: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    hora: int | None = Query(default=None, ge=0, le=23),
    dia_semana: str | None = None,
    solo_google: bool = False,
):
    rows = _filtered_rows(rating, sentiment, date_from, date_to, q, staff, tienda, hora, dia_semana, solo_google)
    xlsx_bytes = rows_to_xlsx(rows)
    return Response(
        xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=krispy_kreme_reviews.xlsx"},
    )


@router.get("/stats")
def stats(
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    solo_google: bool = False,
):
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    result = analytics.get_stats(where, params)
    if tienda:
        total_google = analytics.get_store_total_google(tienda)
        result["total_google"] = total_google
        result["completo"] = bool(total_google and result["total"] >= total_google)
    else:
        result["total_google"] = None
        result["completo"] = analytics.get_all_stores_completeness()
        # Barras apiladas de "Distribución de estrellas" — solo aporta algo
        # en "Todas" (con una tienda ya es una única serie, igual que la
        # aggregada de arriba).
        result["distribucion_por_tienda"] = analytics.get_distribucion_por_tienda(where, params)
    return result


@router.get("/timeline-horas")
def timeline_horas(
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    solo_google: bool = False,
):
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    resultado = analytics.get_hourly_distribution(where, params)
    if not tienda:
        resultado["por_tienda"] = analytics.get_hourly_distribution_por_tienda(where, params)
    return resultado


@router.get("/rating-progress")
def rating_progress(
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    solo_google: bool = False,
):
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    return analytics.get_rating_progress(where, params)


@router.get("/timeline")
def timeline(
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    solo_google: bool = False,
):
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    resultado = {"timeline": analytics.get_timeline(where, params)}
    if not tienda:
        # Desglose por tienda solo tiene sentido en "Todas" — con una tienda
        # ya elegida sería una única línea idéntica a "timeline". Se calcula
        # con un `where` SIN fecha (histórico completo) para que el
        # acumulado no arranque en 0 al inicio del rango — ver el docstring
        # de get_timeline_por_tienda.
        where_sin_fecha, params_sin_fecha = build_filters(rating, sentiment, None, None, q, staff, tienda, solo_google)
        resultado["por_tienda"] = analytics.get_timeline_por_tienda(where_sin_fecha, params_sin_fecha, date_from, date_to)
    return resultado


@router.get("/timeline-evolucion")
def timeline_evolucion(date_from: str, date_to: str, solo_google: bool = False):
    """Comparativa de reseñas/valoración ACUMULADAS por tienda entre dos
    fechas — para la vista "Todas" con Desde/Hasta puestos: cuánto creció
    cada tienda en ese periodo (ver analytics.get_evolucion_por_tienda)."""
    return {"evolucion": analytics.get_evolucion_por_tienda(date_from, date_to, solo_google)}


@router.get("/keywords")
def keywords(
    limit: int = 20,
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    staff: str | None = None,
    tienda: str | None = None,
    solo_google: bool = False,
):
    where, params = build_filters(rating, sentiment, date_from, date_to, q, staff, tienda, solo_google)
    return {"keywords": analytics.get_keywords(limit, where, params)}


@router.get("/staff-mentions")
def staff_mentions(
    rating: int | None = None,
    sentiment: str | None = Query(default=None, pattern="^(positivo|neutral|negativo)$"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    tienda: str | None = None,
    solo_google: bool = False,
):
    # Nota: no acepta `staff` — esta es la lista base que alimenta los clics
    # del ranking; filtrarla por staff sería circular.
    # El ranking de personal solo tiene sentido POR TIENDA (el mismo nombre de
    # pila puede ser una persona distinta en cada local). Con una tienda
    # seleccionada se cuenta solo ahí; con "Todas" se cuenta cada una POR SU
    # PROPIA tienda por separado (nunca mezcladas) y se etiqueta cada fila.
    where, params = build_filters(rating, sentiment, date_from, date_to, q, tienda=tienda, solo_google=solo_google)
    if tienda:
        return analytics.get_staff_mentions(tienda, where, params)
    return analytics.get_staff_mentions_all_stores(where, params)


@router.get("/stores")
def stores(
    order_by: str = Query(default="total", pattern="^(total|tasa)$"),
    mes: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    solo_google: bool = False,
):
    """Tiendas presentes en la BD con su nº de reseñas — alimenta el selector
    de tienda y el ranking comparativo entre locales (`order_by=tasa` para
    ordenar por reseñas/transacciones). Con `mes` (YYYY-MM), tanto las
    reseñas como las transacciones se acotan a ese mes en vez de mostrar el
    acumulado histórico."""
    return {"stores": analytics.get_store_stats(order_by, mes, solo_google)}


MES_PATTERN = r"^\d{4}-\d{2}$"


@router.get("/transactions")
def get_transactions(mes: str = Query(pattern=MES_PATTERN)):
    """Transacciones cargadas para un mes concreto, por tienda — alimenta los
    inputs editables del ranking al cambiar de mes."""
    return {"mes": mes, "transacciones": analytics.get_month_transactions(mes)}


class TransactionsIn(BaseModel):
    tienda: str
    mes: str = Field(pattern=MES_PATTERN)
    transacciones: int


@router.post("/transactions")
def set_transactions(body: TransactionsIn):
    if body.transacciones < 0:
        raise HTTPException(400, "transacciones no puede ser negativo")
    analytics.set_store_transactions(body.tienda, body.mes, body.transacciones)
    return {"ok": True}


# El botón "Actualizar"/"Escaneo completo" que lanzaba scraper_v2.py desde
# aquí se quitó: el contenedor de producción no tiene Chrome instalado, así
# que en Railway ese botón nunca funcionó de verdad (fallaba en silencio).
# El scraping de Maps sigue existiendo como herramienta de terminal en local
# (scraper/scraper_v2.py) para quien tenga Chrome con sesión propia — la vía
# soportada dentro de la app es "Importar Takeout".


class ReconciliacionIn(BaseModel):
    tienda: str
    no_visibles: list[str] = []
    vistas_ahora: list[str] = []


@router.post("/reviews/reconciliacion")
def marcar_reconciliacion(body: ReconciliacionIn):
    """Recibe el resultado de `python scraper_v2.py <tienda> --reconciliar`
    corrido en local y lo aplica a la BD real de producción — un commit a
    GitHub no sirve para esto (la base de datos vive fuera de git a
    propósito, ver DATA_DIR en db.py). `no_visibles`: review_id que la
    pasada completa en vivo no encontró (se marcan visible_en_google=0, así
    el toggle "solo Google" del dashboard las excluye de todo: totales,
    promedio, %positivas, ranking). `vistas_ahora`: review_id que sí se
    vieron, para desmarcar las que una reconciliación anterior había
    marcado como no visibles y que desde entonces reaparecieron."""
    conn = get_connection()
    if body.no_visibles:
        placeholders = ",".join("?" * len(body.no_visibles))
        conn.execute(
            f"UPDATE reviews SET visible_en_google = 0 WHERE review_id IN ({placeholders})",
            body.no_visibles,
        )
    if body.vistas_ahora:
        placeholders = ",".join("?" * len(body.vistas_ahora))
        conn.execute(
            f"UPDATE reviews SET visible_en_google = 1 WHERE review_id IN ({placeholders})",
            body.vistas_ahora,
        )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "marcadas_no_visibles": len(body.no_visibles),
        "marcadas_visibles": len(body.vistas_ahora),
    }


@router.post("/transactions/upload")
def upload_transactions(file: UploadFile = File(...), mes: str | None = Query(default=None, pattern=MES_PATTERN)):
    try:
        rows = read_transactions_xlsx(file.file.read(), default_mes=mes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rows:
        raise HTTPException(400, "No se encontraron filas válidas (columnas esperadas: tienda, mes, transacciones)")
    analytics.bulk_set_store_transactions(rows)
    return {"ok": True, "actualizadas": len(rows)}


@router.post("/import/takeout")
def import_takeout(file: UploadFile = File(...)):
    """Sube el .zip de un export de Google Takeout ("Perfil de Empresa en
    Google") y lo importa: lee todas las reseñas oficiales de cada tienda y
    solo inserta las que no teníamos (por review_id), sin duplicar."""
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Sube el archivo .zip que descarga Google Takeout, sin extraer.")

    tmp_dir = tempfile.mkdtemp(prefix="kt_import_")
    try:
        zip_path = os.path.join(tmp_dir, "upload.zip")
        with open(zip_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        extract_dir = os.path.join(tmp_dir, "x")
        # Los nombres de archivo de Takeout (el ID completo de cada reseña)
        # son tan largos que, combinados con la ruta del directorio temporal,
        # superan el límite de 260 caracteres de Windows. El prefijo \\?\
        # hace que Windows use la API de rutas largas sin ese límite — pero
        # SOLO existe en Windows: en Linux (producción) esas barras invertidas
        # se tratan como caracteres normales del nombre, así que el zip se
        # extraía en una carpeta con un nombre corrupto fuera de extract_dir
        # y luego no se encontraba nada dentro.
        extract_target = ("\\\\?\\" + os.path.abspath(extract_dir)) if os.name == "nt" else extract_dir
        try:
            with zipfile.ZipFile(zip_path) as zf:
                # El export de Takeout incluye las fotos adjuntas a cada
                # reseña ("media-*"), que pueden pesar >150 MB y que el
                # importador nunca lee (solo usa los reviews*.json). Se
                # omiten al extraer para no gastar de más disco/memoria del
                # contenedor con archivos que no hacen falta.
                miembros = [m for m in zf.infolist() if not os.path.basename(m.filename).lower().startswith("media-")]
                zf.extractall(extract_target, members=miembros)
        except zipfile.BadZipFile:
            raise HTTPException(400, "El archivo no es un .zip válido.")

        try:
            report = import_takeout_module.run_import(extract_dir)
        except SystemExit as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            # El 500 genérico de Starlette no manda detail en JSON, así que
            # en producción llegaba al navegador completamente vacío y no
            # daba ninguna pista de qué fallaba de verdad. Se captura aquí
            # para que el propio error diga qué excepción fue.
            raise HTTPException(500, f"{type(e).__name__}: {e}")

        total_nuevas = sum(r["nuevas"] for r in report)
        set_ultima_importacion_takeout()
        return {"ok": True, "total_nuevas": total_nuevas, "tiendas": report}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


class PersonalIn(BaseModel):
    tienda: str
    nombre_canonico: str
    variantes: list[str] = []
    fecha_inicio: str | None = None


class PersonalEditIn(BaseModel):
    nombre_canonico: str
    variantes: list[str]


class SugerirVariantesIn(BaseModel):
    nombre: str


class SalidaPersonalIn(BaseModel):
    asignacion_id: int
    fecha: str
    tipo: str  # "baja" | "traslado"
    tienda_destino: str | None = None


@router.get("/personal")
def listar_personal_route(tienda: str | None = None, _admin: dict = Depends(require_admin)):
    return {"personal": personal_module.list_personal(tienda)}


@router.post("/personal")
def crear_personal_route(body: PersonalIn, _admin: dict = Depends(require_admin)):
    try:
        return personal_module.crear_personal(body.tienda, body.nombre_canonico, body.variantes, body.fecha_inicio)
    except personal_module.PersonalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/personal/sugerir-variantes")
def sugerir_variantes_route(body: SugerirVariantesIn, _admin: dict = Depends(require_admin)):
    try:
        return {"variantes": personal_module.sugerir_variantes(body.nombre)}
    except personal_module.PersonalError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.patch("/personal/{personal_id}")
def editar_personal_route(personal_id: int, body: PersonalEditIn, _admin: dict = Depends(require_admin)):
    try:
        personal_module.actualizar_personal(personal_id, body.nombre_canonico, body.variantes)
        return {"ok": True}
    except personal_module.PersonalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/personal/salida")
def salida_personal_route(body: SalidaPersonalIn, _admin: dict = Depends(require_admin)):
    try:
        return personal_module.dar_salida(body.asignacion_id, body.fecha, body.tipo, body.tienda_destino)
    except personal_module.PersonalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/personal/{personal_id}")
def eliminar_personal_route(personal_id: int, _admin: dict = Depends(require_admin)):
    personal_module.eliminar_personal(personal_id)
    return {"ok": True}


@router.get("/import/takeout/ultima")
def ultima_importacion_takeout_route():
    """Fecha/hora de la última importación de Takeout — visible para
    cualquiera con acceso a Reseñas (hereda require_resenas del router)."""
    return {"ultima_importacion": get_ultima_importacion_takeout()}
