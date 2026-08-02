from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import auth as auth_module
import entrevistas as entrevistas_module
from auth_routes import get_current_user
from entrevistas_pdf import generar_pdf


class SalidaIn(BaseModel):
    centro: str
    nombre: str
    fecha_baja: str


class MatchIn(BaseModel):
    respuesta_id: int
    salida_id: int


class MotivoIn(BaseModel):
    motivo: str


class CentroIn(BaseModel):
    centro: str

router = APIRouter()


def _modulo_para_empresa(empresa: str) -> str:
    return "saona_informes" if empresa == "saona" else "informes"


def require_entrevistas(empresa: str = "kk", user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Entrevistas de Salida")
    return user


def require_entrevistas_oleada(oleada_id: int, user: dict = Depends(get_current_user)) -> dict:
    empresa = entrevistas_module.get_oleada_empresa(oleada_id) or "kk"
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Entrevistas de Salida")
    return user


@router.get("/oleadas")
def list_oleadas_route(empresa: str = "kk", _user: dict = Depends(require_entrevistas)):
    return entrevistas_module.list_oleadas(empresa)


@router.get("/centros-conocidos")
def list_centros_conocidos_route(empresa: str = "kk", _user: dict = Depends(require_entrevistas)):
    return entrevistas_module.list_centros_conocidos(empresa)


@router.get("/{oleada_id}/centros")
def list_centros_route(oleada_id: int, _user: dict = Depends(require_entrevistas_oleada)):
    return entrevistas_module.list_centros(oleada_id)


@router.post("/importar")
async def importar_route(
    file: UploadFile = File(...),
    nueva_oleada: bool = Form(default=False),
    empresa: str = Form(default="kk"),
    user: dict = Depends(get_current_user),
):
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Entrevistas de Salida")
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = entrevistas_module.import_excel(content, file.filename, user["username"], nueva_oleada, empresa=empresa)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/{oleada_id}/reporte")
def reporte_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    try:
        return entrevistas_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{oleada_id}/evolucion")
def evolucion_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    try:
        return entrevistas_module.compute_evolucion(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{oleada_id}/salidas")
def crear_salida_route(oleada_id: int, body: SalidaIn, _user: dict = Depends(require_entrevistas_oleada)):
    if not body.centro.strip() or not body.nombre.strip() or not body.fecha_baja.strip():
        raise HTTPException(status_code=400, detail="Centro, nombre y fecha de baja son obligatorios")
    entrevistas_module.add_salida(oleada_id, body.centro.strip(), body.nombre.strip(), body.fecha_baja.strip())
    return {"ok": True}


@router.post("/{oleada_id}/matches")
def crear_match_route(oleada_id: int, body: MatchIn, _user: dict = Depends(require_entrevistas_oleada)):
    entrevistas_module.set_match_manual(body.respuesta_id, body.salida_id)
    return {"ok": True}


@router.delete("/{oleada_id}/matches/{respuesta_id}")
def borrar_match_route(oleada_id: int, respuesta_id: int, _user: dict = Depends(require_entrevistas_oleada)):
    entrevistas_module.quitar_match_manual(respuesta_id)
    return {"ok": True}


@router.delete("/{oleada_id}/respuestas/{respuesta_id}")
def borrar_respuesta_route(oleada_id: int, respuesta_id: int, _user: dict = Depends(require_entrevistas_oleada)):
    entrevistas_module.borrar_respuesta(respuesta_id)
    return {"ok": True}


@router.get("/{oleada_id}/respuestas")
def list_respuestas_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    return entrevistas_module.list_respuestas_con_motivo(oleada_id, centro)


@router.patch("/{oleada_id}/respuestas/{respuesta_id}/motivo")
def update_motivo_route(oleada_id: int, respuesta_id: int, body: MotivoIn, _user: dict = Depends(require_entrevistas_oleada)):
    if not body.motivo.strip():
        raise HTTPException(status_code=400, detail="El motivo no puede estar vacío")
    try:
        entrevistas_module.update_motivo(respuesta_id, body.motivo.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.patch("/{oleada_id}/respuestas/{respuesta_id}/centro")
def update_centro_route(oleada_id: int, respuesta_id: int, body: CentroIn, _user: dict = Depends(require_entrevistas_oleada)):
    if not body.centro.strip():
        raise HTTPException(status_code=400, detail="El centro no puede estar vacío")
    try:
        entrevistas_module.update_centro(respuesta_id, body.centro)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.get("/{oleada_id}/reporte.pdf")
def reporte_pdf_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    try:
        reporte = entrevistas_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    empresa = entrevistas_module.get_oleada_empresa(oleada_id) or "kk"
    pdf_bytes = generar_pdf(reporte, empresa=empresa)
    nombre = f"entrevista_salida_{centro or 'global'}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
