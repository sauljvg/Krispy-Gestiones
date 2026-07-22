import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import informes as informes_module
from auth_routes import get_current_user
from db import get_connection

router = APIRouter()


def require_todo(user: dict = Depends(get_current_user)) -> dict:
    if user["rol"] not in ("admin", "rrhh"):
        raise HTTPException(status_code=403, detail="No tienes acceso a Informes")
    return user


class NewTipoBody(BaseModel):
    clave: str
    nombre: str


class CompartirBody(BaseModel):
    respuesta_ids: list[int]
    usuario_id: int


class HojaOcultaBody(BaseModel):
    hoja: str
    oculta: bool


class HojaNombreBody(BaseModel):
    hoja: str


@router.get("/tipos")
def list_tipos_route(_user: dict = Depends(require_todo)):
    return informes_module.list_tipos()


@router.post("/tipos")
def create_tipo_route(body: NewTipoBody, _user: dict = Depends(require_todo)):
    try:
        tipo_id = informes_module.create_tipo(body.clave, body.nombre)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo crear el tipo (¿clave duplicada?): {exc}")
    return {"ok": True, "id": tipo_id}


@router.get("/usuarios-para-compartir")
def usuarios_para_compartir_route(_user: dict = Depends(require_todo)):
    conn = get_connection()
    rows = conn.execute("SELECT id, username, nombre, rol FROM usuarios ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/compartidos")
def get_compartidos_route(user: dict = Depends(get_current_user)):
    return informes_module.get_compartidos_con(user["id"])


@router.get("/{tipo_clave}/hojas")
def list_hojas_route(tipo_clave: str, _user: dict = Depends(require_todo)):
    try:
        return informes_module.list_hojas(tipo_clave)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{tipo_clave}/hojas/ocultar")
def set_hoja_oculta_route(tipo_clave: str, body: HojaOcultaBody, _user: dict = Depends(require_todo)):
    try:
        informes_module.set_hoja_oculta(tipo_clave, body.hoja, body.oculta)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{tipo_clave}/hojas/principal")
def set_hoja_conteo_route(tipo_clave: str, body: HojaNombreBody, _user: dict = Depends(require_todo)):
    try:
        informes_module.set_hoja_conteo(tipo_clave, body.hoja)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{tipo_clave}/hojas/eliminar")
def eliminar_hoja_route(tipo_clave: str, body: HojaNombreBody, _user: dict = Depends(require_todo)):
    try:
        informes_module.eliminar_hoja(tipo_clave, body.hoja)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{tipo_clave}/importar")
async def importar_route(tipo_clave: str, file: UploadFile = File(...), user: dict = Depends(require_todo)):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = informes_module.import_excel(tipo_clave, content, file.filename, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/{tipo_clave}/respuestas")
def respuestas_route(
    tipo_clave: str,
    hoja: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=1000),
    q: str | None = None,
    orden: str | None = None,
    orden_dir: str = "asc",
    fecha_col: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    _user: dict = Depends(require_todo),
):
    try:
        return informes_module.get_respuestas(
            tipo_clave, hoja=hoja, page=page, page_size=page_size, q=q,
            orden=orden, orden_dir=orden_dir,
            fecha_col=fecha_col, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/respuestas/{respuesta_id}/cv")
async def subir_cv_route(respuesta_id: int, file: UploadFile = File(...), _user: dict = Depends(require_todo)):
    content = await file.read()
    try:
        informes_module.guardar_cv(respuesta_id, file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.get("/respuestas/{respuesta_id}/cv")
def descargar_cv_route(respuesta_id: int, user: dict = Depends(get_current_user)):
    tiene_acceso = user["rol"] in ("admin", "rrhh") or informes_module.usuario_tiene_acceso_respuesta(
        user["id"], respuesta_id
    )
    if not tiene_acceso:
        raise HTTPException(status_code=403, detail="No tienes acceso a este CV")
    respuesta = informes_module.get_respuesta(respuesta_id)
    if respuesta is None or not respuesta["cv_ruta"] or not os.path.exists(respuesta["cv_ruta"]):
        raise HTTPException(status_code=404, detail="Este candidato no tiene CV subido")
    return FileResponse(
        respuesta["cv_ruta"],
        filename=respuesta["cv_nombre_original"] or "cv",
        media_type="application/octet-stream",
    )


@router.post("/compartir")
def compartir_route(body: CompartirBody, user: dict = Depends(require_todo)):
    informes_module.compartir_respuestas(body.respuesta_ids, body.usuario_id, user["username"])
    return {"ok": True}


@router.delete("/compartir/{respuesta_id}/{usuario_id}")
def dejar_de_compartir_route(respuesta_id: int, usuario_id: int, _user: dict = Depends(require_todo)):
    informes_module.dejar_de_compartir(respuesta_id, usuario_id)
    return {"ok": True}
