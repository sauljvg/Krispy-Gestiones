import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
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
    direccion_text: str | None = None


class DireccionNuevaIn(BaseModel):
    tienda: str
    lat: float
    lng: float
    direccion_text: str | None = None


# --- Endpoints del scraper (API key, sin cookie) --------------------------


@router.post("/chequeo", dependencies=[Depends(require_api_key)])
def recibir_chequeo(body: ChequeoIn):
    # Hay que mirar si el punto ESTABA disponible antes de insertar el chequeo
    # actual -- una vez insertado, "el anterior" ya seríamos nosotros mismos.
    transicion = False
    if not body.error_texto and not body.disponible:
        transicion = agregadores_module.hubo_transicion_a_no_disponible(
            body.direccion_id, body.agregador
        )

    chequeo_id = agregadores_module.guardar_chequeo(body.model_dump())

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

    if transicion:
        agregadores_module.registrar_alerta(
            tipo="paso_a_no_disponible",
            mensaje=agregadores_module.formatear_alerta_transicion(
                body.agregador, body.tienda, body.direccion_id, body.mensaje_bloqueo
            ),
            tienda=body.tienda,
            agregador=body.agregador,
        )

    return {"ok": True, "chequeo_id": chequeo_id, "transicion": transicion}


@router.post("/capturas/{chequeo_id}", dependencies=[Depends(require_api_key)])
async def subir_captura_route(chequeo_id: int, archivo: UploadFile = File(...)):
    """El scraper sube la captura de CADA chequeo (no solo transiciones) --
    se borran solas a los pocos días (ver agregadores.limpiar_capturas_viejas)
    en vez de limitar de antemano cuáles se suben."""
    contenido = await archivo.read()
    agregadores_module.guardar_captura_chequeo(chequeo_id, contenido)
    return {"ok": True}


@router.get("/capturas/{chequeo_id}")
def ver_captura_route(chequeo_id: int, _user: dict = Depends(require_agregadores)):
    ruta = agregadores_module.get_ruta_captura(chequeo_id)
    if not ruta:
        raise HTTPException(status_code=404, detail="Sin captura para este chequeo")
    return FileResponse(ruta, media_type="image/png")


@router.get("/admin/chequeos", dependencies=[Depends(require_api_key)])
def admin_listar_chequeos_route(
    tienda: str,
    agregador: str | None = None,
    horas: int = 24,
    contiene: str | None = Query(default=None, description="Filtra por texto contenido en la dirección"),
):
    """Solo para corregir a mano un dato puntual confirmado como erróneo (ver
    admin_eliminar_chequeo_route) -- no pensado para uso normal del dashboard."""
    chequeos = agregadores_module.get_ultimos(tienda, horas=horas)
    if agregador:
        chequeos = [c for c in chequeos if c["agregador"] == agregador]
    if contiene:
        chequeos = [c for c in chequeos if contiene.lower() in (c.get("direccion_text") or "").lower()]
    return chequeos


@router.delete("/admin/chequeo/{chequeo_id}", dependencies=[Depends(require_api_key)])
def admin_eliminar_chequeo_route(chequeo_id: int):
    """Borra un chequeo puntual (y su captura) -- para corregir un dato
    confirmado como erróneo, no para limpiar en bloque."""
    if not agregadores_module.eliminar_chequeo(chequeo_id):
        raise HTTPException(status_code=404, detail="Chequeo no encontrado")
    return {"ok": True}


@router.delete("/chequeo/{chequeo_id}")
def eliminar_chequeo_route(chequeo_id: int, _user: dict = Depends(require_agregadores)):
    """Igual que admin_eliminar_chequeo_route pero con sesión de usuario en
    vez de API key -- para el botón de borrar en "Dejaron de estar
    disponibles" del propio dashboard (confirmar un falso positivo, p.ej. el
    bug de coordenadas o el de fuentes bloqueadas en la captura, ya
    corregidos, pero el registro viejo se queda hasta que alguien lo borre)."""
    if not agregadores_module.eliminar_chequeo(chequeo_id):
        raise HTTPException(status_code=404, detail="Chequeo no encontrado")
    return {"ok": True}


@router.get("/transiciones")
def transiciones_route(
    tienda: str | None = None, horas: int = 24, _user: dict = Depends(require_agregadores)
):
    return agregadores_module.get_transiciones(tienda, horas)


@router.get("/direcciones/{tienda}", dependencies=[Depends(require_api_key)])
def direcciones_route(
    tienda: str, cercano: bool = False, agregador: str | None = None, solo_sin_datos: bool = False
):
    """El scraper llama esto al empezar una pasada: genera (si hace falta)
    y geocodifica el grid server-side, así el geocoding se cachea una única
    vez para todo el mundo en vez de cada portátil/proceso repitiéndolo.

    `agregador`, si se manda, prioriza los puntos que ese agregador nunca ha
    comprobado de verdad. `solo_sin_datos=True` va más allá y devuelve SOLO
    esos -- ver get_o_crear_direcciones."""
    radios = agregadores_module.GRID_RADIOS_CERCANO_KM if cercano else agregadores_module.GRID_RADIOS_KM
    return agregadores_module.get_o_crear_direcciones(tienda, radios, agregador, solo_sin_datos)


