from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

import auth as auth_module
import clima as clima_module
import informes as informes_module
from db import get_connection

router = APIRouter()

COOKIE_NAME = "kt_session"


def public_user(row: dict) -> dict:
    return {
        "id": row["id"], "username": row["username"], "nombre": row["nombre"], "rol": row["rol"],
        "tiendas": auth_module.get_tiendas_permitidas(row["id"]),
        "modulos": list(auth_module.MODULOS) if row["rol"] == "admin" else auth_module.get_modulos_permitidos(row["id"]),
        "tipos_informes": informes_module.get_tipos_permitidos(row["id"]),
        "clima_centros": clima_module.get_centros_permitidos(row["id"]),
    }


def get_current_user(kt_session: str | None = Cookie(default=None)) -> dict:
    user = auth_module.get_user_by_token(kt_session)
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")
    return user


@router.get("/usuarios-en-linea")
def usuarios_en_linea_route(user: dict = Depends(get_current_user)):
    # A propósito atado al username literal (no a rol admin): es un vistazo
    # personal de Saúl, no una función general del portal para cualquier
    # administrador.
    if user["username"] != "saul":
        raise HTTPException(status_code=403, detail="No disponible")
    return {"usuarios": auth_module.get_usuarios_en_linea(excluir_usuario_id=user["id"])}


def require_resenas(empresa: str = "kk", user: dict = Depends(get_current_user)) -> dict:
    modulo = "saona_resenas" if empresa == "saona" else "resenas"
    if not auth_module.tiene_modulo(user, modulo):
        raise HTTPException(status_code=403, detail="No tienes acceso a Reseñas")
    return user


class CheckUsernameBody(BaseModel):
    username: str


class SetPinBody(BaseModel):
    username: str
    pin: str


class LoginPinBody(BaseModel):
    username: str
    pin: str


@router.post("/check-username")
def check_username_route(body: CheckUsernameBody):
    user = auth_module.get_user_by_username(body.username.strip())
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"tiene_pin": user["pin"] is not None}


@router.post("/set-pin")
def set_pin_route(body: SetPinBody):
    if not auth_module.pin_valido(body.pin):
        raise HTTPException(status_code=400, detail="El PIN debe ser de 4 dígitos")
    ok = auth_module.set_pin_si_no_tiene(body.username.strip(), body.pin)
    if not ok:
        raise HTTPException(status_code=400, detail="Este usuario ya tiene un PIN configurado")
    return {"ok": True}


@router.post("/login-pin")
def login_pin_route(body: LoginPinBody, response: Response):
    user = auth_module.authenticate_pin(body.username.strip(), body.pin)
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario o PIN incorrectos")
    token = auth_module.create_session(user["id"])
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {"ok": True, "user": public_user(user)}


@router.post("/logout")
def logout(response: Response, kt_session: str | None = Cookie(default=None)):
    if kt_session:
        auth_module.delete_session(kt_session)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return public_user(user)


class NewUserBody(BaseModel):
    username: str
    nombre: str
    rol: str
    tiendas: list[str] = []
    modulos: list[str] = []
    tipos_informes: list[str] = []


class UpdateRoleBody(BaseModel):
    rol: str


class SetAdminPinBody(BaseModel):
    pin: str


class SetTiendasBody(BaseModel):
    tiendas: list[str] = []


class SetModulosBody(BaseModel):
    modulos: list[str] = []


class SetTiposInformesBody(BaseModel):
    tipos_informes: list[str] = []


class SetClimaCentrosBody(BaseModel):
    centros: list[str] = []


@router.get("/roles")
def list_roles(_admin: dict = Depends(require_admin)):
    return [{"value": k, "label": v} for k, v in auth_module.ROLES.items()]


@router.get("/modulos")
def list_modulos(_admin: dict = Depends(require_admin)):
    return [{"value": k, "label": v} for k, v in auth_module.MODULOS.items()]


@router.get("/users")
def list_users(_admin: dict = Depends(require_admin)):
    conn = get_connection()
    rows = conn.execute("SELECT id, username, pin, nombre, rol, creado FROM usuarios ORDER BY id").fetchall()
    conn.close()
    return [
        {
            **dict(r),
            "tiendas": auth_module.get_tiendas_permitidas(r["id"]),
            "modulos": list(auth_module.MODULOS) if r["rol"] == "admin" else auth_module.get_modulos_permitidos(r["id"]),
            "tipos_informes": informes_module.get_tipos_permitidos(r["id"]),
            "clima_centros": clima_module.get_centros_permitidos(r["id"]),
        }
        for r in rows
    ]


