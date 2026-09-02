import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import manuales as manuales_module
from auth_routes import get_current_user, require_admin

router = APIRouter()

EXTENSIONES_IMAGEN = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def require_manuales(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, "manuales"):
        raise HTTPException(status_code=403, detail="No tienes acceso a Manuales")
    return user


class ManualIn(BaseModel):
    titulo: str
    categoria: str = "General"


class PasoTextoIn(BaseModel):
    texto: str = ""
    pictograma: str | None = None


class MoverPasoIn(BaseModel):
    direccion: str  # "arriba" | "abajo"


@router.get("/pictogramas")
def list_pictogramas_route(_user: dict = Depends(require_manuales)):
    return manuales_module.PICTOGRAMAS


@router.get("")
def list_manuales_route(_user: dict = Depends(require_manuales)):
    return manuales_module.list_manuales()


@router.get("/{manual_id}")
def get_manual_route(manual_id: int, _user: dict = Depends(require_manuales)):
    manual = manuales_module.get_manual(manual_id)
    if manual is None:
        raise HTTPException(status_code=404, detail="Manual no encontrado")
    return manual


@router.get("/{manual_id}/pasos/{paso_id}/imagen")
def get_imagen_paso_route(manual_id: int, paso_id: int, _user: dict = Depends(require_manuales)):
    paso = manuales_module.get_paso(manual_id, paso_id)
    if not paso or not paso["imagen_ruta"]:
        raise HTTPException(status_code=404, detail="Este paso no tiene imagen")
    ext = os.path.splitext(paso["imagen_ruta"])[1].lower()
    return FileResponse(paso["imagen_ruta"], media_type=EXTENSIONES_IMAGEN.get(ext, "application/octet-stream"))


# ------------------------------- Solo admin -------------------------------

@router.post("")
def crear_manual_route(body: ManualIn, user: dict = Depends(require_admin)):
    if not body.titulo.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio")
    manual_id = manuales_module.crear_manual(body.titulo.strip(), body.categoria.strip(), user["username"])
    return {"ok": True, "id": manual_id}


@router.put("/{manual_id}")
def actualizar_manual_route(manual_id: int, body: ManualIn, _user: dict = Depends(require_admin)):
    if manuales_module.get_manual(manual_id) is None:
        raise HTTPException(status_code=404, detail="Manual no encontrado")
    if not body.titulo.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio")
    manuales_module.actualizar_manual(manual_id, body.titulo.strip(), body.categoria.strip())
    return {"ok": True}


@router.delete("/{manual_id}")
def eliminar_manual_route(manual_id: int, _user: dict = Depends(require_admin)):
    if manuales_module.get_manual(manual_id) is None:
        raise HTTPException(status_code=404, detail="Manual no encontrado")
    manuales_module.eliminar_manual(manual_id)
    return {"ok": True}


@router.post("/{manual_id}/pasos")
async def agregar_paso_route(
    manual_id: int,
    texto: str = Form(""),
    pictograma: str | None = Form(None),
    file: UploadFile | None = File(None),
    _user: dict = Depends(require_admin),
):
    nombre_original = ext = contenido = None
    if file is not None and file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in EXTENSIONES_IMAGEN:
            raise HTTPException(status_code=400, detail="Sube una imagen (jpg, png o webp)")
        contenido = await file.read()
        nombre_original = file.filename
    try:
        paso_id = manuales_module.agregar_paso(manual_id, texto, pictograma, nombre_original, ext, contenido)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "id": paso_id}


@router.put("/{manual_id}/pasos/{paso_id}")
def actualizar_paso_route(manual_id: int, paso_id: int, body: PasoTextoIn, _user: dict = Depends(require_admin)):
    if manuales_module.get_paso(manual_id, paso_id) is None:
        raise HTTPException(status_code=404, detail="Paso no encontrado")
    manuales_module.actualizar_paso(manual_id, paso_id, body.texto, body.pictograma)
    return {"ok": True}


@router.put("/{manual_id}/pasos/{paso_id}/imagen")
async def reemplazar_imagen_paso_route(manual_id: int, paso_id: int, file: UploadFile = File(...), _user: dict = Depends(require_admin)):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in EXTENSIONES_IMAGEN:
        raise HTTPException(status_code=400, detail="Sube una imagen (jpg, png o webp)")
    content = await file.read()
    try:
        manuales_module.reemplazar_imagen_paso(manual_id, paso_id, file.filename, ext, content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{manual_id}/pasos/{paso_id}/mover")
def mover_paso_route(manual_id: int, paso_id: int, body: MoverPasoIn, _user: dict = Depends(require_admin)):
    if body.direccion not in ("arriba", "abajo"):
        raise HTTPException(status_code=400, detail="direccion debe ser 'arriba' o 'abajo'")
    try:
        manuales_module.mover_paso(manual_id, paso_id, body.direccion)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.delete("/{manual_id}/pasos/{paso_id}")
def eliminar_paso_route(manual_id: int, paso_id: int, _user: dict = Depends(require_admin)):
    manuales_module.eliminar_paso(manual_id, paso_id)
    return {"ok": True}
