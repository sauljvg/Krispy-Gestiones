from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth as auth_module
import david as david_module
from auth_routes import get_current_user

router = APIRouter()


class TurnoIn(BaseModel):
    rol: str
    texto: str


class PreguntaIn(BaseModel):
    mensaje: str
    historial: list[TurnoIn] = []


@router.post("/chat")
def chat_route(body: PreguntaIn, user: dict = Depends(get_current_user)):
    mensaje = body.mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="Mensaje vacio")
    modulos_usuario = list(auth_module.MODULOS) if user["rol"] == "admin" else auth_module.get_modulos_permitidos(user["id"])
    try:
        respuesta = david_module.preguntar(mensaje, [t.model_dump() for t in body.historial], modulos_usuario)
    except david_module.DavidError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"respuesta": respuesta}