@router.post("/users")
def create_user_route(body: NewUserBody, _admin: dict = Depends(require_admin)):
    if body.rol not in auth_module.ROLES:
        raise HTTPException(status_code=400, detail=f"rol debe ser uno de: {', '.join(auth_module.ROLES)}")
    if not auth_module.username_disponible(body.username):
        raise HTTPException(status_code=400, detail="Ese usuario ya existe (el usuario no distingue mayúsculas de minúsculas)")
    try:
        user_id = auth_module.create_user(body.username, body.nombre, body.rol)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo crear el usuario (¿username duplicado?): {exc}")
    if body.tiendas:
        auth_module.set_tiendas_permitidas(user_id, body.tiendas)
    # admin siempre tiene todos los módulos (ver auth_module.tiene_modulo) —
    # no hace falta guardarlo explícitamente, pero para el resto de roles el
    # checkbox de cada módulo es la única fuente de verdad.
    if body.rol != "admin":
        auth_module.set_modulos_permitidos(user_id, body.modulos)
    if body.tipos_informes:
        informes_module.set_tipos_permitidos(user_id, body.tipos_informes)
    return {"ok": True, "id": user_id}


@router.patch("/users/{user_id}/tiendas")
def set_tiendas_route(user_id: int, body: SetTiendasBody, _admin: dict = Depends(require_admin)):
    conn = get_connection()
    row = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    auth_module.set_tiendas_permitidas(user_id, body.tiendas)
    return {"ok": True}


@router.patch("/users/{user_id}/modulos")
def set_modulos_route(user_id: int, body: SetModulosBody, _admin: dict = Depends(require_admin)):
    conn = get_connection()
    row = conn.execute("SELECT id, rol FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if row["rol"] == "admin":
        raise HTTPException(status_code=400, detail="Admin ya tiene acceso a todos los módulos")
    auth_module.set_modulos_permitidos(user_id, body.modulos)
    return {"ok": True}


@router.patch("/users/{user_id}/tipos-informes")
def set_tipos_informes_route(user_id: int, body: SetTiposInformesBody, _admin: dict = Depends(require_admin)):
    conn = get_connection()
    row = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    informes_module.set_tipos_permitidos(user_id, body.tipos_informes)
    return {"ok": True}


@router.patch("/users/{user_id}/clima-centros")
def set_clima_centros_route(user_id: int, body: SetClimaCentrosBody, _admin: dict = Depends(require_admin)):
    conn = get_connection()
    row = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    clima_module.set_centros_permitidos(user_id, body.centros)
    return {"ok": True}


@router.patch("/users/{user_id}/rol")
def update_role_route(user_id: int, body: UpdateRoleBody, admin: dict = Depends(require_admin)):
    if body.rol not in auth_module.ROLES:
        raise HTTPException(status_code=400, detail=f"rol debe ser uno de: {', '.join(auth_module.ROLES)}")
    if user_id == admin["id"] and body.rol != "admin":
        raise HTTPException(status_code=400, detail="No puedes quitarte tu propio rol admin")
    conn = get_connection()
    row = conn.execute("SELECT rol FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (body.rol, user_id))
    conn.commit()
    conn.close()
    # Un admin no tiene filas propias en usuario_modulos (siempre ve todo por
    # su rol) — si deja de ser admin, hay que concederle explícitamente todo
    # lo que ya veía, si no, se queda sin ningún módulo de golpe.
    if row and row["rol"] == "admin" and body.rol != "admin" and not auth_module.get_modulos_permitidos(user_id):
        auth_module.set_modulos_permitidos(user_id, list(auth_module.MODULOS))
    return {"ok": True}


@router.patch("/users/{user_id}/pin")
def set_admin_pin_route(user_id: int, body: SetAdminPinBody, _admin: dict = Depends(require_admin)):
    if not auth_module.pin_valido(body.pin):
        raise HTTPException(status_code=400, detail="El PIN debe ser de 4 dígitos")
    conn = get_connection()
    row = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    auth_module.admin_set_pin(user_id, body.pin)
    return {"ok": True}


@router.post("/users/{user_id}/reset-pin")
def reset_pin_route(user_id: int, _admin: dict = Depends(require_admin)):
    """Borra el PIN del usuario — la próxima vez que entre con su usuario le
    pedirá crear uno nuevo, como si fuera la primera vez."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    auth_module.reset_pin(user_id)
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user_route(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="No puedes borrar tu propio usuario")
    conn = get_connection()
    conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
