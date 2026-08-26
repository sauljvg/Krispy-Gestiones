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


class ChequeoManualIn(BaseModel):
    tienda: str
    agregador: str
    direccion_id: int
    disponible: bool


class SesionIniciarIn(BaseModel):
    modo: str
    total_planeado: int | None = None


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


@router.post("/chequeo-manual")
def crear_chequeo_manual_route(body: ChequeoManualIn, user: dict = Depends(require_agregadores)):
    """Como POST /chequeo (el que usa el scraper) pero con sesión de usuario
    en vez de API key, sin campos de scraper (tiempo/mensaje/error) -- para
    que el propio usuario pueda confirmar a mano, desde el dashboard, el
    estado de un punto en un agregador concreto (pedido explícito del
    usuario 10/08: quiere poder priorizar y verificar puntos puntuales sin
    esperar al scraper). Reusa exactamente la misma lógica de alertas de
    transición que el chequeo del scraper -- un "dejó de estar disponible"
    confirmado a mano es tan real como uno automático."""
    transicion = agregadores_module.hubo_transicion_a_no_disponible(body.direccion_id, body.agregador)
    verificado_por = user.get("nombre") or user["username"]
    chequeo_id = agregadores_module.guardar_chequeo(
        {**body.model_dump(), "verificado_por": verificado_por}
    )
    if transicion:
        agregadores_module.registrar_alerta(
            tipo="paso_a_no_disponible",
            mensaje=agregadores_module.formatear_alerta_transicion(
                body.agregador, body.tienda, body.direccion_id, f"verificado a mano por {verificado_por}"
            ),
            tienda=body.tienda,
            agregador=body.agregador,
        )
    return {"ok": True, "chequeo_id": chequeo_id, "transicion": transicion}


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
def reformatear_direcciones_route(background_tasks: BackgroundTasks):
    """Mantenimiento puntual: pasa los puntos ya guardados al formato nuevo
    'Calle número, Ciudad, CP' (ver _construir_direccion). Re-geocodifica
    cada punto para leer sus componentes -- corre en background porque son
    varias llamadas seriadas a Nominatim, más que el timeout del proxy de
    Railway."""
    background_tasks.add_task(agregadores_module.reformatear_direcciones)
    return {"ok": True, "mensaje": "Reformateo lanzado en background, revisa /direcciones/{tienda} en un minuto"}


@router.post("/direcciones/podar", dependencies=[Depends(require_api_key)])
def podar_direcciones_route():
    """Mantenimiento puntual: desactiva los puntos del grid viejo (4 radios x
    12 ángulos) que sobran tras reducir a GRID_RADIOS_KM x GRID_ANGULOS_COUNT.
    Solo son UPDATEs, sin llamadas a Nominatim -- rápido, responde al instante."""
    return agregadores_module.podar_grid_reducido()


@router.get("/admin/almacenamiento/info", dependencies=[Depends(require_api_key)])
def info_almacenamiento_route():
    """Diagnóstico del volumen entero (DB + backups + todas las carpetas de
    subida del backend, no solo agregadores) -- para saber qué se está
    comiendo el espacio de verdad antes de borrar nada."""
    return agregadores_module.info_almacenamiento()


@router.get("/admin/almacenamiento/candidatos-huerfanos", dependencies=[Depends(require_api_key)])
def info_candidatos_huerfanos_route():
    import reclutamiento
    return reclutamiento.info_archivos_huerfanos()


@router.post("/admin/almacenamiento/candidatos-huerfanos/borrar", dependencies=[Depends(require_api_key)])
def borrar_candidatos_huerfanos_route():
    import reclutamiento
    return reclutamiento.borrar_archivos_huerfanos()


@router.get("/admin/almacenamiento/candidatos-duplicados", dependencies=[Depends(require_api_key)])
def info_candidatos_duplicados_route():
    import reclutamiento
    return reclutamiento.info_archivos_duplicados()


