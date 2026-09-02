from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import auth as auth_module
import clima as clima_module
from auth_routes import get_current_user, require_admin
from clima_pdf import generar_pdf

router = APIRouter()


class NuevaOleadaBody(BaseModel):
    etiqueta: str
    empresa: str = "kk"
    fase: str = "completa"


class PlantillaBody(BaseModel):
    plantilla: dict[str, int]


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


@router.get("/centros-conocidos")
def list_centros_conocidos_route(_user: dict = Depends(require_clima)):
    """Para el checklist de restricción por centro en Usuarios (junto con
    tipos-informe, ver informes_routes.py) — no depende de una oleada
    concreta, así que no usa require_clima_oleada."""
    return clima_module.list_centros_conocidos()


@router.post("/oleadas")
def crear_oleada_route(body: NuevaOleadaBody, user: dict = Depends(get_current_user)):
    """Para "+ Nueva oleada de Clima Laboral" desde el editor de Tests (ver
    tests.js) -- requiere el módulo de Clima de esa empresa, no solo Tests,
    para que alguien con acceso a Tests pero sin Clima Laboral no pueda
    crear oleadas a las que luego no tiene forma de entrar."""
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(body.empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Clima Laboral")
    if not body.etiqueta.strip():
        raise HTTPException(status_code=400, detail="Ponle un nombre a la oleada")
    fase = body.fase if body.fase in ("completa", "pulso") else "completa"
    oleada_id = clima_module.crear_oleada(body.etiqueta.strip(), body.empresa, fase)
    return {"ok": True, "id": oleada_id}


class RenombrarOleadaBody(BaseModel):
    etiqueta: str


@router.put("/{oleada_id}/etiqueta")
def renombrar_oleada_route(oleada_id: int, body: RenombrarOleadaBody, _user: dict = Depends(require_admin)):
    if not body.etiqueta.strip():
        raise HTTPException(status_code=400, detail="Ponle un nombre a la oleada")
    clima_module.renombrar_oleada(oleada_id, body.etiqueta.strip())
    return {"ok": True}


@router.delete("/{oleada_id}")
def eliminar_oleada_route(oleada_id: int, _user: dict = Depends(require_admin)):
    try:
        clima_module.eliminar_oleada(oleada_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.get("/{oleada_id}/plantilla")
def get_plantilla_route(oleada_id: int, _user: dict = Depends(require_clima_oleada)):
    return clima_module.get_plantilla(oleada_id)


@router.put("/{oleada_id}/plantilla")
def set_plantilla_route(oleada_id: int, body: PlantillaBody, _user: dict = Depends(require_clima_oleada)):
    clima_module.set_plantilla(oleada_id, body.plantilla)
    return {"ok": True}


@router.get("/{oleada_id}/centros")
def list_centros_route(oleada_id: int, user: dict = Depends(require_clima_oleada)):
    return clima_module.list_centros(oleada_id, clima_module.get_centros_permitidos(user["id"]))


@router.get("/{oleada_id}/por-centro")
def por_centro_route(oleada_id: int, user: dict = Depends(require_clima_oleada)):
    return clima_module.compute_por_centro(oleada_id, clima_module.get_centros_permitidos(user["id"]))


@router.post("/importar")
async def importar_route(
    file: UploadFile = File(...),
    nueva_oleada: bool = Form(default=False),
    empresa: str = Form(default="kk"),
    user: dict = Depends(require_admin),
):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = clima_module.import_excel(content, file.filename, user["username"], nueva_oleada, empresa=empresa)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


def _validar_centro_permitido(centro, centros_permitidos):
    if centro and centros_permitidos and centro not in centros_permitidos:
        raise HTTPException(status_code=403, detail="No tienes acceso a este centro")


@router.get("/{oleada_id}/reporte")
def reporte_route(
    oleada_id: int, centro: str | None = None, solo_tipo: str | None = None,
    user: dict = Depends(require_clima_oleada),
):
    centros_permitidos = clima_module.get_centros_permitidos(user["id"])
    _validar_centro_permitido(centro, centros_permitidos)
    try:
        return clima_module.compute_reporte(oleada_id, centro, centros_permitidos, solo_tipo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{oleada_id}/reporte.pdf")
def reporte_pdf_route(
    oleada_id: int, centro: str | None = None, solo_tipo: str | None = None,
    user: dict = Depends(require_clima_oleada),
):
    centros_permitidos = clima_module.get_centros_permitidos(user["id"])
    _validar_centro_permitido(centro, centros_permitidos)
    try:
        reporte = clima_module.compute_reporte(oleada_id, centro, centros_permitidos, solo_tipo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    empresa = clima_module.get_oleada_empresa(oleada_id) or "kk"
    pdf_bytes = generar_pdf(reporte, empresa=empresa)
    nombre = f"clima_laboral_{centro or solo_tipo or 'global'}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
