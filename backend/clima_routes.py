from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import auth as auth_module
import clima as clima_module
from auth_routes import get_current_user
from clima_pdf import generar_pdf

router = APIRouter()


def _modulo_para_empresa(empresa: str) -> str:
    return "saona_clima" if empresa == "saona" else "clima"


def require_clima(empresa: str = "kk", user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Clima Laboral")
    return user


def require_clima_oleada(oleada_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Para rutas que ya traen oleada_id en el path: la empresa se resuelve
    de la propia oleada (no hace falta que el frontend la repita en la URL),
    y así no hay forma de pedir el reporte de una oleada de la otra empresa
    aunque se adivine el id."""
    empresa = clima_module.get_oleada_empresa(oleada_id) or "kk"
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Clima Laboral")
    return user


@router.get("/oleadas")
def list_oleadas_route(empresa: str = "kk", _user: dict = Depends(require_clima)):
    return clima_module.list_oleadas(empresa)


@router.get("/{oleada_id}/centros")
def list_centros_route(oleada_id: int, _user: dict = Depends(require_clima_oleada)):
    return clima_module.list_centros(oleada_id)


@router.get("/{oleada_id}/por-centro")
def por_centro_route(oleada_id: int, _user: dict = Depends(require_clima_oleada)):
    return clima_module.compute_por_centro(oleada_id)


@router.post("/importar")
async def importar_route(
    file: UploadFile = File(...),
    nueva_oleada: bool = Form(default=False),
    empresa: str = Form(default="kk"),
    user: dict = Depends(get_current_user),
):
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Clima Laboral")
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = clima_module.import_excel(content, file.filename, user["username"], nueva_oleada, empresa=empresa)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/{oleada_id}/reporte")
def reporte_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_clima_oleada)):
    try:
        return clima_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{oleada_id}/reporte.pdf")
def reporte_pdf_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_clima_oleada)):
    try:
        reporte = clima_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    empresa = clima_module.get_oleada_empresa(oleada_id) or "kk"
    pdf_bytes = generar_pdf(reporte, empresa=empresa)
    nombre = f"clima_laboral_{centro or 'global'}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