@router.post("/admin/almacenamiento/candidatos-duplicados/deduplicar", dependencies=[Depends(require_api_key)])
def deduplicar_candidatos_route():
    import reclutamiento
    return reclutamiento.deduplicar_archivos()


@router.get("/admin/almacenamiento/fotos-perfil", dependencies=[Depends(require_api_key)])
def info_fotos_perfil_route():
    import reclutamiento
    return reclutamiento.info_fotos_perfil()


@router.post("/admin/almacenamiento/fotos-perfil/borrar", dependencies=[Depends(require_api_key)])
def borrar_fotos_perfil_route():
    import reclutamiento
    return reclutamiento.quitar_todas_las_fotos()


@router.get("/admin/capturas/info", dependencies=[Depends(require_api_key)])
def info_capturas_route():
    """Diagnóstico: número de archivos y tamaño total en CAPTURAS_DIR."""
    return agregadores_module.info_capturas()


@router.post("/admin/capturas/limpiar-inactivas", dependencies=[Depends(require_api_key)])
def limpiar_capturas_inactivas_route():
    """Mantenimiento puntual: borra los ARCHIVOS de captura (no las filas ni
    ningún dato) de chequeos ligados a direcciones ya desactivadas -- para
    liberar espacio en el volumen sin tocar nada de lo que sigue activo."""
    return agregadores_module.limpiar_capturas_direcciones_inactivas()


@router.post("/alertas/limpiar-excepcion-vacia", dependencies=[Depends(require_api_key)])
def limpiar_alertas_excepcion_vacia_route():
    return agregadores_module.borrar_alertas_excepcion_vacia()


@router.post("/chequeos/limpiar-errores-tecnicos", dependencies=[Depends(require_api_key)])
def limpiar_chequeos_error_route():
    return agregadores_module.borrar_chequeos_error_texto()


@router.post("/sesiones/cerrar-huerfanas", dependencies=[Depends(require_api_key)])
def cerrar_sesiones_huerfanas_route():
    return {"sesiones_cerradas": agregadores_module.cerrar_sesiones_huerfanas()}


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
    return {"id": agregadores_module.iniciar_sesion(body.modo, body.total_planeado)}


@router.put("/sesiones/{sesion_id}", dependencies=[Depends(require_api_key)])
def cerrar_sesion_route(sesion_id: int, body: SesionCerrarIn):
    agregadores_module.cerrar_sesion(sesion_id, body.estado, body.chequeos_exitosos, body.chequeos_fallidos)
    return {"ok": True}


class SesionTiendaActualIn(BaseModel):
    tienda: str


@router.put("/sesiones/{sesion_id}/tienda-actual", dependencies=[Depends(require_api_key)])
def actualizar_tienda_actual_route(sesion_id: int, body: SesionTiendaActualIn):
    """El daemon avisa aquí qué tienda está recorriendo AHORA MISMO dentro de
    la pasada en curso (ver scheduler.py) -- para el contador en vivo del
    dashboard (pedido explícito del usuario 10/08, solo visible para el
    admin)."""
    agregadores_module.actualizar_tienda_actual(sesion_id, body.tienda)
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
def eliminar_direccion_route(
    direccion_id: int,
    agregador: str | None = None,
    _user: dict = Depends(require_agregadores),
):
    """Quita un punto (baja lógica). Sin `agregador`: baja global (los 3).
    Con `agregador`: solo desactiva esa capa -- el mismo punto sigue vivo
    para los otros dos agregadores (ver agregadores_direcciones_estado)."""
    if not agregadores_module.eliminar_direccion(direccion_id, agregador):
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


class DireccionReasignadaIn(BaseModel):
    tienda: str
    lat: float
    lng: float
    direccion_text: str | None = None


