import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import boletines as boletines_module
from auth_routes import get_current_user

router = APIRouter()
router_publico = APIRouter()


def require_boletines(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, "boletines"):
        raise HTTPException(status_code=403, detail="No tienes acceso a Boletines")
    return user


EXTENSIONES_IMAGEN = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class PostIn(BaseModel):
    titulo: str
    resumen: str = ""
    contenido_html: str
    contenido_bloques: str | None = None


class ContactoIn(BaseModel):
    nombre: str
    email: str


class EnviarIn(BaseModel):
    contacto_ids: list[int]


# ------------------------------- Admin -------------------------------

@router.get("/posts")
def list_posts_route(_user: dict = Depends(require_boletines)):
    return boletines_module.list_posts()


@router.get("/posts/{post_id}")
def get_post_route(post_id: int, _user: dict = Depends(require_boletines)):
    post = boletines_module.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Boletín no encontrado")
    return post


@router.post("/posts")
def create_post_route(body: PostIn, user: dict = Depends(require_boletines)):
    if not body.titulo.strip() or not body.contenido_html.strip():
        raise HTTPException(status_code=400, detail="Título y contenido son obligatorios")
    post_id = boletines_module.create_post(
        body.titulo.strip(), body.resumen.strip(), body.contenido_html, user["username"], body.contenido_bloques
    )
    return {"ok": True, "id": post_id}


@router.put("/posts/{post_id}")
def update_post_route(post_id: int, body: PostIn, _user: dict = Depends(require_boletines)):
    if not boletines_module.get_post(post_id):
        raise HTTPException(status_code=404, detail="Boletín no encontrado")
    boletines_module.update_post(post_id, body.titulo.strip(), body.resumen.strip(), body.contenido_html, body.contenido_bloques)
    return {"ok": True}


@router.post("/posts/{post_id}/publicar")
def publicar_route(post_id: int, _user: dict = Depends(require_boletines)):
    if not boletines_module.get_post(post_id):
        raise HTTPException(status_code=404, detail="Boletín no encontrado")
    boletines_module.publicar_post(post_id)
    return {"ok": True}


@router.post("/posts/{post_id}/despublicar")
def despublicar_route(post_id: int, _user: dict = Depends(require_boletines)):
    if not boletines_module.get_post(post_id):
        raise HTTPException(status_code=404, detail="Boletín no encontrado")
    boletines_module.despublicar_post(post_id)
    return {"ok": True}


@router.delete("/posts/{post_id}")
def delete_post_route(post_id: int, _user: dict = Depends(require_boletines)):
    boletines_module.delete_post(post_id)
    return {"ok": True}


@router.post("/posts/{post_id}/pdf")
async def subir_pdf_route(post_id: int, file: UploadFile = File(...), _user: dict = Depends(require_boletines)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube un archivo PDF")
    content = await file.read()
    try:
        boletines_module.guardar_pdf(post_id, file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.get("/posts/{post_id}/pdf")
def descargar_pdf_route(post_id: int, _user: dict = Depends(require_boletines)):
    pdf_info = boletines_module.get_pdf_info(post_id)
    if not pdf_info:
        raise HTTPException(status_code=404, detail="Este boletín no tiene PDF adjunto")
    return FileResponse(
        pdf_info["ruta"], media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{pdf_info["nombre"]}"'},
    )


@router.post("/posts/{post_id}/imagenes")
async def subir_imagen_route(post_id: int, file: UploadFile = File(...), _user: dict = Depends(require_boletines)):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in EXTENSIONES_IMAGEN:
        raise HTTPException(status_code=400, detail="Sube una imagen (jpg, png o webp)")
    content = await file.read()
    try:
        imagen_id = boletines_module.guardar_imagen(post_id, file.filename, ext, content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "id": imagen_id}


@router.get("/posts/{post_id}/imagenes/{imagen_id}")
def descargar_imagen_route(post_id: int, imagen_id: int, _user: dict = Depends(require_boletines)):
    imagen = boletines_module.get_imagen_info(post_id, imagen_id)
    if not imagen:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    ext = os.path.splitext(imagen["ruta"])[1].lower()
    return FileResponse(imagen["ruta"], media_type=EXTENSIONES_IMAGEN.get(ext, "application/octet-stream"))


@router.delete("/posts/{post_id}/imagenes/{imagen_id}")
def borrar_imagen_route(post_id: int, imagen_id: int, _user: dict = Depends(require_boletines)):
    boletines_module.borrar_imagen(post_id, imagen_id)
    return {"ok": True}


@router.get("/posts/{post_id}/envios")
def list_envios_route(post_id: int, _user: dict = Depends(require_boletines)):
    return boletines_module.list_envios(post_id)


@router.post("/posts/{post_id}/enviar")
def enviar_route(post_id: int, body: EnviarIn, _user: dict = Depends(require_boletines)):
    if not body.contacto_ids:
        raise HTTPException(status_code=400, detail="Selecciona al menos un destinatario")
    try:
        return boletines_module.enviar_boletin(post_id, body.contacto_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/contactos")
def list_contactos_route(_user: dict = Depends(require_boletines)):
    return boletines_module.list_contactos()


@router.post("/contactos")
def add_contacto_route(body: ContactoIn, _user: dict = Depends(require_boletines)):
    if not body.nombre.strip() or "@" not in body.email:
        raise HTTPException(status_code=400, detail="Nombre y email válidos son obligatorios")
    try:
        contacto_id = boletines_module.add_contacto(body.nombre.strip(), body.email.strip().lower())
    except Exception:
        raise HTTPException(status_code=400, detail="Ese email ya está en la lista de contactos")
    return {"ok": True, "id": contacto_id}


@router.post("/contactos/importar")
async def importar_contactos_route(file: UploadFile = File(...), _user: dict = Depends(require_boletines)):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        return {"ok": True, **boletines_module.import_contactos_excel(content)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/contactos/{contacto_id}")
def delete_contacto_route(contacto_id: int, _user: dict = Depends(require_boletines)):
    boletines_module.delete_contacto(contacto_id)
    return {"ok": True}


# ------------------------------- Público (sin login) -------------------------------

@router_publico.get("/posts")
def list_posts_publico_route():
    posts = boletines_module.list_posts(solo_publicados=True)
    return [
        {"id": p["id"], "titulo": p["titulo"], "resumen": p["resumen"], "publicado_en": p["publicado_en"], "tiene_pdf": p["tiene_pdf"]}
        for p in posts
    ]


@router_publico.get("/posts/{post_id}")
def get_post_publico_route(post_id: int):
    post = boletines_module.get_post(post_id, solo_publicado=True)
    if not post:
        raise HTTPException(status_code=404, detail="Boletín no encontrado")
    return post


@router_publico.get("/posts/{post_id}/pdf")
def descargar_pdf_publico_route(post_id: int):
    pdf_info = boletines_module.get_pdf_info(post_id, solo_publicado=True)
    if not pdf_info:
        raise HTTPException(status_code=404, detail="Este boletín no tiene PDF adjunto")
    return FileResponse(
        pdf_info["ruta"], media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{pdf_info["nombre"]}"'},
    )
