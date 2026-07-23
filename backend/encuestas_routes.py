from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import encuestas as encuestas_module
import informes as informes_module
from auth_routes import get_current_user

router = APIRouter()
router_publico = APIRouter()


def require_tests(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, "tests"):
        raise HTTPException(status_code=403, detail="No tienes acceso a Test")
    return user


class EncuestaCrearIn(BaseModel):
    titulo: str


class EncuestaEditarIn(BaseModel):
    titulo: str
    mensaje_final: str = "Gracias por completar el formulario."
    color_boton: str = "#5b2a2a"
    tipo_informe_clave: str | None = None
    tipo_entrevista_empresa: str | None = None


class PaginaIn(BaseModel):
    instrucciones: str = ""


class PreguntaIn(BaseModel):
    tipo: str
    etiqueta: str
    obligatoria: bool = True
    opciones: list[str] = []
    mostrar_dashboard: bool = False


class RespuestaIn(BaseModel):
    respuestas: dict[str, str]


# ------------------------------- Admin -------------------------------

@router.get("/tipos-informe-disponibles")
def tipos_informe_disponibles_route(_user: dict = Depends(require_tests)):
    """Para el desplegable "¿A qué informe alimenta?" del editor."""
    return informes_module.list_tipos()


@router.get("/encuestas")
def list_encuestas_route(_user: dict = Depends(require_tests)):
    return encuestas_module.list_encuestas()


@router.get("/encuestas/{encuesta_id}")
def get_encuesta_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    encuesta = encuestas_module.get_encuesta(encuesta_id)
    if not encuesta:
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    return encuesta


@router.post("/encuestas")
def create_encuesta_route(body: EncuestaCrearIn, _user: dict = Depends(require_tests)):
    if not body.titulo.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio")
    encuesta_id = encuestas_module.create_encuesta(body.titulo)
    return {"ok": True, "id": encuesta_id}


@router.put("/encuestas/{encuesta_id}")
def update_encuesta_route(encuesta_id: int, body: EncuestaEditarIn, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    encuestas_module.update_encuesta(
        encuesta_id, body.titulo, body.mensaje_final, body.color_boton,
        body.tipo_informe_clave, body.tipo_entrevista_empresa,
    )
    return {"ok": True}


@router.post("/encuestas/{encuesta_id}/publicar")
def publicar_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    encuestas_module.set_estado(encuesta_id, True)
    return {"ok": True}


@router.post("/encuestas/{encuesta_id}/despublicar")
def despublicar_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    encuestas_module.set_estado(encuesta_id, False)
    return {"ok": True}


@router.delete("/encuestas/{encuesta_id}")
def delete_encuesta_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.delete_encuesta(encuesta_id)
    return {"ok": True}


@router.post("/encuestas/{encuesta_id}/fondo")
async def subir_fondo_route(encuesta_id: int, file: UploadFile = File(...), _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(status_code=400, detail="Sube una imagen (jpg, png o webp)")
    content = await file.read()
    encuestas_module.guardar_fondo(encuesta_id, content, ext)
    return {"ok": True}


@router.get("/encuestas/{encuesta_id}/fondo")
def descargar_fondo_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    ruta = encuestas_module.get_fondo_ruta(encuesta_id)
    if not ruta:
        raise HTTPException(status_code=404, detail="Esta encuesta no tiene fondo")
    return FileResponse(ruta)


@router.get("/encuestas/{encuesta_id}/respuestas")
def list_respuestas_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    return encuestas_module.list_respuestas(encuesta_id)


@router.post("/encuestas/{encuesta_id}/paginas")
def add_pagina_route(encuesta_id: int, body: PaginaIn, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    pagina_id = encuestas_module.add_pagina(encuesta_id, body.instrucciones)
    return {"ok": True, "id": pagina_id}


@router.put("/paginas/{pagina_id}")
def update_pagina_route(pagina_id: int, body: PaginaIn, _user: dict = Depends(require_tests)):
    encuestas_module.update_pagina(pagina_id, body.instrucciones)
    return {"ok": True}


@router.delete("/paginas/{pagina_id}")
def delete_pagina_route(pagina_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.delete_pagina(pagina_id)
    return {"ok": True}


@router.post("/paginas/{pagina_id}/mover-arriba")
def mover_pagina_arriba_route(pagina_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.mover_pagina(pagina_id, -1)
    return {"ok": True}


@router.post("/paginas/{pagina_id}/mover-abajo")
def mover_pagina_abajo_route(pagina_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.mover_pagina(pagina_id, 1)
    return {"ok": True}


@router.post("/paginas/{pagina_id}/preguntas")
def add_pregunta_route(pagina_id: int, body: PreguntaIn, _user: dict = Depends(require_tests)):
    if not body.etiqueta.strip():
        raise HTTPException(status_code=400, detail="El enunciado de la pregunta es obligatorio")
    try:
        pregunta_id = encuestas_module.add_pregunta(
            pagina_id, body.tipo, body.etiqueta, body.obligatoria, body.opciones, body.mostrar_dashboard
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": pregunta_id}


@router.put("/preguntas/{pregunta_id}")
def update_pregunta_route(pregunta_id: int, body: PreguntaIn, _user: dict = Depends(require_tests)):
    encuestas_module.update_pregunta(pregunta_id, body.etiqueta, body.obligatoria, body.opciones, body.mostrar_dashboard)
    return {"ok": True}


@router.delete("/preguntas/{pregunta_id}")
def delete_pregunta_route(pregunta_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.delete_pregunta(pregunta_id)
    return {"ok": True}


@router.post("/preguntas/{pregunta_id}/mover-arriba")
def mover_pregunta_arriba_route(pregunta_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.mover_pregunta(pregunta_id, -1)
    return {"ok": True}


@router.post("/preguntas/{pregunta_id}/mover-abajo")
def mover_pregunta_abajo_route(pregunta_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.mover_pregunta(pregunta_id, 1)
    return {"ok": True}


# ------------------------------- Público (sin login) -------------------------------

@router_publico.get("/{slug}")
def get_encuesta_publica_route(slug: str):
    encuesta = encuestas_module.get_encuesta_publica(slug)
    if not encuesta:
        raise HTTPException(status_code=404, detail="Esta encuesta no está disponible actualmente")
    return encuesta


@router_publico.get("/{slug}/fondo")
def get_fondo_publico_route(slug: str):
    encuesta = encuestas_module.get_encuesta_publica(slug)
    if not encuesta:
        raise HTTPException(status_code=404, detail="Esta encuesta no está disponible actualmente")
    ruta = encuestas_module.get_fondo_ruta(encuesta["id"])
    if not ruta:
        raise HTTPException(status_code=404, detail="Esta encuesta no tiene fondo")
    return FileResponse(ruta)


def _ip_cliente(request: Request) -> str:
    # X-Forwarded-For es lo que pone el proxy de Replit delante de la app;
    # sin esto, request.client.host siempre sería la IP interna del proxy,
    # no la del candidato real.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


@router_publico.post("/{slug}/enviar")
def enviar_respuesta_route(slug: str, body: RespuestaIn, request: Request):
    ip = _ip_cliente(request)
    user_agent = request.headers.get("user-agent", "")
    try:
        return encuestas_module.guardar_respuesta(slug, body.respuestas, ip, user_agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