@router.post("/admin/direcciones/reasignada", dependencies=[Depends(require_api_key)])
def crear_direccion_reasignada_route(body: DireccionReasignadaIn):
    """Para buscar_limite_cobertura.py: cuando la búsqueda de límite de UNA
    tienda descubre un punto disponible que en realidad está más cerca de
    OTRA, se guarda aquí como punto suelto de la tienda correcta (con
    dedup si ya existe uno muy próximo) en vez de perder el dato."""
    resultado = agregadores_module.agregar_o_reusar_direccion_otra_tienda(body.tienda, body.lat, body.lng, body.direccion_text)
    if resultado is None:
        raise HTTPException(status_code=400, detail="Tienda no reconocida")
    return resultado


@router.get("/admin/chequeo-cercano", dependencies=[Depends(require_api_key)])
def chequeo_cercano_route(lat: float, lng: float, agregador: str):
    """Para buscar_limite_cobertura.py: busca un chequeo real ya hecho (de
    cualquier tienda) muy cerca de este punto para poder reutilizarlo en
    vez de repetir el mismo scrape -- evita que tiendas vecinas con zonas
    de solape (o rondas sucesivas) vuelvan a probar la misma dirección."""
    return agregadores_module.buscar_chequeo_cercano(lat, lng, agregador)


@router.get("/admin/direcciones/resumen-deduplicado", dependencies=[Depends(require_api_key)])
def resumen_deduplicado_route():
    """Vistos/faltan por agregador contando sitios reales únicos, no filas -- los
    grids de tiendas vecinas se solapan geográficamente, así que el mismo sitio real
    puede tener una fila por tienda (ver agregadores_module.UMBRAL_DUPLICADO_KM)."""
    return agregadores_module.resumen_cobertura_deduplicada()


@router.get("/admin/resumen-estados/{tienda}", dependencies=[Depends(require_api_key)])
def admin_resumen_estados_route(tienda: str):
    """Conteos por agregador (disponible/no_disponible/error/sin_datos), exactamente
    las mismas categorías que la leyenda del mapa (ver AGR_LEYENDA_AGREGADOR en
    frontend/js/agregadores.js) -- para el mini dashboard local del scraper
    (status_server.py), que quiere ver de un vistazo lo mismo que refleja el mapa
    sin tener que iniciar sesión de staff."""
    return agregadores_module.get_resumen_estados(tienda)


@router.post("/admin/direcciones/deduplicar", dependencies=[Depends(require_api_key)])
def deduplicar_direcciones_route(aplicar: bool = False, umbral_m: float = 100):
    """Encuentra (y si aplicar=true, fusiona) direcciones activas que son el mismo
    sitio real repetido en varias tiendas. aplicar=false (por defecto) solo devuelve
    el plan de fusión sin escribir nada -- para revisar antes de aplicar de verdad.
    umbral_m (metros, default 100 -- igual que agregadores_module.UMBRAL_DUPLICADO_KM)
    para poder probar un radio distinto antes de decidir si cambiar el umbral por
    defecto de verdad."""
    return agregadores_module.deduplicar_direcciones(umbral_km=umbral_m / 1000, aplicar=aplicar)


@router.post("/admin/direcciones/limpiar-sin-numero", dependencies=[Depends(require_api_key)])
def limpiar_direcciones_sin_numero_route(aplicar: bool = False):
    """Desactiva direcciones activas sin número de portal real (ver
    agregadores_module._direccion_valida) que ningún agregador haya confirmado con
    datos reales -- geocoding que colapsó en el nombre genérico de una calle/zona sin
    poder afinar más (la causa de los clusters más grandes de duplicados, ver
    /admin/direcciones/deduplicar). aplicar=false (por defecto) solo devuelve el plan."""
    return agregadores_module.direcciones_sin_numero(aplicar=aplicar)


class LimiteIn(BaseModel):
    tienda: str
    agregador: str
    angulo_grados: float
    limite_km: float | None = None
    nota: str | None = None
    lat: float | None = None
    lng: float | None = None
    direccion_text: str | None = None


