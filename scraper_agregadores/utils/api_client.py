"""Cliente HTTP hacia la API en vivo de Krispy Gestiones (backend/agregadores_routes.py).

El scraper corre en un portátil aparte y no tiene sesión de usuario (no hay navegador de
por medio) — se autentica con una API key fija en vez de cookie, solo válida para estos
endpoints (ver require_api_key en el backend)."""
import asyncio
import logging

import aiohttp

import config

logger = logging.getLogger(__name__)

# 502/503/504: errores transitorios del servidor (Railway con una sola réplica en modo
# sleep) -- confirmado en vivo 26/08: una ráfaga de arranque (~360 peticiones a la vez
# con 60 workers) satura la réplica y devuelve 502, que antes tumbaba el proceso entero
# al no reintentarse (raise_for_status sin red de seguridad). Espera exponencial: 1s,
# 2s, 4s entre los 3 intentos.
#
# 500 añadido 27/08: el "disk I/O error" de SQLite bajo carga (ver backend/db.py)
# devuelve 500, no 502/503/504 -- sin esto ni se intentaba una segunda vez aunque el
# problema fuera intermitente (confirmado en vivo: la tasa de error de Railway
# oscilaba entre 0% y 100% en el mismo minuto varias veces). No hay riesgo real de
# duplicar el chequeo: un 500 aquí es la escritura fallando del todo, no una escritura
# que sí ocurrió pero cuya respuesta se perdió.
_ESTADOS_REINTENTABLES = {500, 502, 503, 504}
_REINTENTOS_DEFECTO = 3


def _headers():
    return {"X-API-Key": config.KG_API_KEY, "Content-Type": "application/json"}


