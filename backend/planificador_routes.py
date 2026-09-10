from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

import auth as auth_module
import clima as clima_module
import planificador as planificador_module
from auth_routes import get_current_user

router = APIRouter()


def _modulo(empresa: str) -> str:
    return "saona_planificador" if empresa == "saona" else "planificador"


def require_planificador(empresa: str = "kk", user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, _modulo(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso al Planificador de turnos")
    return user


def _centros_permitidos(user: dict) -> list[str]:
    """Reutiliza la restricción por centro de Clima Laboral (mismo universo de
    centros). Lista vacía = sin restricción (ve todos)."""
    if user["rol"] == "admin":
        return []
    return clima_module.get_centros_permitidos(user["id"])


def _exigir_centro(user: dict, centro: str) -> None:
    permitidos = _centros_permitidos(user)
    if permitidos and centro not in permitidos:
        raise HTTPException(status_code=403, detail="No tienes acceso a ese centro")


@router.get("/centros")
def centros_route(empresa: str = "kk", user: dict = Depends(require_planificador)):
    todos = planificador_module.centros_disponibles(empresa)
    permitidos = _centros_permitidos(user)
    return {"centros": [c for c in todos if not permitidos or c in permitidos]}


@router.get("/dia")
def dia_route(empresa: str = "kk", centro: str = "", fecha: str = "", user: dict = Depends(require_planificador)):
    if not centro or not fecha:
        raise HTTPException(status_code=400, detail="Faltan centro o fecha")
    _exigir_centro(user, centro)
    return planificador_module.dia_completo(empresa, centro, fecha)


@router.get("/semana")
def semana_route(empresa: str = "kk", centro: str = "", fecha: str = "", user: dict = Depends(require_planificador)):
    if not centro or not fecha:
        raise HTTPException(status_code=400, detail="Faltan centro o fecha")
    _exigir_centro(user, centro)
    return planificador_module.semana_completa(empresa, centro, fecha)


# --- Roster ---

@router.get("/roster")
def roster_route(empresa: str = "kk", centro: str = "", user: dict = Depends(require_planificador)):
    if not centro:
        raise HTTPException(status_code=400, detail="Falta el centro")
    _exigir_centro(user, centro)
    return {"trabajadores": planificador_module.list_trabajadores(empresa, centro, incluir_inactivos=True)}


@router.post("/roster/cargar-kpis")
def roster_cargar_kpis_route(empresa: str = "kk", centro: str = "", user: dict = Depends(require_planificador)):
    if not centro:
        raise HTTPException(status_code=400, detail="Falta el centro")
    _exigir_centro(user, centro)
    return planificador_module.cargar_desde_kpis(empresa, centro)


@router.post("/roster/importar-odoo")
async def roster_importar_odoo_route(
    empresa: str = "kk", file: UploadFile = File(...), user: dict = Depends(require_planificador)
):
    # El Excel de Odoo trae TODOS los centros -> solo quien no está restringido
    # a un centro concreto puede usarlo (si no, poblaría rosters que no ve).
    if _centros_permitidos(user):
        raise HTTPException(status_code=403, detail="La importación de Odoo es solo para administración (afecta a todos los centros)")
    contenido = await file.read()
    try:
        return planificador_module.importar_odoo_excel(empresa, contenido, file.filename or "archivo.xls")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/roster/importar-planificacion")
async def roster_importar_planificacion_route(
    empresa: str = "kk", file: UploadFile = File(...), user: dict = Depends(require_planificador)
):
    """Importa un Excel de planificación de Odoo (planning.slot) como turnos.
    El centro sale de "Dirección de trabajo", así que solo administración."""
    if _centros_permitidos(user):
        raise HTTPException(status_code=403, detail="La importación de planificación es solo para administración (afecta a varios centros)")
    contenido = await file.read()
    try:
        return planificador_module.importar_planificacion_odoo(empresa, contenido, file.filename or "planning.xlsx")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class TrabajadorIn(BaseModel):
    centro: str
    nombre: str
    horas_contrato_semana: float | None = None
    rol: str | None = None


@router.post("/roster")
def crear_trabajador_route(body: TrabajadorIn, empresa: str = "kk", user: dict = Depends(require_planificador)):
    _exigir_centro(user, body.centro)
    try:
        tid = planificador_module.crear_trabajador_manual(
            empresa, body.centro, body.nombre, body.horas_contrato_semana, rol=body.rol
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": tid}


class TrabajadorUpdateIn(BaseModel):
    nombre: str | None = None
    horas_contrato_semana: float | None = None
    activo: bool | None = None
    rol: str | None = None


@router.patch("/roster/{trabajador_id}")
def actualizar_trabajador_route(
    trabajador_id: int, body: TrabajadorUpdateIn, empresa: str = "kk", user: dict = Depends(require_planificador)
):
    t = planificador_module.get_trabajador(trabajador_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Trabajador no encontrado")
    _exigir_centro(user, t["centro"])
    planificador_module.actualizar_trabajador(
        trabajador_id, nombre=body.nombre, horas_contrato_semana=body.horas_contrato_semana,
        activo=body.activo, rol=body.rol,
    )
    return {"ok": True}


@router.delete("/roster/{trabajador_id}")
def eliminar_trabajador_route(trabajador_id: int, empresa: str = "kk", user: dict = Depends(require_planificador)):
    t = planificador_module.get_trabajador(trabajador_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Trabajador no encontrado")
    _exigir_centro(user, t["centro"])
    planificador_module.eliminar_trabajador(trabajador_id)
    return {"ok": True}


# --- Turnos ---

class TurnoIn(BaseModel):
    centro: str
    fecha: str
    trabajador_id: int
    inicio_min: int
    duracion_min: int
    tipo: str = "trabajo"


@router.post("/turnos")
def crear_turno_route(body: TurnoIn, empresa: str = "kk", user: dict = Depends(require_planificador)):
    _exigir_centro(user, body.centro)
    if body.tipo not in ("trabajo", "libre", "vacaciones"):
        raise HTTPException(status_code=400, detail="Tipo de turno inválido")
    # trabajador_id 0 = slot sin asignar (no hay que validar persona).
    if body.trabajador_id != planificador_module.SIN_ASIGNAR:
        t = planificador_module.get_trabajador(body.trabajador_id)
        if t is None or t["centro"] != body.centro or t["empresa"] != empresa:
            raise HTTPException(status_code=400, detail="Ese trabajador no es de este centro")
    try:
        tid = planificador_module.crear_turno(
            empresa, body.centro, body.trabajador_id, body.fecha,
            body.inicio_min, body.duracion_min, user["username"], tipo=body.tipo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": tid}


class TurnoUpdateIn(BaseModel):
    inicio_min: int | None = None
    duracion_min: int | None = None


@router.patch("/turnos/{turno_id}")
def actualizar_turno_route(
    turno_id: int, body: TurnoUpdateIn, empresa: str = "kk", user: dict = Depends(require_planificador)
):
    t = planificador_module.get_turno(turno_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    _exigir_centro(user, t["centro"])
    try:
        planificador_module.actualizar_turno(turno_id, inicio_min=body.inicio_min, duracion_min=body.duracion_min)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/turnos/{turno_id}/fusionar/{otro_id}")
def fusionar_turnos_route(
    turno_id: int, otro_id: int, empresa: str = "kk", user: dict = Depends(require_planificador)
):
    t = planificador_module.get_turno(turno_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    _exigir_centro(user, t["centro"])
    try:
        nuevo_id = planificador_module.fusionar_turnos(turno_id, otro_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": nuevo_id}


@router.delete("/turnos/{turno_id}")
def eliminar_turno_route(turno_id: int, empresa: str = "kk", user: dict = Depends(require_planificador)):
    t = planificador_module.get_turno(turno_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    _exigir_centro(user, t["centro"])
    planificador_module.eliminar_turno(turno_id)
    return {"ok": True}


class AsignarIn(BaseModel):
    trabajador_id: int = 0  # 0 = quitar la persona (dejar sin asignar)


@router.patch("/turnos/{turno_id}/asignar")
def asignar_turno_route(
    turno_id: int, body: AsignarIn, empresa: str = "kk", user: dict = Depends(require_planificador)
):
    t = planificador_module.get_turno(turno_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    _exigir_centro(user, t["centro"])
    try:
        planificador_module.asignar_turno(turno_id, body.trabajador_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


class VacacionesIn(BaseModel):
    centro: str
    trabajador_id: int
    desde: str
    hasta: str
    quitar: bool = False


@router.post("/vacaciones")
def vacaciones_route(body: VacacionesIn, empresa: str = "kk", user: dict = Depends(require_planificador)):
    _exigir_centro(user, body.centro)
    w = planificador_module.get_trabajador(body.trabajador_id)
    if w is None or w["centro"] != body.centro or w["empresa"] != empresa:
        raise HTTPException(status_code=400, detail="Esa persona no es de este centro")
    try:
        n = planificador_module.set_vacaciones(
            empresa, body.centro, body.trabajador_id, body.desde, body.hasta, quitar=body.quitar
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "dias": n}


@router.get("/sugerencias")
def sugerencias_route(
    empresa: str = "kk", centro: str = "", fecha: str = "", inicio_min: int = 0, duracion_min: int = 0,
    user: dict = Depends(require_planificador),
):
    if not centro or not fecha or duracion_min <= 0:
        raise HTTPException(status_code=400, detail="Faltan datos")
    _exigir_centro(user, centro)
    return {"sugerencias": planificador_module.sugerencias(empresa, centro, fecha, inicio_min, duracion_min)}


@router.get("/chequeo-descanso")
def chequeo_descanso_route(
    empresa: str = "kk", centro: str = "", fecha: str = "", trabajador_id: int = 0,
    inicio_min: int = 0, duracion_min: int = 0, excluir_id: int = 0,
    user: dict = Depends(require_planificador),
):
    """Aviso previo: ¿poner ese turno a esa persona deja menos de 12 h entre
    jornadas? No bloquea nada, solo informa para pedir confirmación."""
    if not centro or not fecha or duracion_min <= 0:
        raise HTTPException(status_code=400, detail="Faltan datos")
    _exigir_centro(user, centro)
    ko, mensaje = planificador_module.chequear_descanso_persona(
        empresa, centro, trabajador_id, fecha, inicio_min, duracion_min,
        excluir_id=excluir_id or None,
    )
    return {"ko": ko, "mensaje": mensaje}


# --- Biblioteca de slots (horarios predefinidos) ---

@router.get("/slots")
def slots_route(empresa: str = "kk", centro: str = "", user: dict = Depends(require_planificador)):
    if centro:
        _exigir_centro(user, centro)
    return {"slots": planificador_module.list_slots(empresa, centro or None)}


class SlotIn(BaseModel):
    centro: str
    nombre: str
    inicio_min: int
    duracion_min: int


@router.post("/slots")
def crear_slot_route(body: SlotIn, empresa: str = "kk", user: dict = Depends(require_planificador)):
    _exigir_centro(user, body.centro)
    try:
        sid = planificador_module.crear_slot(empresa, body.centro, body.nombre, body.inicio_min, body.duracion_min)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": sid}


class SlotUpdateIn(BaseModel):
    nombre: str | None = None
    inicio_min: int | None = None
    duracion_min: int | None = None


@router.patch("/slots/{slot_id}")
def actualizar_slot_route(
    slot_id: int, body: SlotUpdateIn, empresa: str = "kk", user: dict = Depends(require_planificador)
):
    try:
        planificador_module.actualizar_slot(
            slot_id, nombre=body.nombre, inicio_min=body.inicio_min, duracion_min=body.duracion_min
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.delete("/slots/{slot_id}")
def eliminar_slot_route(slot_id: int, empresa: str = "kk", user: dict = Depends(require_planificador)):
    planificador_module.eliminar_slot(slot_id)
    return {"ok": True}


# --- Proyección ---

class ProyeccionCeldaIn(BaseModel):
    centro: str
    fecha: str
    franja_min: int
    campo: str
    valor: float | None = None


@router.put("/proyeccion")
def proyeccion_route(body: ProyeccionCeldaIn, empresa: str = "kk", user: dict = Depends(require_planificador)):
    _exigir_centro(user, body.centro)
    try:
        planificador_module.set_proyeccion_celda(
            empresa, body.centro, body.fecha, body.franja_min, body.campo, body.valor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


# --- Config del centro ---

class ConfigIn(BaseModel):
    centro: str
    apertura_min: int
    cierre_min: int
    objetivo_transacciones_hora: float | None = None
    direccion_odoo: str | None = None
    rol_odoo: str | None = None
    complementarias_jornada_completa: bool = False


@router.put("/config")
def config_route(body: ConfigIn, empresa: str = "kk", user: dict = Depends(require_planificador)):
    _exigir_centro(user, body.centro)
    try:
        planificador_module.set_config(
            empresa, body.centro, body.apertura_min, body.cierre_min, body.objetivo_transacciones_hora,
            direccion_odoo=body.direccion_odoo, rol_odoo=body.rol_odoo,
            complementarias_jornada_completa=body.complementarias_jornada_completa,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.get("/exportar-odoo")
def exportar_odoo_route(
    empresa: str = "kk", centro: str = "", desde: str = "", hasta: str = "",
    user: dict = Depends(require_planificador),
):
    if not centro or not desde or not hasta:
        raise HTTPException(status_code=400, detail="Faltan centro o fechas")
    _exigir_centro(user, centro)
    try:
        contenido = planificador_module.exportar_odoo_xlsx(empresa, centro, desde, hasta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    nombre = f"planificacion_{centro}_{desde}_{hasta}.xlsx".replace(" ", "_")
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