@router.post("/admin/limites", dependencies=[Depends(require_api_key)])
def guardar_limite_route(body: LimiteIn):
    """Guarda el límite real de cobertura de una dirección (buscar_limite_
    cobertura.py llama esto al terminar cada ángulo) -- el dashboard lee
    esto para dibujar el polígono real en forma de estrella."""
    return agregadores_module.guardar_limite(
        body.tienda, body.agregador, body.angulo_grados, body.limite_km, body.nota,
        lat=body.lat, lng=body.lng, direccion_text=body.direccion_text,
    )


@router.get("/limites/{tienda}")
def get_limites_route(tienda: str, agregador: str | None = None, _user: dict = Depends(require_agregadores)):
    """Límites guardados de una tienda, ordenados por ángulo -- para
    dibujar el polígono real de cobertura en el dashboard."""
    return agregadores_module.get_limites(tienda, agregador)


@router.get("/geocodificar-inverso")
def geocodificar_inverso_route(lat: float, lng: float, _user: dict = Depends(require_agregadores)):
    """Reverse geocoding bajo demanda para mostrar la dirección real de un
    vértice del polígono de cobertura al abrir su popup en el dashboard --
    no se guarda en BD, solo se calcula al vuelo (agregadores_limites no
    guarda direccion_text, solo ángulo + km)."""
    texto_plano, componentes = agregadores_module._geocodificar(lat, lng)
    direccion = agregadores_module._construir_direccion(componentes) or texto_plano
    return {"direccion": direccion}


@router.get("/admin/limites/{tienda}", dependencies=[Depends(require_api_key)])
def admin_get_limites_route(tienda: str, agregador: str | None = None):
    """Igual que get_limites_route pero con API key -- para que
    buscar_limite_cobertura.py pueda saltarse ángulos ya completados al
    relanzar, en vez de rehacerlos desde cero cada vez."""
    return agregadores_module.get_limites(tienda, agregador)


@router.delete("/admin/limites/{tienda}", dependencies=[Depends(require_api_key)])
def admin_eliminar_limite_route(tienda: str, agregador: str, angulo_grados: float):
    """Borra un vértice de límite (no baja lógica -- ver eliminar_limite).
    Para limpiar vértices contaminados por cercanía a otra sucursal, o para
    forzar que un ángulo se recalcule en el próximo relanzamiento."""
    if not agregadores_module.eliminar_limite(tienda, agregador, angulo_grados):
        raise HTTPException(status_code=404, detail="Límite no encontrado")
    return {"ok": True}


@router.delete("/limites/{tienda}")
def eliminar_limite_route(
    tienda: str,
    agregador: str,
    angulo_grados: float,
    _user: dict = Depends(require_agregadores),
):
    """Igual que admin_eliminar_limite_route pero con sesión de usuario --
    para poder quitar a mano, desde el propio popup del vértice en el mapa,
    un punto del borde que se ve claramente mal (contaminado, muy alejado
    del resto) sin tener que usar la API key (pedido explícito del usuario
    10/08: quiere poder "estilizar" el borde tocando esos vértices)."""
    if not agregadores_module.eliminar_limite(tienda, agregador, angulo_grados):
        raise HTTPException(status_code=404, detail="Límite no encontrado")
    return {"ok": True}


class LimiteMoverIn(BaseModel):
    lat: float
    lng: float


@router.put("/limites/{tienda}")
def mover_limite_route(
    tienda: str,
    agregador: str,
    angulo_grados: float,
    body: LimiteMoverIn,
    _user: dict = Depends(require_agregadores),
):
    """Arrastrar un vértice del borde para ajustarlo a mano, en vez de solo
    poder borrarlo -- recalcula el límite (distancia real) desde la nueva
    posición (pedido explícito del usuario 10/08)."""
    resultado = agregadores_module.mover_limite(tienda, agregador, angulo_grados, body.lat, body.lng)
    if resultado is None:
        raise HTTPException(status_code=400, detail="Tienda no reconocida")
    return resultado


