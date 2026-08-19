from fastapi import APIRouter, Depends

import notificaciones as notificaciones_module
from auth_routes import get_current_user

router = APIRouter()


@router.get("/notificaciones")
def notificaciones_route(user: dict = Depends(get_current_user)):
    return notificaciones_module.get_notificaciones(user["id"])


@router.post("/notificaciones/marcar-vistas")
def marcar_notificaciones_route(user: dict = Depends(get_current_user)):
    notificaciones_module.marcar_notificaciones_vistas(user["id"])
    return {"ok": True}
