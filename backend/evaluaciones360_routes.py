from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import auth as auth_module
import evaluaciones360 as eval360_module
from auth_routes import get_current_user, require_admin

router = APIRouter()


def _modulo_para_empresa(empresa: str) -> str:
    return "saona_evaluaciones360" if empresa == "saona" else "evaluaciones360"


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
    puesto_padre_id: int | None = None


class PuestoEditBody(BaseModel):
    nombre: str | None = None
    activo: bool | None = None
    puesto_padre_id: int | None = None


class PersonaBody(BaseModel):
    empresa: str = "kk"
    nombre_completo: str
    puesto_ids: list[int] = []
    jefe_directo_id: int | None = None
    usuario_id: int | None = None
    email: str | None = None


class PersonaEditBody(BaseModel):
    nombre_completo: str | None = None
    puesto_ids: list[int] | None = None
    jefe_directo_id: int | None = None
    usuario_id: int | None = None
    activo: bool | None = None
    email: str | None = None


class PreguntaBody(BaseModel):
    empresa: str = "kk"
    tipo: str
    grupo: str | None = None
    texto: str


class PreguntaEditBody(BaseModel):
    texto: str | None = None
    orden: int | None = None
    activa: bool | None = None


@router.get("/usuarios-seleccionables")
def list_usuarios_seleccionables_route(_user: dict = Depends(require_admin)):
    return eval360_module.list_usuarios_seleccionables()


# ---------------------------------------------------------------------------
# Preguntas
# ---------------------------------------------------------------------------

@router.get("/preguntas")
def list_preguntas_route(empresa: str = "kk", _user: dict = Depends(require_admin)):
    return eval360_module.list_preguntas(empresa)