async def _solicitar(metodo: str, url: str, *, parse_json: bool = True, reintentos: int = _REINTENTOS_DEFECTO, **kwargs):
    """Envoltorio de session.request con reintento en errores transitorios (502/503/504
    o fallo de conexión/timeout). Devuelve el JSON de la respuesta (o None si
    parse_json=False o el cuerpo viene vacío)."""
    espera = 1
    for intento in range(1, reintentos + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(metodo, url, **kwargs) as resp:
                    if resp.status in _ESTADOS_REINTENTABLES and intento < reintentos:
                        logger.warning(
                            "  %s %s -> %d, reintento %d/%d en %ds",
                            metodo, url, resp.status, intento, reintentos, espera,
                        )
                        await asyncio.sleep(espera)
                        espera *= 2
                        continue
                    resp.raise_for_status()
                    if not parse_json or resp.content_length == 0:
                        return None
                    return await resp.json()
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
            if intento < reintentos:
                logger.warning(
                    "  %s %s -> %r, reintento %d/%d en %ds", metodo, url, exc, intento, reintentos, espera,
                )
                await asyncio.sleep(espera)
                espera *= 2
                continue
            raise


async def crear_direccion_calculada(tienda: str, distancia_km: float, angulo_grados: float) -> dict:
    """Para el script de búsqueda del límite de cobertura (investigar_limite_cobertura.py):
    crea un punto de test a la distancia/ángulo pedidos, geocodificado igual que el grid
    fijo (evita autovías/puntos sin número). Devuelve el punto con la distancia/ángulo
    REALES (puede desplazarse hasta 0.5km al buscar una dirección válida cercana)."""
    # Timeout generoso: el backend puede necesitar hasta ~8 llamadas seguidas
    # a Nominatim (búsqueda en espiral, ritmo limitado a 1/seg) para encontrar
    # una dirección válida -- con red lenta eso solo ya se acerca a 30s.
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/calculada"
    body = {"tienda": tienda, "distancia_km": distancia_km, "angulo_grados": angulo_grados}
    return await _solicitar("POST", url, json=body, headers=_headers(), timeout=90)


async def reasignar_punto_otra_tienda(tienda: str, lat: float, lng: float, direccion_text: str | None) -> dict:
    """Cuando la búsqueda de límite de UNA tienda descubre un punto
    disponible que en realidad está más cerca de OTRA (ver 'contaminado'
    en buscar_limite_cobertura.py), se guarda aquí como punto suelto de la
    tienda correcta -- el backend evita duplicados si ya hay uno muy
    próximo guardado."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/reasignada"
    body = {"tienda": tienda, "lat": lat, "lng": lng, "direccion_text": direccion_text}
    return await _solicitar("POST", url, json=body, headers=_headers(), timeout=30)


async def buscar_chequeo_cercano(lat: float, lng: float, agregador: str, radio_m: float = 100) -> dict | None:
    """Busca un chequeo real ya hecho (de cualquier tienda) muy cerca de
    este punto para reutilizarlo en vez de repetir el mismo scrape --
    evita que tiendas vecinas con zonas de solape (o rondas sucesivas de
    la misma tienda) vuelvan a probar la misma dirección real por
    separado. None si no hay nada reutilizable a menos de radio_m (100m
    por defecto)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/chequeo-cercano"
    params = {"lat": lat, "lng": lng, "agregador": agregador, "radio_m": radio_m}
    return await _solicitar("GET", url, params=params, headers=_headers(), timeout=15)


async def guardar_limite(
    tienda: str, agregador: str, angulo_grados: float, limite_km: float | None, nota: str | None,
    lat: float | None = None, lng: float | None = None, direccion_text: str | None = None,
):
    """Guarda el resultado de buscar_limite_cobertura.py para una dirección
    -- el dashboard lo lee para dibujar el polígono real de cobertura
    (forma de estrella, un vértice por ángulo).

    lat/lng/direccion_text: la dirección REAL que se probó (tras la espiral
    de _punto_geocodificado_valido), para que el vértice se dibuje donde de
    verdad se comprobó la entrega y no en el punto geométrico puro centro-
    ángulo-distancia, que puede caer en medio de un parque sin calle."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/limites"
    body = {
        "tienda": tienda, "agregador": agregador, "angulo_grados": angulo_grados, "limite_km": limite_km, "nota": nota,
        "lat": lat, "lng": lng, "direccion_text": direccion_text,
    }
    await _solicitar("POST", url, json=body, headers=_headers(), timeout=15, parse_json=False)


async def obtener_limites(tienda: str, agregador: str) -> list[dict]:
    """Ángulos ya completados para tienda/agregador -- para que
    buscar_limite_cobertura.py pueda saltárselos al relanzar en vez de
    rehacerlos desde cero cada vez (confirmado en vivo 08/08: cada relanzamiento
    por un fix repetía 0° de parquesur entero, sin avanzar nunca al resto)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/limites/{tienda}"
    return await _solicitar("GET", url, params={"agregador": agregador}, headers=_headers(), timeout=15)


async def eliminar_direccion(direccion_id: int, agregador: str | None = None):
    """Sin `agregador`, desactiva el punto globalmente (los tres agregadores). Con
    `agregador`, solo para ese agregador -- ver chequear_tienda."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direccion/{direccion_id}"
    params = {"agregador": agregador} if agregador else {}
    await _solicitar("DELETE", url, params=params, headers=_headers(), timeout=15, parse_json=False)


async def obtener_direcciones(
    tienda: str, cercano: bool = False, agregador: str = None, solo_sin_datos: bool = False,
    ignorar_poligono: bool = False,
) -> list[dict]:
    """`agregador`, si se pasa, hace que el backend devuelva primero los
    puntos que ese agregador todavía no ha comprobado nunca de verdad (ver
    get_o_crear_direcciones en backend/agregadores.py) -- así una pasada que
    se corta a medias cubre puntos nuevos antes que repetir los de siempre.

    `solo_sin_datos=True` va más allá: solo devuelve esos puntos, para la
    pasada previa "cubrir huecos en todas las tiendas" del scheduler.

    `ignorar_poligono=True`: no da por buenos los puntos dentro del polígono
    de cobertura ya confirmado -- para una pasada puntual que quiera
    comprobar cada punto de verdad (ver revalidar_ubereats_sin_poligono.py)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/direcciones/{tienda}"
    params = {"cercano": str(cercano).lower()}
    if agregador:
        params["agregador"] = agregador
    if solo_sin_datos:
        params["solo_sin_datos"] = "true"
    if ignorar_poligono:
        params["ignorar_poligono"] = "true"
    return await _solicitar("GET", url, params=params, headers=_headers(), timeout=60)


async def enviar_chequeo(data: dict) -> dict:
    if config.MODO_LOCAL:
        logger.info(
            "[MODO_LOCAL] chequeo no enviado a KG: %s/%s @ dir=%s disponible=%s",
            data.get("tienda"), data.get("agregador"), data.get("direccion_id"), data.get("disponible"),
        )
        return {"chequeo_id": -1, "transicion": False}

    url = f"{config.KG_API_BASE_URL}/api/agregadores/chequeo"
    return await _solicitar("POST", url, json=data, headers=_headers(), timeout=30)


async def subir_captura(chequeo_id: int, ruta_local: str):
    """Solo se llama cuando /chequeo respondió transicion=true -- sube la
    captura que el scraper ya tenía guardada en local (ver base.py) para que
    quede visible desde el dashboard, no solo en el portátil del scraper."""
    if config.MODO_LOCAL:
        logger.info("[MODO_LOCAL] captura no subida a KG (chequeo %s): %s", chequeo_id, ruta_local)
        return

    url = f"{config.KG_API_BASE_URL}/api/agregadores/capturas/{chequeo_id}"
    try:
        with open(ruta_local, "rb") as f:
            contenido = f.read()
        form = aiohttp.FormData()
        form.add_field("archivo", contenido, filename="captura.png", content_type="image/png")
        await _solicitar(
            "POST", url, data=form, headers={"X-API-Key": config.KG_API_KEY}, timeout=30, parse_json=False
        )
    except Exception as exc:
        logger.error("No se pudo subir la captura de transición (chequeo %s): %s", chequeo_id, exc)


async def iniciar_sesion(modo: str, total_planeado: int | None = None) -> int:
    if config.MODO_LOCAL:
        logger.info("[MODO_LOCAL] sesión no iniciada en KG (modo=%s)", modo)
        return -1

    url = f"{config.KG_API_BASE_URL}/api/agregadores/sesiones"
    body = {"modo": modo, "total_planeado": total_planeado}
    data = await _solicitar("POST", url, json=body, headers=_headers(), timeout=15)
    return data["id"]


async def cerrar_sesion(sesion_id: int, estado: str, exitosos: int, fallidos: int):
    if config.MODO_LOCAL:
        logger.info(
            "[MODO_LOCAL] sesión no cerrada en KG: estado=%s exitosos=%d fallidos=%d",
            estado, exitosos, fallidos,
        )
        return

    url = f"{config.KG_API_BASE_URL}/api/agregadores/sesiones/{sesion_id}"
    body = {"estado": estado, "chequeos_exitosos": exitosos, "chequeos_fallidos": fallidos}
    await _solicitar("PUT", url, json=body, headers=_headers(), timeout=15, parse_json=False)


async def resumen_cobertura_deduplicada() -> dict:
    """Vistos/faltan por agregador contando sitios reales únicos (agrupados por
    proximidad entre TODAS las tiendas), no filas -- ver
    backend/agregadores.py::resumen_cobertura_deduplicada. Usado por status_server.py."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/resumen-deduplicado"
    return await _solicitar("GET", url, headers=_headers(), timeout=30)


async def resumen_estados_todas() -> dict:
    """Conteos por tienda+agregador (disponible/no_disponible/error/sin_datos), las
    mismas categorías Y la misma reasignación a "tienda más cercana" que usa el mapa
    -- ver backend/agregadores.py::get_resumen_estados_todas. Usado por
    status_server.py. Trae las 6 tiendas de una vez (una sola llamada, no una por
    tienda) porque agrupar por tienda-más-cercana necesita ver todos los puntos a
    la vez."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/resumen-estados"
    return await _solicitar("GET", url, headers=_headers(), timeout=30)


async def deduplicar_direcciones(aplicar: bool = False, umbral_m: float = 100) -> dict:
    """Encuentra (y si aplicar=True, fusiona) direcciones activas que son el mismo
    sitio real repetido en varias tiendas -- ver
    backend/agregadores.py::deduplicar_direcciones. aplicar=False solo devuelve el
    plan, no escribe nada. umbral_m: radio en metros para considerar "el mismo sitio"
    (default 100, igual que backend/agregadores.py::UMBRAL_DUPLICADO_KM)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/deduplicar"
    return await _solicitar(
        "POST", url, params={"aplicar": str(aplicar).lower(), "umbral_m": umbral_m}, headers=_headers(), timeout=120
    )


async def limpiar_direcciones_sin_numero(aplicar: bool = False) -> dict:
    """Desactiva direcciones activas sin número de portal real que ningún agregador
    haya confirmado con datos reales -- ver
    backend/agregadores.py::direcciones_sin_numero. aplicar=False solo devuelve el
    plan, no escribe nada."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/limpiar-sin-numero"
    return await _solicitar("POST", url, params={"aplicar": str(aplicar).lower()}, headers=_headers(), timeout=120)


async def adelgazar_direcciones(agregador: str, aplicar: bool = False, umbral_m: float = 500) -> dict:
    """Entre puntos cercanos (<umbral_m) con el mismo estado confirmado para
    `agregador`, deja uno solo (desactivado SOLO para ese agregador, no
    globalmente) -- ver backend/agregadores.py::adelgazar_por_estado.
    aplicar=False solo devuelve el plan, no escribe nada."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/adelgazar"
    params = {"agregador": agregador, "aplicar": str(aplicar).lower(), "umbral_m": umbral_m}
    return await _solicitar("POST", url, params=params, headers=_headers(), timeout=120)


async def iniciar_ronda(agregador: str, total_objetivo: int, worker_count: int) -> dict:
    """Avisa al backend de que una vuelta completa (revalidar_completo.py) empieza
    para `agregador`, con `total_objetivo` puntos repartidos entre `worker_count`
    workers -- para que el "Dashboard del scraper" en agregadores.html pueda mostrar
    progreso en vivo. Idempotente del lado del backend: llamarla desde cada worker en
    paralelo sin coordinarse entre sí es seguro (ver
    backend/agregadores.py::iniciar_ronda). `worker_count` es necesario para que
    finalizar_ronda sepa cuándo han terminado TODOS, no solo el primero (bug
    confirmado en vivo 26/08: Uber Eats se quedaba "completado" con el worker más
    rápido, mientras los otros 19 seguían trabajando)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/rondas/iniciar"
    params = {"agregador": agregador, "total_objetivo": total_objetivo, "worker_count": worker_count}
    return await _solicitar("POST", url, params=params, headers=_headers(), timeout=15)


async def ronda_hechos_ids(agregador: str) -> list[int]:
    """IDs de dirección que la ronda EN CURSO de este agregador ya cubrió --
    para que un worker relanzado tras un corte reanude en vez de volver a
    scrapear desde cero (ver backend/agregadores.py::direcciones_hechas_en_ronda).
    [] si no hay ronda en curso (nada que reanudar, se scrapea todo normal)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/rondas/hechos-ids"
    respuesta = await _solicitar("GET", url, params={"agregador": agregador}, headers=_headers(), timeout=15)
    return (respuesta or {}).get("direccion_ids", [])


async def finalizar_ronda(agregador: str):
    """Ver iniciar_ronda -- idempotente igual, cada worker la llama al terminar sin
    coordinarse con los demás."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/rondas/finalizar"
    await _solicitar("POST", url, params={"agregador": agregador}, headers=_headers(), timeout=15, parse_json=False)


async def actualizar_tienda_actual(sesion_id: int, tienda: str):
    if config.MODO_LOCAL or sesion_id == -1:
        return
    url = f"{config.KG_API_BASE_URL}/api/agregadores/sesiones/{sesion_id}/tienda-actual"
    try:
        await _solicitar("PUT", url, json={"tienda": tienda}, headers=_headers(), timeout=15, parse_json=False, reintentos=1)
    except Exception as exc:
        # Contador informativo para el dashboard -- si falla no debe tumbar
        # la pasada real de chequeos.
        logger.warning("No se pudo avisar de la tienda actual (%s): %r", tienda, exc)


async def registrar_alerta(tipo: str, mensaje: str, tienda: str = None, agregador: str = None):
    if config.MODO_LOCAL:
        logger.info("[MODO_LOCAL] alerta no registrada en KG: [%s] %s", tipo, mensaje)
        return

    url = f"{config.KG_API_BASE_URL}/api/agregadores/alertas"
    body = {"tipo": tipo, "mensaje": mensaje, "tienda": tienda, "agregador": agregador}
    try:
        await _solicitar("POST", url, json=body, headers=_headers(), timeout=15, parse_json=False, reintentos=1)
    except Exception as exc:
        logger.error("No se pudo registrar la alerta en KG: %s", exc)
