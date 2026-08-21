from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import clima as clima_module
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
    clima_oleada_id: int | None = None
    enlace_corto: str | None = None
    evitar_duplicados: bool = False
    mensaje_no_apto: str = "Gracias por contestar nuestro test. En esta ocasión no has superado el proceso, pero te deseamos mucha suerte."
    usar_mensaje_no_apto: bool = True
    fecha_cierre: str | None = None


class PaginaIn(BaseModel):
    instrucciones: str = ""
    condicion_pregunta_id: int | None = None
    condicion_valores: list[str] = []


class PreguntaIn(BaseModel):
    tipo: str
    etiqueta: str
    obligatoria: bool = True
    opciones: list[str] = []
    mostrar_dashboard: bool = False
    opciones_descarta: list[bool] = []


class RespuestaIn(BaseModel):
    respuestas: dict[str, str]
    token: str | None = None


class SesionIn(BaseModel):
    token: str
    pagina: int = 1


class MoverPreguntaAPaginaIn(BaseModel):
    pagina_destino_id: int
    antes_de_pregunta_id: int | None = None


# ------------------------------- Admin -------------------------------

@router.get("/notificaciones")
def notificaciones_route(user: dict = Depends(require_tests)):
    """Para el globo junto al menú hamburguesa: qué tests han recibido
    respuestas nuevas desde la última vez que este usuario las revisó."""
    return encuestas_module.get_notificaciones_tests(user["id"])


@router.post("/notificaciones/marcar-vistas")
def marcar_notificaciones_route(user: dict = Depends(require_tests)):
    encuestas_module.marcar_notificaciones_vistas(user["id"])
    return {"ok": True}


@router.get("/tipos-informe-disponibles")
def tipos_informe_disponibles_route(_user: dict = Depends(require_tests)):
    """Para el desplegable "¿A qué informe alimenta?" del editor."""
    return informes_module.list_tipos()


@router.get("/clima-oleadas-disponibles")
def clima_oleadas_disponibles_route(_user: dict = Depends(require_tests)):
    """Para el mismo desplegable, grupo "Clima Laboral" -- oleadas de las dos
    empresas juntas (mismo criterio que tipos_informe_disponibles_route: el
    editor de Tests no filtra por empresa del usuario, solo por si tiene
    acceso a Tests en general)."""
    return clima_module.list_oleadas("kk") + clima_module.list_oleadas("saona")


@router.get("/encuestas")
def list_encuestas_route(_user: dict = Depends(require_tests)):
    return encuestas_module.list_encuestas()


@router.get("/encuestas/enlace-corto-entrevista/{empresa}")
def enlace_corto_entrevista_route(empresa: str, _user: dict = Depends(get_current_user)):
    """Solo el enlace corto del test de Entrevista de Salida de esta
    empresa — sin exigir el módulo Test, para el botón "Enviar
    Recordatorio" de Entrevista de Salida (que sí requiere Informes)."""
    return {"enlace_corto": encuestas_module.get_enlace_corto_entrevista(empresa)}


@router.get("/encuestas/en-vivo")
def en_vivo_route(_user: dict = Depends(require_tests)):
    """Cuántas personas están respondiendo cada test AHORA MISMO (heartbeat
    de los últimos 2 min, sin haber terminado) — un solo viaje para toda la
    lista en vez de una petición por test."""
    return encuestas_module.contar_en_vivo_por_encuesta()


@router.get("/encuestas/{encuesta_id}/embudo")
def embudo_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    return encuestas_module.get_embudo(encuesta_id)


@router.get("/encuestas/{encuesta_id}/en-vivo-detalle")
def en_vivo_detalle_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    return encuestas_module.get_en_vivo_detalle(encuesta_id)


@router.delete("/encuestas/{encuesta_id}/sesiones")
def borrar_sesiones_route(encuesta_id: int, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    encuestas_module.borrar_sesiones(encuesta_id)
    return {"ok": True}


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
        body.tipo_informe_clave, body.tipo_entrevista_empresa, body.enlace_corto, body.evitar_duplicados,
        body.mensaje_no_apto, body.clima_oleada_id, body.usar_mensaje_no_apto, body.fecha_cierre,
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


@router.delete("/encuestas/respuestas/{respuesta_id}")
def borrar_respuesta_route(respuesta_id: int, _user: dict = Depends(require_tests)):
    encuestas_module.borrar_respuesta(respuesta_id)
    return {"ok": True}


@router.post("/encuestas/{encuesta_id}/paginas")
def add_pagina_route(encuesta_id: int, body: PaginaIn, _user: dict = Depends(require_tests)):
    if not encuestas_module.get_encuesta(encuesta_id):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    pagina_id = encuestas_module.add_pagina(encuesta_id, body.instrucciones, body.condicion_pregunta_id, body.condicion_valores)
    return {"ok": True, "id": pagina_id}


@router.put("/paginas/{pagina_id}")
def update_pagina_route(pagina_id: int, body: PaginaIn, _user: dict = Depends(require_tests)):
    encuestas_module.update_pagina(pagina_id, body.instrucciones, body.condicion_pregunta_id, body.condicion_valores)
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
            pagina_id, body.tipo, body.etiqueta, body.obligatoria, body.opciones, body.mostrar_dashboard,
            body.opciones_descarta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": pregunta_id}


@router.put("/preguntas/{pregunta_id}")
def update_pregunta_route(pregunta_id: int, body: PreguntaIn, _user: dict = Depends(require_tests)):
    encuestas_module.update_pregunta(
        pregunta_id, body.etiqueta, body.obligatoria, body.opciones, body.mostrar_dashboard, body.opciones_descarta
    )
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


@router.post("/preguntas/{pregunta_id}/mover-a-pagina")
def mover_pregunta_a_pagina_route(pregunta_id: int, body: MoverPreguntaAPaginaIn, _user: dict = Depends(require_tests)):
    encuestas_module.mover_pregunta_a_pagina(pregunta_id, body.pagina_destino_id, body.antes_de_pregunta_id)
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
        return encuestas_module.guardar_respuesta(slug, body.respuestas, ip, user_agent, token=body.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router_publico.post("/{slug}/sesion")
def registrar_sesion_route(slug: str, body: SesionIn, request: Request):
    """Late para trackear aperturas/abandono: encuesta.js llama esto al
    cargar y cada vez que cambia de página (más un heartbeat cada 20s en la
    misma página) — nunca bloquea ni rompe el formulario si falla."""
    encuestas_module.registrar_sesion(slug, body.token, body.pagina, ip=_ip_cliente(request))
    return {"ok": True}