class UnionIn(BaseModel):
    tienda: str
    agregador: str
    lat_a: float
    lng_a: float
    lat_b: float
    lng_b: float
    direccion_id_a: int | None = None
    direccion_id_b: int | None = None


@router.post("/uniones")
def crear_union_route(body: UnionIn, _user: dict = Depends(require_agregadores)):
    """Puente manual entre dos puntos: el usuario ve dos dots disponibles (o
    dos vértices ya calculados del borde) con un hueco/pico raro entre
    medias y decide a ojo que ahí también hay cobertura, sin depender de un
    relleno automático poco fiable (ver agregadores_uniones, pedido
    explícito del usuario 10/08: "haré clic sobre un punto y sobre un
    segundo punto y eso va a unir el borde límite"). Por lat/lng en vez de
    direccion_id porque los vértices del borde no siempre tienen una fila de
    dirección real detrás."""
    return agregadores_module.crear_union(
        body.tienda, body.agregador, body.lat_a, body.lng_a, body.lat_b, body.lng_b,
        body.direccion_id_a, body.direccion_id_b,
    )


@router.get("/uniones/{tienda}")
def get_uniones_route(tienda: str, agregador: str | None = None, _user: dict = Depends(require_agregadores)):
    return agregadores_module.get_uniones(tienda, agregador)


@router.delete("/uniones/{union_id}")
def eliminar_union_route(union_id: int, _user: dict = Depends(require_agregadores)):
    if not agregadores_module.eliminar_union(union_id):
        raise HTTPException(status_code=404, detail="Unión no encontrada")
    return {"ok": True}


class RellenoIn(BaseModel):
    tienda: str
    agregador: str
    puntos: list[list[float]]


@router.post("/rellenos")
def crear_relleno_route(body: RellenoIn, _user: dict = Depends(require_agregadores)):
    """Pincel: zona pintada a mano (varios puntos formando un área) que se
    fusiona con el polígono calculado (turf.union en el frontend), para
    huecos DENTRO de la figura -- un puente recto entre dos puntos del borde
    (ver /uniones) no puede rellenar un hueco que no está en el borde
    (pedido explícito del usuario 10/08: "hay unas zonas que debemos poder
    rellenar dentro del mismo polígono")."""
    if len(body.puntos) < 3:
        raise HTTPException(status_code=400, detail="Hacen falta al menos 3 puntos")
    return agregadores_module.crear_relleno(body.tienda, body.agregador, body.puntos)


@router.get("/rellenos/{tienda}")
def get_rellenos_route(tienda: str, agregador: str | None = None, _user: dict = Depends(require_agregadores)):
    return agregadores_module.get_rellenos(tienda, agregador)


@router.delete("/rellenos/{relleno_id}")
def eliminar_relleno_route(relleno_id: int, _user: dict = Depends(require_agregadores)):
    if not agregadores_module.eliminar_relleno(relleno_id):
        raise HTTPException(status_code=404, detail="Relleno no encontrado")
    return {"ok": True}


@router.post("/admin/direcciones/desactivar-busqueda-limite", dependencies=[Depends(require_api_key)])
def admin_desactivar_busqueda_limite_route(tienda: str | None = None):
    """Al terminar la campaña de ángulos de una tienda (o de todas), apaga
    en bloque los puntos de sondeo que sirvieron solo para encontrar el
    límite (origen='limite') -- el límite en sí ya quedó guardado aparte en
    agregadores_limites, así que el daemon no necesita seguir revisando esos
    puntos cada día. Baja lógica: se pueden reactivar si hiciera falta."""
    n = agregadores_module.desactivar_puntos_busqueda_limite(tienda)
    return {"ok": True, "desactivados": n}


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