@router.post("/preguntas")
def crear_pregunta_route(body: PreguntaBody, user: dict = Depends(require_admin)):
    _require_acceso_empresa(user, body.empresa)
    if body.tipo not in ("likert", "abierta"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'likert' o 'abierta'")
    pregunta_id = eval360_module.crear_pregunta(body.empresa, body.tipo, body.grupo, body.texto.strip())
    return {"ok": True, "id": pregunta_id}


@router.patch("/preguntas/{pregunta_id}")
def editar_pregunta_route(pregunta_id: int, body: PreguntaEditBody, user: dict = Depends(require_admin)):
    pregunta = eval360_module.get_pregunta(pregunta_id)
    if not pregunta:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    _require_acceso_empresa(user, pregunta["empresa"])
    texto = body.texto.strip() if body.texto is not None else None
    eval360_module.actualizar_pregunta(pregunta_id, texto=texto, orden=body.orden, activa=body.activa)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Puestos
# ---------------------------------------------------------------------------

@router.get("/puestos")
def list_puestos_route(empresa: str = "kk", _user: dict = Depends(require_admin)):
    return eval360_module.list_puestos(empresa)


@router.post("/puestos")
def crear_puesto_route(body: PuestoBody, user: dict = Depends(require_admin)):
    _require_acceso_empresa(user, body.empresa)
    puesto_id = eval360_module.crear_puesto(body.empresa, body.nombre.strip(), body.puesto_padre_id)
    return {"ok": True, "id": puesto_id}


@router.patch("/puestos/{puesto_id}")
def editar_puesto_route(puesto_id: int, body: PuestoEditBody, user: dict = Depends(require_admin)):
    puesto = eval360_module.get_puesto(puesto_id)
    if not puesto:
        raise HTTPException(status_code=404, detail="Puesto no encontrado")
    _require_acceso_empresa(user, puesto["empresa"])
    campos = body.model_fields_set
    padre_id = body.puesto_padre_id if "puesto_padre_id" in campos else -1
    eval360_module.actualizar_puesto(puesto_id, nombre=body.nombre, activo=body.activo, puesto_padre_id=padre_id)
    return {"ok": True}


@router.get("/puestos/{puesto_id}/personas")
def list_personas_de_puesto_route(puesto_id: int, user: dict = Depends(require_admin)):
    puesto = eval360_module.get_puesto(puesto_id)
    if not puesto:
        raise HTTPException(status_code=404, detail="Puesto no encontrado")
    _require_acceso_empresa(user, puesto["empresa"])
    return eval360_module.list_personas_de_puesto(puesto_id)


# ---------------------------------------------------------------------------
# Personas (organigrama)
# ---------------------------------------------------------------------------

@router.get("/personas")
def list_personas_route(empresa: str = "kk", _user: dict = Depends(require_admin)):
    eval360_module.sincronizar_personas_privilegiadas()
    return eval360_module.list_personas(empresa)


@router.get("/personas/{persona_id}")
def get_persona_route(persona_id: int, user: dict = Depends(require_admin)):
    return _require_acceso_persona(persona_id, user)


@router.get("/personas/{persona_id}/relaciones")
def get_relaciones_route(persona_id: int, user: dict = Depends(require_admin)):
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
def crear_persona_route(body: PersonaBody, user: dict = Depends(require_admin)):
    _require_acceso_empresa(user, body.empresa)
    email = body.email.strip() or None if body.email else None
    persona_id = eval360_module.crear_persona(
        body.empresa, body.nombre_completo.strip(), body.puesto_ids, body.jefe_directo_id, body.usuario_id, email
    )
    return {"ok": True, "id": persona_id}


@router.patch("/personas/{persona_id}")
def editar_persona_route(persona_id: int, body: PersonaEditBody, user: dict = Depends(require_admin)):
    persona = _require_acceso_persona(persona_id, user)
    campos = body.model_dump(exclude_unset=True)
    if "nombre_completo" in campos and campos["nombre_completo"]:
        campos["nombre_completo"] = campos["nombre_completo"].strip()
    if "email" in campos:
        campos["email"] = campos["email"].strip() or None if campos["email"] else None
    eval360_module.actualizar_persona(persona_id, campos)
    # Espejo persona -> cuenta: si esta persona está vinculada a un usuario
    # del portal, un cambio de nombre hecho desde 360 se refleja en Ajustes.
    if persona.get("usuario_id") and campos.get("nombre_completo"):
        auth_module.actualizar_usuario(persona["usuario_id"], nombre=campos["nombre_completo"])
    return {"ok": True}


@router.delete("/personas/{persona_id}")
def eliminar_persona_route(persona_id: int, user: dict = Depends(require_admin)):
    _require_acceso_persona(persona_id, user)
    eval360_module.eliminar_persona(persona_id)
    return {"ok": True}


@router.delete("/personas/{persona_id}/cuenta")
def eliminar_persona_y_cuenta_route(persona_id: int, admin: dict = Depends(require_admin)):
    """Borrado real, gestionado desde 360: a diferencia de "Eliminar" (que
    solo desactiva, ver eliminar_persona), esto borra la CUENTA de portal
    vinculada de verdad -- mismo efecto que borrarla desde Ajustes, solo que
    sin tener que salir de 360 a hacerlo. Deliberadamente distinto del botón
    de quitar del organigrama, que no toca la cuenta."""
    persona = _require_acceso_persona(persona_id, admin)
    if not persona.get("usuario_id"):
        raise HTTPException(status_code=400, detail="Esta persona no tiene una cuenta de portal vinculada")
    if persona["usuario_id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="No puedes borrar tu propio usuario")
    auth_module.eliminar_usuario(persona["usuario_id"])
    eval360_module.desvincular_personas_de_usuario(persona["usuario_id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Campañas
# ---------------------------------------------------------------------------

class CampanaBody(BaseModel):
    empresa: str = "kk"
    nombre: str
    periodo_desde: str | None = None
    periodo_hasta: str | None = None


class CampanaEditBody(BaseModel):
    nombre: str | None = None
    periodo_desde: str | None = None
    periodo_hasta: str | None = None


class EvaluadoBody(BaseModel):
    persona_id: int


class EvaluadorManualBody(BaseModel):
    evaluador_persona_id: int


def _require_acceso_campana(campana_id: int, user: dict) -> dict:
    campana = eval360_module.get_campana(campana_id)
    if not campana:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    _require_acceso_empresa(user, campana["empresa"])
    return campana


@router.get("/campanas")
def list_campanas_route(empresa: str = "kk", _user: dict = Depends(require_admin)):
    return eval360_module.list_campanas(empresa)


@router.post("/campanas")
def crear_campana_route(body: CampanaBody, user: dict = Depends(require_admin)):
    _require_acceso_empresa(user, body.empresa)
    if not body.nombre.strip():
        raise HTTPException(status_code=400, detail="Ponle un nombre a la campaña")
    campana_id = eval360_module.crear_campana(
        body.empresa, body.nombre.strip(), body.periodo_desde, body.periodo_hasta, user["id"]
    )
    return {"ok": True, "id": campana_id}


@router.get("/campanas/{campana_id}")
def get_campana_route(campana_id: int, user: dict = Depends(require_admin)):
    campana = _require_acceso_campana(campana_id, user)
    return {**campana, "evaluados": eval360_module.list_evaluados_de_campana(campana_id)}


@router.patch("/campanas/{campana_id}")
def editar_campana_route(campana_id: int, body: CampanaEditBody, user: dict = Depends(require_admin)):
    _require_acceso_campana(campana_id, user)
    campos = body.model_dump(exclude_unset=True)
    if "nombre" in campos and campos["nombre"]:
        campos["nombre"] = campos["nombre"].strip()
    eval360_module.actualizar_campana(campana_id, campos)
    return {"ok": True}


@router.post("/campanas/{campana_id}/lanzar")
def lanzar_campana_route(campana_id: int, request: Request, user: dict = Depends(require_admin)):
    campana = _require_acceso_campana(campana_id, user)
    if campana["estado"] != "borrador":
        raise HTTPException(status_code=400, detail="Esta campaña ya se lanzó")
    if eval360_module.contar_asignaciones(campana_id) == 0:
        raise HTTPException(status_code=400, detail="Añade al menos un evaluado con evaluadores antes de lanzar")
    eval360_module.lanzar_campana(campana_id)
    base_url = str(request.base_url).rstrip("/")
    aviso = eval360_module.notificar_campana_lanzada(campana_id, base_url)
    return {"ok": True, "avisos": aviso}


@router.post("/campanas/{campana_id}/cerrar")
def cerrar_campana_route(campana_id: int, user: dict = Depends(require_admin)):
    _require_acceso_campana(campana_id, user)
    eval360_module.cerrar_campana(campana_id)
    return {"ok": True}


@router.post("/campanas/{campana_id}/reabrir")
def reabrir_campana_route(campana_id: int, user: dict = Depends(require_admin)):
    campana = _require_acceso_campana(campana_id, user)
    if campana["estado"] != "cerrada":
        raise HTTPException(status_code=400, detail="Esta campaña no está cerrada")
    eval360_module.reabrir_campana(campana_id)
    return {"ok": True}


@router.post("/campanas/{campana_id}/evaluados")
def agregar_evaluado_route(campana_id: int, body: EvaluadoBody, user: dict = Depends(require_admin)):
    campana = _require_acceso_campana(campana_id, user)
    if campana["estado"] != "borrador":
        raise HTTPException(status_code=400, detail="Esta campaña ya está lanzada, no se pueden añadir más evaluados")
    _require_acceso_persona(body.persona_id, user)
    eval360_module.agregar_evaluado_a_campana(campana_id, body.persona_id)
    return {"ok": True, "evaluadores": eval360_module.list_evaluadores_de_evaluado(campana_id, body.persona_id)}


@router.delete("/campanas/{campana_id}/evaluados/{persona_id}")
def quitar_evaluado_route(campana_id: int, persona_id: int, user: dict = Depends(require_admin)):
    _require_acceso_campana(campana_id, user)
    eval360_module.quitar_evaluado_de_campana(campana_id, persona_id)
    return {"ok": True}


@router.get("/campanas/{campana_id}/evaluados/{persona_id}/evaluadores")
def list_evaluadores_route(campana_id: int, persona_id: int, user: dict = Depends(require_admin)):
    _require_acceso_campana(campana_id, user)
    return eval360_module.list_evaluadores_de_evaluado(campana_id, persona_id)


@router.post("/campanas/{campana_id}/evaluados/{persona_id}/evaluadores")
def agregar_evaluador_manual_route(
    campana_id: int, persona_id: int, body: EvaluadorManualBody, user: dict = Depends(require_admin)
):
    _require_acceso_campana(campana_id, user)
    _require_acceso_persona(body.evaluador_persona_id, user)
    eval360_module.agregar_evaluador_manual(campana_id, persona_id, body.evaluador_persona_id)
    return {"ok": True, "evaluadores": eval360_module.list_evaluadores_de_evaluado(campana_id, persona_id)}


@router.delete("/asignaciones/{asignacion_id}")
def quitar_asignacion_route(asignacion_id: int, user: dict = Depends(require_admin)):
    asignacion = eval360_module.get_asignacion(asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    _require_acceso_campana(asignacion["campana_id"], user)
    eval360_module.quitar_asignacion(asignacion_id)
    return {"ok": True}


@router.get("/campanas/{campana_id}/evaluados/{persona_id}/resultados")
def resultados_evaluado_route(campana_id: int, persona_id: int, user: dict = Depends(require_admin)):
    _require_acceso_campana(campana_id, user)
    return eval360_module.resultados_evaluado(campana_id, persona_id)


# ---------------------------------------------------------------------------
# Responder mis evaluaciones
# ---------------------------------------------------------------------------

class RespuestaBody(BaseModel):
    pregunta_id: int
    valor: int | None = None
    comentario: str | None = None


def _require_dueno_asignacion(asignacion_id: int, user: dict) -> dict:
    asignacion = eval360_module.get_asignacion(asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    evaluador = eval360_module.get_persona(asignacion["evaluador_persona_id"])
    if not evaluador or evaluador["usuario_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Esta evaluación no te corresponde a ti")
    return asignacion


@router.get("/mis-pendientes")
def mis_pendientes_route(user: dict = Depends(get_current_user)):
    return eval360_module.mis_pendientes(user["id"])


@router.get("/asignacion/{asignacion_id}")
def get_formulario_asignacion_route(asignacion_id: int, user: dict = Depends(get_current_user)):
    _require_dueno_asignacion(asignacion_id, user)
    return eval360_module.get_formulario_asignacion(asignacion_id)


@router.post("/asignacion/{asignacion_id}/respuestas")
def guardar_respuesta_route(asignacion_id: int, body: RespuestaBody, user: dict = Depends(get_current_user)):
    asignacion = _require_dueno_asignacion(asignacion_id, user)
    if asignacion["estado"] == "completada":
        raise HTTPException(status_code=400, detail="Esta evaluación ya se envió, no se puede editar")
    eval360_module.guardar_respuesta(asignacion_id, body.pregunta_id, body.valor, body.comentario)
    return {"ok": True}


@router.post("/asignacion/{asignacion_id}/finalizar")
def finalizar_asignacion_route(asignacion_id: int, user: dict = Depends(get_current_user)):
    asignacion = _require_dueno_asignacion(asignacion_id, user)
    if asignacion["estado"] == "completada":
        return {"ok": True}
    formulario = eval360_module.get_formulario_asignacion(asignacion_id)
    # Todas las preguntas son obligatorias: las likert necesitan una
    # respuesta guardada (el propio "N/A" cuenta, es una respuesta explícita
    # -- solo falta si no se tocó en absoluto); las abiertas necesitan texto
    # real, con un mínimo de 20 caracteres para evitar comentarios vacíos de
    # relleno tipo "-" o "ok".
    sin_responder = 0
    comentarios_cortos = 0
    for p in formulario["preguntas"]:
        respuesta = formulario["respuestas"].get(p["id"])
        if p["tipo"] == "likert":
            if respuesta is None:
                sin_responder += 1
        else:
            texto = (respuesta["comentario"] if respuesta else None) or ""
            if len(texto.strip()) < 20:
                comentarios_cortos += 1
    if sin_responder or comentarios_cortos:
        partes = []
        if sin_responder:
            partes.append(f"{sin_responder} pregunta(s) sin responder")
        if comentarios_cortos:
            partes.append(f"{comentarios_cortos} comentario(s) con menos de 20 caracteres")
        raise HTTPException(status_code=400, detail="Faltan: " + ", ".join(partes))
    eval360_module.finalizar_asignacion(asignacion_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Accesos: crear cuentas de portal para personas del organigrama que aún no
# tienen una vinculada. Admin-only -- crea cuentas reales, a diferencia del
# resto del módulo que solo pide tener el módulo evaluaciones360 concedido.
# ---------------------------------------------------------------------------

@router.get("/accesos")
def list_accesos_route(empresa: str = "kk", _user: dict = Depends(require_admin)):
    eval360_module.sincronizar_personas_privilegiadas()
    return eval360_module.list_personas_con_estado_acceso(empresa)


@router.post("/accesos/{persona_id}/crear")
def crear_acceso_route(persona_id: int, user: dict = Depends(require_admin)):
    _require_acceso_persona(persona_id, user)
    resultado = eval360_module.crear_acceso_para_persona(persona_id)
    if not resultado or resultado.get("error"):
        raise HTTPException(status_code=400, detail="No se pudo crear el acceso (puede que ya tenga una cuenta vinculada).")
    return {"ok": True, **resultado}


@router.post("/accesos/rellenar-emails")
def rellenar_emails_route(empresa: str = "kk", _user: dict = Depends(require_admin)):
    actualizados = eval360_module.rellenar_emails_automaticos(empresa)
    return {"ok": True, "actualizados": actualizados}
