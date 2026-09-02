import os

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

import auth as auth_module
import clima as clima_module
import evaluaciones360 as eval360_module
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


def _require_vista_personal(user: dict) -> None:
    # A propósito atado a UN username, no a rol admin: es un vistazo
    # personal, no una función general del portal para cualquier
    # administrador. El username vive en una variable de entorno (no
    # hardcodeado) para que, si algún día cambia, se actualice en Railway sin
    # tener que tocar ni desplegar código.
    if user["username"].lower() != os.environ.get("USUARIO_VISTA_EN_LINEA", "saul").lower():
        raise HTTPException(status_code=403, detail="No disponible")


@router.get("/usuarios-en-linea")
def usuarios_en_linea_route(user: dict = Depends(get_current_user)):
    _require_vista_personal(user)
    return {"usuarios": auth_module.get_usuarios_en_linea(excluir_usuario_id=user["id"])}


@router.get("/historial-accesos")
def historial_accesos_route(dias: int = 30, user: dict = Depends(get_current_user)):
    _require_vista_personal(user)
    return auth_module.get_historial_accesos(dias)


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
    username_clean = body.username.strip().lower()
    user = auth_module.get_user_by_username(username_clean)
    if user is None:
        return {"existe": False, "tiene_pin": False}
    return {"existe": True, "tiene_pin": user["pin"] is not None}


@router.post("/set-pin")
def set_pin_route(body: SetPinBody):
    if not auth_module.pin_valido(body.pin):
        raise HTTPException(status_code=400, detail="El PIN debe ser de 4 dígitos")
    username_clean = body.username.strip().lower()
    ok = auth_module.set_pin_si_no_tiene(username_clean, body.pin)
    if not ok:
        raise HTTPException(status_code=400, detail="Este usuario ya tiene un PIN configurado")
    return {"ok": True}


@router.post("/login-pin")
def login_pin_route(body: LoginPinBody, response: Response):
    username_clean = body.username.strip().lower()
    restante = auth_module.login_bloqueado_minutos(username_clean)
    if restante is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Prueba de nuevo en {restante} minuto{'s' if restante != 1 else ''}.",
        )
    user = auth_module.authenticate_pin(username_clean, body.pin)
    if user is None:
        auth_module.registrar_intento_fallido(username_clean)
        raise HTTPException(status_code=401, detail="Usuario o PIN incorrectos")
    auth_module.limpiar_intentos_login(username_clean)
    token = auth_module.create_session(user["id"])
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=True,
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


def _normalizar_rol(rol: str) -> str:
    rol = (rol or "").strip()
    if not rol:
        raise HTTPException(status_code=400, detail="El rol no puede estar vacío")
    if len(rol) > 60:
        raise HTTPException(status_code=400, detail="El rol es demasiado largo (máximo 60 caracteres)")
    # Si coincide (sin distinguir mayúsculas) con uno de los roles conocidos
    # -- "admin" sobre todo, el único con permisos especiales de verdad, ver
    # auth.tiene_modulo -- se ajusta a su forma exacta (la clave interna,
    # p.ej. "area_manager"). Así escribir "Admin" no crea sin querer un rol
    # nuevo "Admin" sin ningún permiso real, distinto del "admin" que sí los
    # tiene. Antes solo comparaba contra las claves (auth_module.ROLES,
    # "director_operaciones") y nunca contra las etiquetas que en realidad
    # se escriben/muestran ("Director de Operaciones") -- así que escribir
    # el nombre normal del rol nunca lo ajustaba a su clave interna, y
    # comprobaciones como _ve_todo_lo_compartido() en reclutamiento_routes.py
    # (que sí comparan contra la clave) nunca reconocían a esa persona.
    for clave, etiqueta in auth_module.ROLES.items():
        if rol.lower() in (clave.lower(), etiqueta.lower()):
            return clave
    return rol