@router.post("/direcciones/reparar", dependencies=[Depends(require_api_key)])
def reparar_direcciones_route(background_tasks: BackgroundTasks):
    """Mantenimiento puntual: reubica los puntos ya guardados que cayeron en
    autovía/M-45/etc (creados antes del filtro de _direccion_valida). Corre
    en background porque son muchas llamadas seriadas a Nominatim -- puede
    tardar varios minutos, más que el timeout del proxy de Railway."""
    background_tasks.add_task(agregadores_module.reparar_direcciones_invalidas)
    return {"ok": True, "mensaje": "Reparación lanzada en background, revisa /direcciones/{tienda} en unos minutos"}


@router.post("/direcciones/reformatear", dependencies=[Depends(require_api_key)])
def reformatear_direcciones_route():
    """Mantenimiento puntual: reordena 'número, calle' -> 'calle número' en
    los puntos ya guardados con el formato viejo de Nominatim (ver
    _formatear_direccion). Solo UPDATEs de texto, sin Nominatim -- rápido,
    responde al instante, no toca chequeos."""
    return agregadores_module.reformatear_direcciones()


@router.post("/direcciones/podar", dependencies=[Depends(require_api_key)])
def podar_direcciones_route():
    """Mantenimiento puntual: desactiva los puntos del grid viejo (4 radios x
    12 ángulos) que sobran tras reducir a GRID_RADIOS_KM x GRID_ANGULOS_COUNT.
    Solo son UPDATEs, sin llamadas a Nominatim -- rápido, responde al instante."""
    return agregadores_module.podar_grid_reducido()


@router.post("/alertas/limpiar-excepcion-vacia", dependencies=[Depends(require_api_key)])
def limpiar_alertas_excepcion_vacia_route():
    return agregadores_module.borrar_alertas_excepcion_vacia()


@router.post("/chequeos/limpiar-errores-tecnicos", dependencies=[Depends(require_api_key)])
def limpiar_chequeos_error_route():
    return agregadores_module.borrar_chequeos_error_texto()


@router.post("/estadisticas/reset", dependencies=[Depends(require_api_key)])
def resetear_estadisticas_route():
    """Mantenimiento puntual: borra el histórico de chequeos y alertas de los
    3 agregadores (deja el grid de puntos intacto) -- para limpiar
    estadísticas contaminadas por un bug de lectura ya corregido."""
    return agregadores_module.resetear_estadisticas()


@router.post("/estadisticas/reset-hoy", dependencies=[Depends(require_api_key)])
def resetear_estadisticas_hoy_route():
    """Como /estadisticas/reset pero solo el día de hoy -- conserva días
    anteriores para no perder histórico de los reportes semanales."""
    return agregadores_module.resetear_estadisticas_hoy()


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


@router.get("/transiciones-consulta", dependencies=[Depends(require_api_key)])
def transiciones_consulta_route(tienda: str | None = None, horas: int = 24):
    """Misma consulta que GET /transiciones pero con API key en vez de cookie
    -- para poder tirar de esto por curl/scripts sin sesión de dashboard."""
    return agregadores_module.get_transiciones(tienda, horas)


@router.get("/cobertura")
def cobertura_route(tienda: str | None = None, agregador: str | None = None, _user: dict = Depends(require_agregadores)):
    """Último estado conocido de cada punto (disponible o no), para dibujar
    mapas de cobertura con polígonos convex/concave. Devuelve puntos verdes
    (DD) y amarillos (DND) agrupados por agregador."""
    return agregadores_module.get_cobertura_mapa(tienda, agregador)


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


class DireccionCalculadaIn(BaseModel):
    tienda: str
    distancia_km: float
    angulo_grados: float


@router.post("/admin/direcciones/calculada", dependencies=[Depends(require_api_key)])
def crear_direccion_calculada_route(body: DireccionCalculadaIn):
    """Para el script de búsqueda adaptativa del límite de cobertura (API
    key, no cookie -- lo llama el scraper, no el dashboard). Crea un punto a
    la distancia/ángulo pedidos, geocodificado con la misma búsqueda en
    espiral del grid fijo."""
    resultado = agregadores_module.crear_punto_calculado(body.tienda, body.distancia_km, body.angulo_grados)
    if resultado is None:
        raise HTTPException(status_code=400, detail="Tienda no reconocida")
    return resultado


@router.delete("/admin/direccion/{direccion_id}", dependencies=[Depends(require_api_key)])
def admin_eliminar_direccion_route(direccion_id: int):
    """Igual que eliminar_direccion_route pero con API key -- para que el
    script de búsqueda de límite pueda dar de baja los puntos del anillo de
    1km (ya sabemos que ahí siempre hay cobertura, no aportan nada)."""
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


@router.get("/mapa-datos-todas")
def mapa_datos_todas_route(_user: dict = Depends(require_agregadores)):
    return agregadores_module.get_mapa_datos_todas()


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
    tienda: str | None = None,
    fecha: str | None = Query(default=None),
    resets: str | None = Query(
        default=None,
        description='JSON {"agregador": "iso_timestamp"} -- recalcula ese agregador solo '
        "con chequeos posteriores al timestamp (ver botón 'Reiniciar contador' del dashboard, "
        "solo cambia lo que se lee, no borra nada).",
    ),
    _user: dict = Depends(require_agregadores),
):
    if fecha:
        dia = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        dia = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    resets_dict = None
    if resets:
        try:
            resets_dict = json.loads(resets)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="resets debe ser JSON válido")
    return agregadores_module.get_reporte(tienda, dia, dia + timedelta(days=1), resets_dict)


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
