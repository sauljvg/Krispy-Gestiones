from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

import auth as auth_module
import kpis as kpis_module
from auth_routes import get_current_user, require_admin

router = APIRouter()


class BajaManualIn(BaseModel):
    fecha_baja: str
    motivo_baja: str


class MovimientoIn(BaseModel):
    codigo_empleado: str
    tipo: str
    origen: str | None = None
    destino: str
    fecha: str


def require_kpis(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, "kpis"):
        raise HTTPException(status_code=403, detail="No tienes acceso al Dashboard de KPIs")
    return user


@router.get("/resumen")
def resumen_route(_user: dict = Depends(require_kpis)):
    return kpis_module.compute_resumen()


@router.get("/ultima-importacion")
def ultima_importacion_route(_user: dict = Depends(require_kpis)):
    return kpis_module.get_ultima_importacion()


@router.post("/importar")
async def importar_route(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx o .xls)")
    contenido = await file.read()
    try:
        resultado = kpis_module.import_excel(contenido, file.filename, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/empleados/{codigo_empleado}")
def buscar_empleado_route(codigo_empleado: str, _user: dict = Depends(require_kpis)):
    empleado = kpis_module.buscar_empleado(codigo_empleado)
    if not empleado:
        raise HTTPException(status_code=404, detail="No se encontró ningún empleado con ese código")
    return empleado


@router.patch("/empleados/{codigo_empleado}/baja")
def marcar_baja_manual_route(codigo_empleado: str, body: BajaManualIn, _user: dict = Depends(require_admin)):
    """Corrige a mano un empleado que el Excel de plantilla todavía trae como
    activo pero que ya consta de baja en Entrevista de Salida -- para cuando
    el Excel va por detrás y hace falta unificar las dos fuentes antes de la
    próxima importación."""
    try:
        return kpis_module.marcar_baja_manual(codigo_empleado, body.fecha_baja, body.motivo_baja)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/movimientos")
def listar_movimientos_route(tipo: str | None = None, _user: dict = Depends(require_kpis)):
    return kpis_module.listar_movimientos(tipo)


@router.post("/movimientos")
def crear_movimiento_route(body: MovimientoIn, user: dict = Depends(require_kpis)):
    try:
        return kpis_module.agregar_movimiento(
            body.codigo_empleado, body.tipo, body.origen, body.destino, body.fecha, user["username"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/movimientos/{movimiento_id}")
def eliminar_movimiento_route(movimiento_id: int, _user: dict = Depends(require_admin)):
    try:
        return kpis_module.eliminar_movimiento(movimiento_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
