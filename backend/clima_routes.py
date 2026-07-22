from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import clima as clima_module
from auth_routes import get_current_user
from clima_pdf import generar_pdf

router = APIRouter()


def require_todo(user: dict = Depends(get_current_user)) -> dict:
    if user["rol"] not in ("admin", "rrhh"):
        raise HTTPException(status_code=403, detail="No tienes acceso a Clima Laboral")
    return user


@router.get("/oleadas")
def list_oleadas_route(_user: dict = Depends(require_todo)):
    return clima_module.list_oleadas()


@router.get("/{oleada_id}/centros")
def list_centros_route(oleada_id: int, _user: dict = Depends(require_todo)):
    return clima_module.list_centros(oleada_id)


@router.post("/importar")
async def importar_route(
    file: UploadFile = File(...),
    nueva_oleada: bool = Form(default=False),
    user: dict = Depends(require_todo),
):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = clima_module.import_excel(content, file.filename, user["username"], nueva_oleada)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/{oleada_id}/reporte")
def reporte_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_todo)):
    try:
        return clima_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{oleada_id}/reporte.pdf")
def reporte_pdf_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_todo)):
    try:
        reporte = clima_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    pdf_bytes = generar_pdf(reporte)
    nombre = f"clima_laboral_{centro or 'global'}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
