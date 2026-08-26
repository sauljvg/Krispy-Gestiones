"""Cliente HTTP hacia la API en vivo de Krispy Gestiones (backend/agregadores_routes.py).

El scraper corre en un portátil aparte y no tiene sesión de usuario (no hay navegador de
por medio) — se autentica con una API key fija en vez de cookie, solo válida para estos
endpoints (ver require_api_key en el backend)."""
import logging

import aiohttp

import config

logger = logging.getLogger(__name__)


def _headers():
    return {"X-API-Key": config.KG_API_KEY, "Content-Type": "application/json"}


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
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=_headers(), timeout=90) as resp:
            resp.raise_for_status()
            return await resp.json()


async def reasignar_punto_otra_tienda(tienda: str, lat: float, lng: float, direccion_text: str | None) -> dict:
    """Cuando la búsqueda de límite de UNA tienda descubre un punto
    disponible que en realidad está más cerca de OTRA (ver 'contaminado'
    en buscar_limite_cobertura.py), se guarda aquí como punto suelto de la
    tienda correcta -- el backend evita duplicados si ya hay uno muy
    próximo guardado."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/reasignada"
    body = {"tienda": tienda, "lat": lat, "lng": lng, "direccion_text": direccion_text}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=_headers(), timeout=30) as resp:
            resp.raise_for_status()
            return await resp.json()


async def buscar_chequeo_cercano(lat: float, lng: float, agregador: str) -> dict | None:
    """Busca un chequeo real ya hecho (de cualquier tienda) muy cerca de
    este punto para reutilizarlo en vez de repetir el mismo scrape --
    evita que tiendas vecinas con zonas de solape (o rondas sucesivas de
    la misma tienda) vuelvan a probar la misma dirección real por
    separado. None si no hay nada reutilizable a menos de 100m."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/chequeo-cercano"
    params = {"lat": lat, "lng": lng, "agregador": agregador}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=_headers(), timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()


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
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=_headers(), timeout=15) as resp:
            resp.raise_for_status()


async def obtener_limites(tienda: str, agregador: str) -> list[dict]:
    """Ángulos ya completados para tienda/agregador -- para que
    buscar_limite_cobertura.py pueda saltárselos al relanzar en vez de
    rehacerlos desde cero cada vez (confirmado en vivo 08/08: cada relanzamiento
    por un fix repetía 0° de parquesur entero, sin avanzar nunca al resto)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/limites/{tienda}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params={"agregador": agregador}, headers=_headers(), timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()


async def eliminar_direccion(direccion_id: int):
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direccion/{direccion_id}"
    async with aiohttp.ClientSession() as session:
        async with session.delete(url, headers=_headers(), timeout=15) as resp:
            resp.raise_for_status()


async def obtener_direcciones(
    tienda: str, cercano: bool = False, agregador: str = None, solo_sin_datos: bool = False
) -> list[dict]:
    """`agregador`, si se pasa, hace que el backend devuelva primero los
    puntos que ese agregador todavía no ha comprobado nunca de verdad (ver
    get_o_crear_direcciones en backend/agregadores.py) -- así una pasada que
    se corta a medias cubre puntos nuevos antes que repetir los de siempre.

    `solo_sin_datos=True` va más allá: solo devuelve esos puntos, para la
    pasada previa "cubrir huecos en todas las tiendas" del scheduler."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/direcciones/{tienda}"
    params = {"cercano": str(cercano).lower()}
    if agregador:
        params["agregador"] = agregador
    if solo_sin_datos:
        params["solo_sin_datos"] = "true"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=_headers(), timeout=60) as resp:
            resp.raise_for_status()
            return await resp.json()


async def enviar_chequeo(data: dict) -> dict:
    if config.MODO_LOCAL:
        logger.info(
            "[MODO_LOCAL] chequeo no enviado a KG: %s/%s @ dir=%s disponible=%s",
            data.get("tienda"), data.get("agregador"), data.get("direccion_id"), data.get("disponible"),
        )
        return {"chequeo_id": -1, "transicion": False}

    url = f"{config.KG_API_BASE_URL}/api/agregadores/chequeo"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=_headers(), timeout=30) as resp:
            resp.raise_for_status()
            return await resp.json()


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
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, data=form, headers={"X-API-Key": config.KG_API_KEY}, timeout=30
            ) as resp:
                resp.raise_for_status()
    except Exception as exc:
        logger.error("No se pudo subir la captura de transición (chequeo %s): %s", chequeo_id, exc)


async def iniciar_sesion(modo: str, total_planeado: int | None = None) -> int:
    if config.MODO_LOCAL:
        logger.info("[MODO_LOCAL] sesión no iniciada en KG (modo=%s)", modo)
        return -1

    url = f"{config.KG_API_BASE_URL}/api/agregadores/sesiones"
    body = {"modo": modo, "total_planeado": total_planeado}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=_headers(), timeout=15) as resp:
            resp.raise_for_status()
            data = await resp.json()
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
    async with aiohttp.ClientSession() as session:
        async with session.put(url, json=body, headers=_headers(), timeout=15) as resp:
            resp.raise_for_status()


async def resumen_cobertura_deduplicada() -> dict:
    """Vistos/faltan por agregador contando sitios reales únicos (agrupados por
    proximidad entre TODAS las tiendas), no filas -- ver
    backend/agregadores.py::resumen_cobertura_deduplicada. Usado por status_server.py."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/resumen-deduplicado"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers(), timeout=30) as resp:
            resp.raise_for_status()
            return await resp.json()


async def resumen_estados(tienda: str) -> dict:
    """Conteos por agregador (disponible/no_disponible/error/sin_datos), las mismas
    categorías que la leyenda del mapa -- ver
    backend/agregadores.py::get_resumen_estados. Usado por status_server.py."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/resumen-estados/{tienda}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers(), timeout=30) as resp:
            resp.raise_for_status()
            return await resp.json()


async def deduplicar_direcciones(aplicar: bool = False, umbral_m: float = 100) -> dict:
    """Encuentra (y si aplicar=True, fusiona) direcciones activas que son el mismo
    sitio real repetido en varias tiendas -- ver
    backend/agregadores.py::deduplicar_direcciones. aplicar=False solo devuelve el
    plan, no escribe nada. umbral_m: radio en metros para considerar "el mismo sitio"
    (default 100, igual que backend/agregadores.py::UMBRAL_DUPLICADO_KM)."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/deduplicar"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, params={"aplicar": str(aplicar).lower(), "umbral_m": umbral_m}, headers=_headers(), timeout=120
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def limpiar_direcciones_sin_numero(aplicar: bool = False) -> dict:
    """Desactiva direcciones activas sin número de portal real que ningún agregador
    haya confirmado con datos reales -- ver
    backend/agregadores.py::direcciones_sin_numero. aplicar=False solo devuelve el
    plan, no escribe nada."""
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/limpiar-sin-numero"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params={"aplicar": str(aplicar).lower()}, headers=_headers(), timeout=120) as resp:
            resp.raise_for_status()
            return await resp.json()


async def actualizar_tienda_actual(sesion_id: int, tienda: str):
    if config.MODO_LOCAL or sesion_id == -1:
        return
    url = f"{config.KG_API_BASE_URL}/api/agregadores/sesiones/{sesion_id}/tienda-actual"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(url, json={"tienda": tienda}, headers=_headers(), timeout=15) as resp:
                resp.raise_for_status()
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=_headers(), timeout=15) as resp:
                resp.raise_for_status()
    except Exception as exc:
        logger.error("No se pudo registrar la alerta en KG: %s", exc)
