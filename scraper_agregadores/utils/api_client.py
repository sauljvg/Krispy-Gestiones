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
    url = f"{config.KG_API_BASE_URL}/api/agregadores/admin/direcciones/calculada"
    body = {"tienda": tienda, "distancia_km": distancia_km, "angulo_grados": angulo_grados}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=_headers(), timeout=30) as resp:
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


async def iniciar_sesion(modo: str) -> int:
    if config.MODO_LOCAL:
        logger.info("[MODO_LOCAL] sesión no iniciada en KG (modo=%s)", modo)
        return -1

    url = f"{config.KG_API_BASE_URL}/api/agregadores/sesiones"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"modo": modo}, headers=_headers(), timeout=15) as resp:
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
