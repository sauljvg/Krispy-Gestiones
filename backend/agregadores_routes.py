import csv
import io
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agregadores as agregadores_module
import auth as auth_module
from auth_routes import get_current_user

router = APIRouter()

# El scraper vive en un portátil aparte y llama a esta API sin sesión de
# usuario (no hay navegador de por medio) — se autentica con una clave fija
# en vez de cookie, solo para el POST que escribe datos.
API_KEY_ENV = "AGREGADORES_API_KEY"


def require_agregadores(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, "agregadores"):
        raise HTTPException(status_code=403, detail="No tienes acceso a Agregadores")
    return user


def require_api_key(x_api_key: str | None = Header(default=None)):
    esperada = os.environ.get(API_KEY_ENV)
    if not esperada or x_api_key != esperada:
        raise HTTPException(status_code=401, detail="API key inválida o no configurada")


class ChequeoIn(BaseModel):
    tienda: str
    agregador: str
    direccion_id: int | None = None
    disponible: bool
    tiempo_entrega_min: int | None = None
    mensaje_bloqueo: str | None = None
    error_texto: str | None = None
    timestamp: str | None = None


class SesionIniciarIn(BaseModel):
    modo: str


class SesionCerrarIn(BaseModel):
    estado: str
    chequeos_exitosos: int = 0
    chequeos_fallidos: int = 0


class AlertaIn(BaseModel):
    tipo: str
    mensaje: str
    tienda: str | None = None
    agregador: str | None = None


class DireccionMoverIn(BaseModel):
    lat: float
    lng: float
    direccion_text: str


class DireccionNuevaIn(BaseModel):
    tienda: str
    lat: float
    lng: float
    direccion_text: str


# --- Endpoints del scraper (API key, sin cookie) --------------------------


@router.post("/chequeo", dependencies=[Depends(require_api_key)])
def recibir_chequeo(body: ChequeoIn):
    agregadores_module.guardar_chequeo(body.model_dump())

    if body.error_texto:
        recientes = agregadores_module.get_ultimos(body.tienda, horas=1)
        mismos_agregador = [
            c for c in recientes if c["agregador"] == body.agregador
        ][: agregadores_module.FALLOS_CONSECUTIVOS_ALERTA]
        if len(mismos_agregador) >= agregadores_module.FALLOS_CONSECUTIVOS_ALERTA and all(
            c["error_texto"] for c in mismos_agregador
        ):
            agregadores_module.registrar_alerta(
                tipo="scraper_error",
                mensaje=(
                    f"{body.agregador}: {agregadores_module.FALLOS_CONSECUTIVOS_ALERTA}+ fallos "
                    f"consecutivos en {body.tienda}. Último: {body.error_texto}"
                ),
                tienda=body.tienda,
                agregador=body.agregador,
            )
    return {"ok": True}


@router.get("/direcciones/{tienda}", dependencies=[Depends(require_api_key)])
def direcciones_route(tienda: str, cercano: bool = False):
    """El scraper llama esto al empezar una pasada: genera (si hace falta)
    y geocodifica el grid server-side, así el geocoding se cachea una única
    vez para todo el mundo en vez de cada portátil/proceso repitiéndolo."""
    radios = agregadores_module.GRID_RADIOS_CERCANO_KM if cercano else agregadores_module.GRID_RADIOS_KM
    return agregadores_module.get_o_crear_direcciones(tienda, radios)


@router.post("/direcciones/reparar", dependencies=[Depends(require_api_key)])
def reparar_direcciones_route(background_tasks: BackgroundTasks):
    """Mantenimiento puntual: reubica los puntos ya guardados que cayeron en
    autovía/M-45/etc (creados antes del filtro de _direccion_valida). Corre
    en background porque son muchas llamadas seriadas a Nominatim -- puede
    tardar varios minutos, más que el timeout del proxy de Railway."""
    background_tasks.add_task(agregadores_module.reparar_direcciones_invalidas)
    return {"ok": True, "mensaje": "Reparación lanzada en background, revisa /direcciones/{tienda} en unos minutos"}


@router.post("/sesiones", dependencies=[Depends(require_api_key)])
def iniciar_sesion_route(body: SesionIniciarIn):
    return {"id": agregadores_module.iniciar_sesion(body.modo)}


@router.put("/sesiones/{sesion_id}", dependencies=[Depends(require_api_key)])
def cerrar_sesion_route(sesion_id: int, body: SesionCerrarIn):
    agregadores_module.cerrar_sesion(sesion_id, body.estado, body.chequeos_exitosos, body.chequeos_fallidos)
    return {"ok": True}


