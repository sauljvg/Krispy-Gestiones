from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth as auth_module
import evaluaciones360 as eval360_module
from auth_routes import get_current_user

router = APIRouter()


def _modulo_para_empresa(empresa: str) -> str:
    return "saona_evaluaciones360" if empresa == "saona" else "evaluaciones360"


def require_eval360(empresa: str = "kk", user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Evaluaciones 360°")
    return user


def _require_acceso_empresa(user: dict, empresa: str):
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Evaluaciones 360°")


def _require_acceso_persona(persona_id: int, user: dict) -> dict:
    persona = eval360_module.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    _require_acceso_empresa(user, persona["empresa"])
    return persona


class PuestoBody(BaseModel):
    empresa: str = "kk"
    nombre: str


class PuestoEditBody(BaseModel):
    nombre: str | None = None
    activo: bool | None = None


class PersonaBody(BaseModel):
    empresa: str = "kk"
    nombre_completo: str
    puesto_id: int | None = None
    jefe_directo_id: int | None = None
    usuario_id: int | None = None


class PersonaEditBody(BaseModel):
    nombre_completo: str | None = None
    puesto_id: int | None = None
    jefe_directo_id: int | None = None
    usuario_id: int | None = None
    activo: bool | None = None


@router.get("/usuarios-seleccionables")
def list_usuarios_seleccionables_route(_user: dict = Depends(require_eval360)):
    return eval360_module.list_usuarios_seleccionables()


# ---------------------------------------------------------------------------
# Puestos
# ---------------------------------------------------------------------------

@router.get("/puestos")
def list_puestos_route(empresa: str = "kk", _user: dict = Depends(require_eval360)):
    return eval360_module.list_puestos(empresa)


@router.post("/puestos")
def crear_puesto_route(body: PuestoBody, user: dict = Depends(get_current_user)):
    _require_acceso_empresa(user, body.empresa)
    puesto_id = eval360_module.crear_puesto(body.empresa, body.nombre.strip())
    return {"ok": True, "id": puesto_id}


@router.patch("/puestos/{puesto_id}")
def editar_puesto_route(puesto_id: int, body: PuestoEditBody, user: dict = Depends(get_current_user)):
    puesto = eval360_module.get_puesto(puesto_id)
    if not puesto:
        raise HTTPException(status_code=404, detail="Puesto no encontrado")
    _require_acceso_empresa(user, puesto["empresa"])
    eval360_module.actualizar_puesto(puesto_id, nombre=body.nombre, activo=body.activo)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Personas (organigrama)
# ---------------------------------------------------------------------------

@router.get("/personas")
def list_personas_route(empresa: str = "kk", _user: dict = Depends(require_eval360)):
    return eval360_module.list_personas(empresa)


@router.get("/personas/{persona_id}")
def get_persona_route(persona_id: int, user: dict = Depends(get_current_user)):
    return _require_acceso_persona(persona_id, user)


@router.get("/personas/{persona_id}/relaciones")
def get_relaciones_route(persona_id: int, user: dict = Depends(get_current_user)):
    """Superior/pares/reportes calculados desde el organigrama -- usado para
    previsualizar y para la autopropuesta de evaluadores al lanzar una
    campaña (fase 3)."""
    _require_acceso_persona(persona_id, user)
    return {
        "superior": eval360_module.superior_de(persona_id),
        "pares": eval360_module.pares_de(persona_id),
        "reportes": eval360_module.reportes_de(persona_id),
    }


@router.post("/personas")
def crear_persona_route(body: PersonaBody, user: dict = Depends(get_current_user)):
    _require_acceso_empresa(user, body.empresa)
    persona_id = eval360_module.crear_persona(
        body.empresa, body.nombre_completo.strip(), body.puesto_id, body.jefe_directo_id, body.usuario_id
    )
    return {"ok": True, "id": persona_id}


@router.patch("/personas/{persona_id}")
def editar_persona_route(persona_id: int, body: PersonaEditBody, user: dict = Depends(get_current_user)):
    _require_acceso_persona(persona_id, user)
    campos = body.model_dump(exclude_unset=True)
    if "nombre_completo" in campos and campos["nombre_completo"]:
        campos["nombre_completo"] = campos["nombre_completo"].strip()
    eval360_module.actualizar_persona(persona_id, campos)
    return {"ok": True}


@router.delete("/personas/{persona_id}")
def eliminar_persona_route(persona_id: int, user: dict = Depends(get_current_user)):
    _require_acceso_persona(persona_id, user)
    eval360_module.eliminar_persona(persona_id)
    return {"ok": True}