@router.get("/roles")
def list_roles(_admin: dict = Depends(require_admin)):
    """Los roles "de siempre" (auth.ROLES) más cualquier rol personalizado ya
    en uso (ver NewUserBody/UpdateRoleBody -- el rol es texto libre desde
    que se permitió escribir cualquier cosa, p.ej. "Marketing") -- para que
    el desplegable/autocompletar de la web sugiera también los que ya
    escribió alguien antes, no solo los seis de siempre."""
    conocidos = [{"value": k, "label": v} for k, v in auth_module.ROLES.items()]
    conn = get_connection()
    personalizados = conn.execute("SELECT DISTINCT rol FROM usuarios").fetchall()
    conn.close()
    claves_conocidas = {k.lower() for k in auth_module.ROLES}
    for row in personalizados:
        rol = row["rol"]
        if rol and rol.lower() not in claves_conocidas:
            conocidos.append({"value": rol, "label": rol})
            claves_conocidas.add(rol.lower())
    return conocidos


@router.get("/modulos")
def list_modulos(_admin: dict = Depends(require_admin)):
    return [{"value": k, "label": v} for k, v in auth_module.MODULOS.items()]


MODULOS_360 = {"evaluaciones360", "saona_evaluaciones360"}


@router.get("/users")
def list_users(_admin: dict = Depends(require_admin)):
    """Ajustes -> Usuarios es la lista de quienes usan el portal en general.
    Las cuentas creadas desde Evaluaciones 360 exclusivamente para responder
    ahí (rol colaborador, único módulo evaluaciones360/saona_evaluaciones360)
    se gestionan desde la pestaña Accesos de 360 y no aparecen aquí -- si a
    esa cuenta se le da algún otro módulo, deja de ser "exclusiva" y pasa a
    verse también en Ajustes."""
    conn = get_connection()
    rows = conn.execute("SELECT id, username, pin, nombre, rol, creado FROM usuarios ORDER BY id").fetchall()
    conn.close()
    resultado = []
    for r in rows:
        modulos = list(auth_module.MODULOS) if r["rol"] == "admin" else auth_module.get_modulos_permitidos(r["id"])
        if r["rol"] != "admin" and modulos and set(modulos) <= MODULOS_360:
            continue
        resultado.append({
            **dict(r),
            "tiendas": auth_module.get_tiendas_permitidas(r["id"]),
            "modulos": modulos,
            "tipos_informes": informes_module.get_tipos_permitidos(r["id"]),
            "clima_centros": clima_module.get_centros_permitidos(r["id"]),
        })
    return resultado


@router.post("/users")
def create_user_route(body: NewUserBody, _admin: dict = Depends(require_admin)):
    body.rol = _normalizar_rol(body.rol)
    username_clean = body.username.strip().lower()
    if not auth_module.username_disponible(username_clean):
        raise HTTPException(status_code=400, detail="Ese usuario ya existe (el usuario no distingue mayúsculas de minúsculas)")
    try:
        user_id = auth_module.create_user(username_clean, body.nombre, body.rol)
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
    body.rol = _normalizar_rol(body.rol)
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
    auth_module.eliminar_usuario(user_id)
    # Espejo con Evaluaciones 360: si esta cuenta tenía una persona vinculada
    # en el organigrama, se desactiva y se desvincula (no se borra la
    # persona de verdad, arrastraría respuestas de evaluaciones ya hechas).
    eval360_module.desvincular_personas_de_usuario(user_id)
    return {"ok": True}


class UpdateUserBody(BaseModel):
    nombre: str | None = None
    username: str | None = None


@router.patch("/users/{user_id}")
def update_user_route(user_id: int, body: UpdateUserBody, _admin: dict = Depends(require_admin)):
    conn = get_connection()
    row = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    nombre = body.nombre.strip() if body.nombre else None
    username = body.username.strip() if body.username else None
    error = auth_module.actualizar_usuario(user_id, nombre=nombre, username=username)
    if error:
        raise HTTPException(status_code=400, detail=error)
    # Espejo con Evaluaciones 360: si renombran a alguien desde Ajustes, se
    # refleja en su(s) persona(s) espejo del organigrama.
    if nombre:
        eval360_module.sincronizar_nombre_a_personas(user_id, nombre)
    return {"ok": True}