@router.post("/alertas", dependencies=[Depends(require_api_key)])
def crear_alerta_route(body: AlertaIn):
    agregadores_module.registrar_alerta(body.tipo, body.mensaje, body.tienda, body.agregador)
    return {"ok": True}


# --- Endpoints del dashboard (cookie de usuario) ---------------------------


@router.put("/direcciones/{direccion_id}")
def mover_direccion_route(direccion_id: int, body: DireccionMoverIn, _user: dict = Depends(require_agregadores)):
    """Reubicación manual desde el mapa: alguien arrastra el punto y confirma
    la dirección real (ej. mirando Google Maps) cuando Nominatim no acertó."""
    resultado = agregadores_module.mover_direccion_manual(direccion_id, body.lat, body.lng, body.direccion_text)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    return resultado


@router.delete("/direcciones/{direccion_id}")
def eliminar_direccion_route(direccion_id: int, _user: dict = Depends(require_agregadores)):
    """Quita un punto del grid (baja lógica) -- útil para tiendas donde no
    hacen falta tantos puntos de test."""
    if not agregadores_module.eliminar_direccion(direccion_id):
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    return {"ok": True}


@router.post("/direcciones")
def agregar_direccion_route(body: DireccionNuevaIn, _user: dict = Depends(require_agregadores)):
    """Añade un punto de test a mano (clic en el mapa), fuera del grid fijo
    de radios/ángulos -- para vigilar de cerca una zona concreta."""
    resultado = agregadores_module.agregar_direccion_manual(body.tienda, body.lat, body.lng, body.direccion_text)
    if resultado is None:
        raise HTTPException(status_code=400, detail="Tienda no reconocida")
    return resultado


@router.get("/tiendas")
def tiendas_route(_user: dict = Depends(require_agregadores)):
    return agregadores_module.get_tiendas()


@router.get("/ultimos")
def ultimos_route(tienda: str, horas: int = 24, _user: dict = Depends(require_agregadores)):
    return agregadores_module.get_ultimos(tienda, horas)


@router.get("/mapa-datos")
def mapa_datos_route(tienda: str, _user: dict = Depends(require_agregadores)):
    return agregadores_module.get_mapa_datos(tienda)


@router.get("/alertas")
def alertas_route(
    tienda: str | None = None, horas: int = 24, _user: dict = Depends(require_agregadores)
):
    return agregadores_module.get_alertas(tienda, horas)


@router.get("/config")
def config_route(_user: dict = Depends(require_agregadores)):
    m = agregadores_module
    return {
        "horarios_apertura": m.HORARIOS_APERTURA,
        "frecuencia_chequeo_cercano_min": m.FRECUENCIA_CHEQUEO_CERCANO_MIN,
        "frecuencia_chequeo_completo_min": m.FRECUENCIA_CHEQUEO_COMPLETO_MIN,
        "grid_radios_km": m.GRID_RADIOS_KM,
        "grid_radios_cercano_km": m.GRID_RADIOS_CERCANO_KM,
        "grid_angulos_count": m.GRID_ANGULOS_COUNT,
    }


@router.get("/estado")
def estado_route(_user: dict = Depends(require_agregadores)):
    return agregadores_module.get_estado()


@router.get("/reportes/diario")
def reporte_diario_route(
    tienda: str,
    fecha: str | None = Query(default=None),
    _user: dict = Depends(require_agregadores),
):
    if fecha:
        dia = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        dia = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return agregadores_module.get_reporte(tienda, dia, dia + timedelta(days=1))


@router.get("/reportes/semanal")
def reporte_semanal_route(tienda: str, _user: dict = Depends(require_agregadores)):
    hasta = datetime.now(timezone.utc)
    return agregadores_module.get_reporte(tienda, hasta - timedelta(days=7), hasta)


@router.get("/reportes/export-csv")
def export_csv_route(tienda: str, dias: int = 7, _user: dict = Depends(require_agregadores)):
    chequeos = agregadores_module.get_ultimos(tienda, horas=dias * 24)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["timestamp", "agregador", "disponible", "tiempo_entrega_min", "mensaje_bloqueo", "error_texto"]
    )
    for c in chequeos:
        writer.writerow(
            [
                c["timestamp"],
                c["agregador"],
                bool(c["disponible"]),
                c["tiempo_entrega_min"] or "",
                c["mensaje_bloqueo"] or "",
                c["error_texto"] or "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=chequeos_{tienda}.csv"},
    )
