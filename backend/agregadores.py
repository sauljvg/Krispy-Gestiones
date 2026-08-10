"""Monitoreo de disponibilidad en JustEat/Glovo/Uber Eats.

El scraper corre en un portátil aparte (necesita un navegador real, headed
para Uber Eats — ver scraper_agregadores/ en la raíz del repo) y llama a la
API en vivo (POST /api/agregadores/chequeo) con cada resultado; aquí solo se
guarda y se sirve. Nada de esto toca Selenium ni el scraper de Reseñas."""
import math
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")

from db import DATA_DIR, get_connection

# Coordenadas fijas de las tiendas monitoreadas — mismos slugs que
# scraper/status/*.json para que sea el mismo vocabulario de tienda en toda
# la app, aunque esta tabla y esa carpeta no se relacionen para nada.
TIENDAS = {
    "parquesur": {
        "nombre": "Krispy Kreme Parque Sur",
        "lat": 40.341082,
        "lng": -3.734291,
    },
    "princesa": {
        "nombre": "Krispy Kreme Princesa",
        "lat": 40.425453459430805,
        "lng": -3.7127550479062386,
    },
    "caleido": {
        "nombre": "Krispy Kreme Caleido",
        "lat": 40.47683804982206,
        "lng": -3.688842649151165,
    },
    "granplaza2": {
        "nombre": "Krispy Kreme Gran Plaza",
        "lat": 40.49067173429696,
        "lng": -3.89729127382966,
    },
    "plenilunio": {
        "nombre": "Krispy Kreme Plenilunio",
        "lat": 40.445940,
        "lng": -3.608343,
    },
    "lagavia": {
        "nombre": "Krispy Kreme La Gavia",
        "lat": 40.367859,
        "lng": -3.597440,
    },
}

AGREGADORES = ["justeat", "glovo", "ubereats"]

GRID_RADIOS_KM = [1.0, 2.5, 5.0]
GRID_RADIOS_CERCANO_KM = [1.0]
GRID_ANGULOS_COUNT = 8

HORARIOS_APERTURA = [{"inicio": 9, "fin": 22}]
FRECUENCIA_CHEQUEO_CERCANO_MIN = 10
FRECUENCIA_CHEQUEO_COMPLETO_MIN = 60
FALLOS_CONSECUTIVOS_ALERTA = 3


def ensure_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_direcciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tienda TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            distancia_km REAL NOT NULL,
            angulo_grados INTEGER NOT NULL,
            direccion_text TEXT,
            UNIQUE(tienda, distancia_km, angulo_grados)
        )
    """)
    # activo: puntos "eliminados" desde el mapa se marcan inactivos en vez de
    # borrarse -- si se borrara la fila, get_o_crear_direcciones la volvería
    # a crear en el siguiente chequeo (el hueco (tienda, distancia, angulo)
    # vuelve a estar libre). Además así el histórico de chequeos con ese
    # direccion_id sigue teniendo sentido.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_direcciones)")}
    if "activo" not in cols:
        conn.execute("ALTER TABLE agregadores_direcciones ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
    # origen: distingue el grid fijo, los puntos de sondeo de la búsqueda de
    # límite (buscar_limite_cobertura.py) y los añadidos a mano -- para poder
    # desactivar en bloque solo los de sondeo cuando la búsqueda de límite
    # termine, sin tocar el grid normal ni lo puesto a mano (ver
    # desactivar_puntos_busqueda_limite). Backfill de lo ya existente: el
    # grid se reconoce por encajar exacto en (radio, ángulo) fijos; todo lo
    # demás activo hasta ahora es de la búsqueda de límite -- "Añadir punto"
    # llevaba roto desde la consolidación del selector (09/08), así que no
    # hay puntos manuales de verdad mezclados en este momento.
    if "origen" not in cols:
        conn.execute("ALTER TABLE agregadores_direcciones ADD COLUMN origen TEXT")
        angulos_grid = [int(round((360 / GRID_ANGULOS_COUNT) * i)) for i in range(GRID_ANGULOS_COUNT)]
        marcadores_radios = ",".join("?" * len(GRID_RADIOS_KM))
        marcadores_angulos = ",".join("?" * len(angulos_grid))
        conn.execute(
            f"""UPDATE agregadores_direcciones SET origen = CASE
                WHEN distancia_km IN ({marcadores_radios}) AND angulo_grados IN ({marcadores_angulos})
                THEN 'grid' ELSE 'limite' END""",
            (*GRID_RADIOS_KM, *angulos_grid),
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_chequeos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tienda TEXT NOT NULL,
            agregador TEXT NOT NULL,
            direccion_id INTEGER,
            timestamp TEXT NOT NULL,
            disponible INTEGER NOT NULL,
            tiempo_entrega_min INTEGER,
            mensaje_bloqueo TEXT,
            error_texto TEXT
        )
    """)
    # url_captura: solo se rellena cuando el chequeo resulta ser una transición
    # real de disponible->no disponible (ver hubo_transicion_a_no_disponible) --
    # no en cada chequeo, para no subir una captura por cada uno de los muchos
    # puntos que simplemente están siempre fuera de cobertura.
    cols_chequeos = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_chequeos)")}
    if "url_captura" not in cols_chequeos:
        conn.execute("ALTER TABLE agregadores_chequeos ADD COLUMN url_captura TEXT")
    # verificado_por: nombre del usuario cuando el chequeo lo puso a mano
    # desde el dashboard (ver guardar_chequeo_manual) en vez del scraper --
    # NULL para los del scraper. Sirve para distinguir en el popup del mapa
    # un dato confirmado en vivo por una persona de uno automático (pedido
    # explícito del usuario 10/08: quiere poder priorizar y confirmar puntos
    # concretos a mano, sin esperar al scraper).
    if "verificado_por" not in cols_chequeos:
        conn.execute("ALTER TABLE agregadores_chequeos ADD COLUMN verificado_por TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tienda TEXT,
            agregador TEXT,
            tipo TEXT NOT NULL,
            mensaje TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_sesiones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            modo TEXT NOT NULL,
            fecha_inicio TEXT NOT NULL,
            fecha_fin TEXT,
            chequeos_exitosos INTEGER DEFAULT 0,
            chequeos_fallidos INTEGER DEFAULT 0,
            estado TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agr_chequeos_tienda_ts ON agregadores_chequeos(tienda, timestamp)"
    )
    # Un límite real de cobertura por (tienda, agregador, ángulo) -- lo
    # calcula buscar_limite_cobertura.py (búsqueda adaptativa) y lo guarda
    # aquí para que el dashboard pueda dibujar el polígono real (forma de
    # estrella, un vértice por ángulo) en vez de un envolvente convexo sobre
    # los puntos sueltos, que no puede representar huecos de cobertura.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_limites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tienda TEXT NOT NULL,
            agregador TEXT NOT NULL,
            angulo_grados INTEGER NOT NULL,
            limite_km REAL,
            nota TEXT,
            actualizado_en TEXT NOT NULL,
            UNIQUE(tienda, agregador, angulo_grados)
        )
    """)
    # lat/lng/direccion_text: el vértice del polígono se dibujaba en el punto
    # GEOMÉTRICO puro (centro + ángulo + distancia), que puede caer en medio
    # de un parque/campo sin ninguna calle -- el punto REALMENTE comprobado
    # por el scraper (tras la búsqueda en espiral que busca la dirección
    # numerada más cercana) puede estar unos metros/cientos de metros
    # desplazado. Guardar su lat/lng/dirección real permite dibujar el
    # vértice donde de verdad se probó la entrega, no donde cae la recta
    # (confirmado en vivo 09/08: un vértice caía dentro de Casa de Campo).
    cols_limites = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_limites)")}
    if "lat" not in cols_limites:
        conn.execute("ALTER TABLE agregadores_limites ADD COLUMN lat REAL")
    if "lng" not in cols_limites:
        conn.execute("ALTER TABLE agregadores_limites ADD COLUMN lng REAL")
    if "direccion_text" not in cols_limites:
        conn.execute("ALTER TABLE agregadores_limites ADD COLUMN direccion_text TEXT")

    # total_planeado: cuántos chequeos individuales (tienda x agregador x
    # dirección) va a hacer la pasada en curso -- el scheduler lo calcula al
    # empezar (ver scheduler.py) y lo manda aquí para que el dashboard pueda
    # mostrar un progreso real ("22/66") en vez de solo "activo/inactivo".
    cols_sesiones = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_sesiones)")}
    if "total_planeado" not in cols_sesiones:
        conn.execute("ALTER TABLE agregadores_sesiones ADD COLUMN total_planeado INTEGER")
    conn.commit()
    conn.close()


def _mover_punto(lat, lng, bearing_deg, distancia_km):
    R = 6371
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)
    lng_rad = math.radians(lng)
    lat2_rad = math.asin(
        math.sin(lat_rad) * math.cos(distancia_km / R)
        + math.cos(lat_rad) * math.sin(distancia_km / R) * math.cos(bearing_rad)
    )
    lng2_rad = lng_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(distancia_km / R) * math.cos(lat_rad),
        math.cos(distancia_km / R) - math.sin(lat_rad) * math.sin(lat2_rad),
    )
    return math.degrees(lat2_rad), math.degrees(lng2_rad)


def _distancia_y_angulo(lat_centro, lng_centro, lat, lng):
    """Inverso de _mover_punto: dado un punto puesto a mano en el mapa,
    calcula a qué distancia (línea recta) y ángulo queda del centro de la
    tienda, para guardarlo con el mismo formato que los puntos del grid."""
    R = 6371
    lat1, lng1, lat2, lng2 = map(math.radians, (lat_centro, lng_centro, lat, lng))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    distancia_km = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    bearing = math.degrees(
        math.atan2(
            math.sin(dlng) * math.cos(lat2),
            math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng),
        )
    )
    return distancia_km, (bearing + 360) % 360


_NOMINATIM_LOCK = threading.Lock()
_nominatim_ultima_llamada = 0.0
_NOMINATIM_INTERVALO_MIN_SEG = 1.1  # política de Nominatim: máx. 1 petición/segundo


def _geocodificar(lat, lng):
    """Reverse geocoding vía Nominatim. Con la búsqueda en espiral de
    _punto_geocodificado_valido ya no es "una vez por punto" -- puede haber
    varios intentos seguidos, así que aquí sí hace falta espaciar las
    llamadas o Nominatim empieza a bloquear/ralentizar el IP entero (nos
    pasó: cada llamada tardaba 5-6s y fallaba tras machacarlo sin pausas).

    Devuelve (texto_plano, componentes): el texto plano es el display_name
    genérico de Nominatim (fallback si no hay calle+número reales), y
    componentes es el dict estructurado (road, house_number, city,
    postcode...) -- de ahí se construye el formato español real, más fiable
    que adivinar por posición de comas en el texto plano."""
    global _nominatim_ultima_llamada
    with _NOMINATIM_LOCK:
        espera = _NOMINATIM_INTERVALO_MIN_SEG - (time.monotonic() - _nominatim_ultima_llamada)
        if espera > 0:
            time.sleep(espera)
        _nominatim_ultima_llamada = time.monotonic()

        try:
            from geopy.geocoders import Nominatim

            geocoder = Nominatim(user_agent="krispy-monitor-kg")
            location = geocoder.reverse(f"{lat}, {lng}", timeout=6, addressdetails=True)
            if location:
                return location.address, (location.raw.get("address") or {})
        except Exception:
            pass
        return f"({lat:.4f}, {lng:.4f})", {}


_PATRON_VIA_NO_DIRECCION = re.compile(
    r"^(Autov[ií]a|Autopista|Carretera|V[ií]a de servicio|[AMNR]-\d+\b)", re.IGNORECASE
)
_PATRON_NUMERO_LIMPIO = re.compile(r"^\d+[a-zA-Z]?$")


def _construir_direccion(componentes: dict) -> str | None:
    """'Calle número, Ciudad, CP' a partir de los componentes estructurados
    de Nominatim -- el formato real con el que se busca en España (calle
    primero), sin el barrio/distrito de en medio que solo confunde al
    autocompletado, y con el código postal para no ambiguar entre calles
    con el mismo nombre en zonas distintas. None si no hay una calle CON
    número de portal real: autovía/polígono sin número, o portal compuesto
    tipo "74,76" (Nominatim lo junta en un único campo house_number que ni
    el propio buscador de los agregadores sabe resolver de forma fiable)."""
    calle = (componentes.get("road") or "").strip()
    numero = (componentes.get("house_number") or "").strip()
    if not calle or not numero or not _PATRON_NUMERO_LIMPIO.match(numero):
        return None
    if _PATRON_VIA_NO_DIRECCION.match(calle):
        return None
    ciudad = (
        componentes.get("city") or componentes.get("town")
        or componentes.get("village") or componentes.get("municipality") or ""
    ).strip()
    cp = (componentes.get("postcode") or "").strip()
    return ", ".join([f"{calle} {numero}"] + [p for p in (ciudad, cp) if p])


def _direccion_valida(texto: str) -> bool:
    """Valida un direccion_text YA GUARDADO en la base -- para repasar filas
    existentes, que pueden venir tanto en el formato nuevo ("Calle X 20,
    Alcorcón, 28923") como en el crudo de Nominatim de antes de este cambio
    ("20, Calle X, Barrio, ..."). Para geocodificar puntos nuevos se usa
    _construir_direccion, que es más fiable porque parte de los componentes
    estructurados en vez de adivinar por comas."""
    t = texto.strip()
    primer_segmento = t.split(",", 1)[0].strip()
    if _PATRON_VIA_NO_DIRECCION.match(primer_segmento):
        return False
    if _PATRON_NUMERO_LIMPIO.match(primer_segmento):
        # Formato crudo viejo "74, Calle X, ..." -- si el siguiente trozo
        # también empieza por dígitos, en realidad es un portal compuesto
        # tipo "74,76" partido por la coma, no una calle real.
        resto = t.split(",", 2)
        siguiente = resto[1].strip() if len(resto) > 1 else ""
        return not re.match(r"^\d", siguiente)
    ultima_palabra = primer_segmento.rsplit(" ", 1)[-1] if primer_segmento else ""
    return bool(_PATRON_NUMERO_LIMPIO.match(ultima_palabra)) and " " in primer_segmento


def _punto_geocodificado_valido(lat, lng, intentos_extra=7, paso_km=0.07, radio_max_km=0.5):
    """Geocodifica un punto y, si no es una calle con número real, prueba
    puntos cercanos en espiral alrededor del MISMO punto original (nunca más
    lejos de radio_max_km, para que siga representando ese sitio del círculo
    y no se desplace de zona) hasta encontrar una dirección numerada válida.
    Si agota los intentos, se queda con el último probado (texto plano, para
    que quede algo legible aunque no sea una dirección válida)."""
    lat0, lng0 = lat, lng
    texto_plano, componentes = _geocodificar(lat, lng)
    texto = _construir_direccion(componentes)
    if texto:
        return lat, lng, texto

    mejor = (lat, lng, texto_plano)
    for intento in range(1, intentos_extra + 1):
        radio = min(paso_km * intento, radio_max_km)
        bearing = (intento * 137) % 360  # ángulo dorado: cubre el círculo sin repetir dirección
        lat_i, lng_i = _mover_punto(lat0, lng0, bearing, radio)
        texto_plano_i, componentes_i = _geocodificar(lat_i, lng_i)
        texto_i = _construir_direccion(componentes_i)
        mejor = (lat_i, lng_i, texto_i or texto_plano_i)
        if texto_i:
            return lat_i, lng_i, texto_i
    return mejor


def reparar_direcciones_invalidas() -> dict:
    """Recorre los puntos ya guardados y reubica los que no tienen número de
    portal real (sin él, el autocompletado de los agregadores es ambiguo --
    confirmado en vivo: pasa incluso mandando el texto tal cual, no es solo
    un problema de coordenadas en bruto). Actualiza la misma fila (mismo id),
    pero como el punto pasa a ser una dirección FÍSICA DISTINTA, los chequeos
    que tenía guardados ya no dicen nada de la nueva -- se borran (no solo el
    dato, el punto "pasa a sin datos otra vez") para que el scheduler lo
    priorice en la próxima pasada (ver get_o_crear_direcciones/scheduler.py)."""
    conn = get_connection()
    filas = conn.execute("SELECT * FROM agregadores_direcciones").fetchall()
    reparadas = []
    for fila in filas:
        if _direccion_valida(fila["direccion_text"]):
            continue
        lat, lng, texto = _punto_geocodificado_valido(fila["lat"], fila["lng"])
        conn.execute(
            "UPDATE agregadores_direcciones SET lat=?, lng=?, direccion_text=? WHERE id=?",
            (lat, lng, texto, fila["id"]),
        )
        conn.execute("DELETE FROM agregadores_chequeos WHERE direccion_id=?", (fila["id"],))
        # Commit por fila, no al final: cada punto tarda varios segundos en
        # geocodificar (varios intentos a Nominatim), así que un commit único
        # al final mantendría la escritura abierta -- y el archivo bloqueado
        # para cualquier otra petición -- durante toda la duración del repaso.
        conn.commit()
        reparadas.append({"id": fila["id"], "antes": fila["direccion_text"], "despues": texto})
    conn.close()
    return {"reparadas": len(reparadas), "detalle": reparadas}


def reformatear_direcciones() -> dict:
    """Pasada única para pasar los puntos ya guardados ANTES de este cambio
    al formato nuevo 'Calle número, Ciudad, CP' (ver _construir_direccion).
    Re-geocodifica el mismo lat/lng exacto que ya tenían (no busca uno
    nuevo) solo para leer los componentes estructurados -- el resultado
    debería ser la misma calle de siempre, así que NO se tocan los chequeos
    que ya tenía la fila (a diferencia de reparar_direcciones_invalidas,
    que si reubica de verdad el punto). Si por lo que sea la nueva lectura
    no da una dirección válida, se deja el texto de antes tal cual."""
    conn = get_connection()
    filas = conn.execute("SELECT id, lat, lng, direccion_text FROM agregadores_direcciones WHERE activo=1").fetchall()
    cambiadas = []
    for fila in filas:
        _, componentes = _geocodificar(fila["lat"], fila["lng"])
        nuevo = _construir_direccion(componentes)
        if nuevo and nuevo != fila["direccion_text"]:
            conn.execute("UPDATE agregadores_direcciones SET direccion_text=? WHERE id=?", (nuevo, fila["id"]))
            cambiadas.append({"id": fila["id"], "antes": fila["direccion_text"], "despues": nuevo})
        conn.commit()
    conn.close()
    return {"cambiadas": len(cambiadas), "detalle": cambiadas}


def mover_direccion_manual(direccion_id: int, lat: float, lng: float, direccion_text: str = None) -> dict | None:
    """Reubicación manual desde el mapa del dashboard (arrastrar un punto).
    Sin texto de dirección, se geocodifica automáticamente la posición nueva
    -- si no, el texto quedaría desactualizado (el de antes de arrastrar, ya
    no corresponde a dónde está el punto ahora).

    Al ser ahora una dirección física distinta, los chequeos que tenía
    guardados se borran -- el punto "pasa a sin datos" y el scheduler lo
    prioriza en la siguiente pasada (mismo criterio que
    reparar_direcciones_invalidas)."""
    conn = get_connection()
    fila = conn.execute("SELECT id FROM agregadores_direcciones WHERE id=?", (direccion_id,)).fetchone()
    if not fila:
        conn.close()
        return None
    if not direccion_text:
        # Aquí NO se usa la búsqueda en espiral: es una reubicación manual,
        # el punto tiene que quedarse exactamente donde lo soltó quien lo
        # arrastró -- solo se consulta la dirección de ESE punto para
        # mostrarla, sin desplazarlo si no tiene número de portal cerca (eso
        # sería ignorar la decisión de quien lo movió a propósito).
        # _geocodificar devuelve (texto_plano, componentes) -- asignar la
        # tupla entera a direccion_text (bug real, confirmado en producción
        # 09/08 con "Error binding parameter 6: type 'tuple' is not
        # supported") rompía CUALQUIER arrastre sin dirección ya conocida.
        texto_plano, componentes = _geocodificar(lat, lng)
        direccion_text = _construir_direccion(componentes) or texto_plano
    conn.execute(
        "UPDATE agregadores_direcciones SET lat=?, lng=?, direccion_text=? WHERE id=?",
        (lat, lng, direccion_text, direccion_id),
    )
    conn.execute("DELETE FROM agregadores_chequeos WHERE direccion_id=?", (direccion_id,))
    conn.commit()
    fila = conn.execute("SELECT * FROM agregadores_direcciones WHERE id=?", (direccion_id,)).fetchone()
    conn.close()
    return dict(fila)


def formatear_alerta_transicion(agregador: str, tienda: str, direccion_id: int | None, mensaje_bloqueo: str | None) -> str:
    """Mensaje de la alerta 'paso_a_no_disponible' -- antes solo llevaba el
    slug interno de la tienda ("granplaza2") sin decir QUÉ punto exacto dejó
    de estar disponible, aunque el dato ya está guardado y "Dejaron de estar
    disponibles" sí lo muestra para el mismo evento. Se usa el nombre real de
    la tienda y, si hay direccion_id, la dirección completa de ese punto."""
    nombre_tienda = TIENDAS.get(tienda, {}).get("nombre", tienda)
    direccion_text = None
    if direccion_id:
        conn = get_connection()
        fila = conn.execute(
            "SELECT direccion_text FROM agregadores_direcciones WHERE id=?", (direccion_id,)
        ).fetchone()
        conn.close()
        direccion_text = fila["direccion_text"] if fila else None
    ubicacion = direccion_text or f"tienda {nombre_tienda}"
    return f"{agregador}: {ubicacion} dejó de estar disponible. {mensaje_bloqueo or ''}".strip()


def eliminar_direccion(direccion_id: int) -> bool:
    """Baja lógica (activo=0), no DELETE -- si se borrara la fila, el hueco
    (tienda, distancia, angulo) quedaría libre y get_o_crear_direcciones lo
    volvería a generar (y geocodificar) en el siguiente chequeo."""
    conn = get_connection()
    fila = conn.execute("SELECT id FROM agregadores_direcciones WHERE id=?", (direccion_id,)).fetchone()
    if not fila:
        conn.close()
        return False
    conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE id=?", (direccion_id,))
    conn.commit()
    conn.close()
    return True


def podar_grid_reducido() -> dict:
    """Mantenimiento puntual: desactiva (activo=0) los puntos ya generados
    con el grid viejo (4 radios x 12 ángulos) que ya no encajan en el grid
    reducido actual (GRID_RADIOS_KM x GRID_ANGULOS_COUNT) -- radio 7km fuera,
    y de 12 a 8 ángulos por radio. Los puntos añadidos a mano (fuera del
    grid, con su propio distancia/angulo) no se tocan. Baja lógica, igual
    que eliminar_direccion -- no vuelven a regenerarse solos."""
    angulos_validos = {round((360 / GRID_ANGULOS_COUNT) * i) for i in range(GRID_ANGULOS_COUNT)}
    radios_validos = set(GRID_RADIOS_KM)

    conn = get_connection()
    filas = conn.execute(
        "SELECT id, distancia_km, angulo_grados FROM agregadores_direcciones WHERE activo=1"
    ).fetchall()
    podados = 0
    for fila in filas:
        # Solo puntos del grid original de 12 ángulos (múltiplos de 30) --
        # así no se tocan puntos añadidos a mano con ángulos arbitrarios.
        es_del_grid_original = fila["angulo_grados"] % 30 == 0
        if not es_del_grid_original:
            continue
        if fila["distancia_km"] not in radios_validos or fila["angulo_grados"] not in angulos_validos:
            conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE id=?", (fila["id"],))
            podados += 1
    conn.commit()
    conn.close()
    return {"podados": podados}
    return True


def crear_punto_calculado(tienda: str, distancia_km: float, angulo_grados: float) -> dict | None:
    """Como el grid fijo, pero para una distancia/ángulo CUALQUIERA (no solo
    GRID_RADIOS_KM) -- para la búsqueda adaptativa del límite real de
    cobertura (un punto por iteración del binary search, en la dirección que
    toque). Usa la misma búsqueda en espiral que el grid (evita autovías/
    puntos sin número de portal), así que el punto final puede quedar hasta
    0.5km desdesplazado del pedido -- por eso se devuelve la distancia/
    ángulo REALES del punto ya geocodificado, no los pedidos."""
    if tienda not in TIENDAS:
        return None
    info = TIENDAS[tienda]
    lat_dest, lng_dest = _mover_punto(info["lat"], info["lng"], angulo_grados, distancia_km)
    lat_final, lng_final, direccion_text = _punto_geocodificado_valido(lat_dest, lng_dest)
    distancia_real, angulo_real = _distancia_y_angulo(info["lat"], info["lng"], lat_final, lng_final)

    distancia_guardar = round(distancia_real, 3)
    angulo_guardar = int(round(angulo_real))

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO agregadores_direcciones
               (tienda, lat, lng, distancia_km, angulo_grados, direccion_text, activo, origen)
               VALUES (?, ?, ?, ?, ?, ?, 1, 'limite')""",
            (tienda, lat_final, lng_final, distancia_guardar, angulo_guardar, direccion_text),
        )
        conn.commit()
        fila = conn.execute("SELECT * FROM agregadores_direcciones WHERE id=?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError:
        # Dos peticiones distintas (dos pasos del binary search, o dos
        # empujones de ángulo) pueden geocodificar al MISMO punto real más
        # cercano si están a menos de la distancia de redondeo -- choca con
        # el índice único (tienda, distancia_km, angulo_grados) del grid fijo.
        # No es un fallo: simplemente ya existe ese punto exacto, se reusa
        # (mismo patrón que get_o_crear_direcciones para el grid normal).
        conn.rollback()
        fila = conn.execute(
            "SELECT * FROM agregadores_direcciones WHERE tienda=? AND distancia_km=? AND angulo_grados=?",
            (tienda, distancia_guardar, angulo_guardar),
        ).fetchone()
        if fila and not fila["activo"]:
            conn.execute("UPDATE agregadores_direcciones SET activo=1 WHERE id=?", (fila["id"],))
            conn.commit()
            fila = conn.execute("SELECT * FROM agregadores_direcciones WHERE id=?", (fila["id"],)).fetchone()
    conn.close()
    resultado = dict(fila)
    # La búsqueda en espiral puede agotar los intentos sin encontrar nada
    # válido (p.ej. cae en plena M-40) y quedarse con el último probado --
    # sigue siendo inválido. El que llama (script de límite de cobertura)
    # necesita saberlo para no tratar ese chequeo como un dato real.
    resultado["direccion_valida"] = _direccion_valida(direccion_text)
    # Con varias tiendas relativamente cerca (ej. Princesa y Caleido, a
    # 6km), la búsqueda del límite real de UNA tienda puede acabar probando
    # una dirección que en realidad está más cerca de OTRA sucursal -- si
    # ahí sale "disponible", puede ser porque responde la otra tienda, no la
    # que se está midiendo (el buscador de los agregadores solo busca por
    # marca "Krispy Kreme", no distingue sucursal). El que llama necesita
    # saber esto para no tratarlo como límite real de `tienda`.
    resultado["tienda_mas_cercana"] = _tienda_mas_cercana(fila["lat"], fila["lng"])
    return resultado


def _tienda_mas_cercana(lat: float, lng: float) -> str:
    """De las 6 sucursales, cuál está geográficamente más cerca de este
    punto -- para detectar cuándo un punto de test de una tienda cae en
    realidad más cerca de otra (ver crear_punto_calculado)."""
    mejor_tienda, mejor_distancia = None, None
    for nombre, info in TIENDAS.items():
        distancia, _ = _distancia_y_angulo(info["lat"], info["lng"], lat, lng)
        if mejor_distancia is None or distancia < mejor_distancia:
            mejor_tienda, mejor_distancia = nombre, distancia
    return mejor_tienda


def guardar_limite(
    tienda: str, agregador: str, angulo_grados: float, limite_km: float | None, nota: str | None,
    lat: float | None = None, lng: float | None = None, direccion_text: str | None = None,
) -> dict:
    """Guarda (o actualiza) el límite real de cobertura calculado por
    buscar_limite_cobertura.py para una dirección concreta -- lo llama el
    script al terminar cada ángulo, así el dashboard puede dibujar el
    polígono real (un vértice por ángulo) sin esperar a que termine toda la
    tienda.

    lat/lng/direccion_text (opcionales, para compatibilidad con filas viejas):
    la dirección REAL que se probó (tras la búsqueda en espiral que busca la
    calle numerada más cercana al punto geométrico puro), para que el
    dashboard pueda dibujar el vértice donde de verdad se comprobó la
    entrega en vez de en la recta centro-ángulo-distancia, que puede caer en
    medio de un parque sin ninguna calle."""
    angulo_guardar = int(round(angulo_grados))
    conn = get_connection()
    conn.execute(
        """INSERT INTO agregadores_limites (tienda, agregador, angulo_grados, limite_km, nota, actualizado_en, lat, lng, direccion_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(tienda, agregador, angulo_grados)
           DO UPDATE SET limite_km=excluded.limite_km, nota=excluded.nota, actualizado_en=excluded.actualizado_en,
                          lat=excluded.lat, lng=excluded.lng, direccion_text=excluded.direccion_text""",
        (tienda, agregador, angulo_guardar, limite_km, nota, datetime.now(timezone.utc).isoformat(), lat, lng, direccion_text),
    )
    conn.commit()
    conn.close()
    return {
        "tienda": tienda, "agregador": agregador, "angulo_grados": angulo_guardar, "limite_km": limite_km,
        "nota": nota, "lat": lat, "lng": lng, "direccion_text": direccion_text,
    }


def eliminar_limite(tienda: str, agregador: str, angulo_grados: float) -> bool:
    """Borra un vértice de límite guardado (no baja lógica -- a diferencia
    de agregadores_direcciones, aquí no hay riesgo de que se regenere solo:
    el skip-logic de buscar_limite_cobertura.py trata CUALQUIER fila
    existente para ese ángulo como "ya completado", así que hay que
    borrarla de verdad para que un relanzamiento futuro lo vuelva a
    calcular. Para limpiar vértices contaminados por cercanía a otra
    sucursal (ver resultado_punto en el script)."""
    angulo_guardar = int(round(angulo_grados))
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM agregadores_limites WHERE tienda=? AND agregador=? AND angulo_grados=?",
        (tienda, agregador, angulo_guardar),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_limites(tienda: str, agregador: str = None) -> list[dict]:
    """Límites guardados para una tienda -- ordenados por ángulo, para que
    el frontend pueda conectar los vértices en orden sin tener que
    ordenarlos él. Si se pasa agregador, filtra a ese solo."""
    conn = get_connection()
    if agregador:
        filas = conn.execute(
            "SELECT * FROM agregadores_limites WHERE tienda=? AND agregador=? ORDER BY angulo_grados",
            (tienda, agregador),
        ).fetchall()
    else:
        filas = conn.execute(
            "SELECT * FROM agregadores_limites WHERE tienda=? ORDER BY agregador, angulo_grados",
            (tienda,),
        ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def agregar_direccion_manual(tienda: str, lat: float, lng: float, direccion_text: str = None) -> dict | None:
    """Punto añadido a mano en el mapa (no del grid de radios/ángulos fijo)
    -- útil para tiendas donde el grid estándar no encaja bien (ej. una zona
    comercial concreta que interesa vigilar más de cerca). Sin texto de
    dirección, se geocodifica automáticamente (misma búsqueda en espiral que
    usa el grid) en vez de pedirle a quien hace clic que la escriba a mano."""
    if tienda not in TIENDAS:
        return None
    info = TIENDAS[tienda]

    if not direccion_text:
        # Igual que en mover_direccion_manual: sin espiral, el punto se
        # queda donde se hizo clic. _geocodificar devuelve (texto_plano,
        # componentes) -- ver el fix ahí mismo, mismo bug aquí (confirmado
        # en producción 09/08: "Añadir punto" siempre fallaba con 500).
        texto_plano, componentes = _geocodificar(lat, lng)
        direccion_text = _construir_direccion(componentes) or texto_plano
    distancia_km, angulo_grados = _distancia_y_angulo(info["lat"], info["lng"], lat, lng)

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO agregadores_direcciones
           (tienda, lat, lng, distancia_km, angulo_grados, direccion_text, activo, origen)
           VALUES (?, ?, ?, ?, ?, ?, 1, 'manual')""",
        (tienda, lat, lng, distancia_km, int(round(angulo_grados)), direccion_text),
    )
    conn.commit()
    fila = conn.execute("SELECT * FROM agregadores_direcciones WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(fila)


def desactivar_puntos_busqueda_limite(tienda: str | None = None) -> int:
    """Al terminar la búsqueda de límite de una tienda (o de todas), los
    puntos de sondeo que se usaron para encontrarlo (crear_punto_calculado,
    origen='limite') dejan de tener sentido en la rotación diaria del daemon
    -- su única función era descubrir el límite en sí, que ya quedó guardado
    aparte en agregadores_limites (independiente de esta tabla), no vigilar
    cobertura día a día. Sin esto, cada ronda de ángulos (8->16->32...) deja
    para siempre cientos de puntos activos que el daemon vuelve a comprobar
    en cada vuelta sin aportar nada nuevo (pedido explícito del usuario
    09/08: 'que revise únicamente los dots que le pongamos a mano', para no
    alargar el ciclo diario reconstruyendo el borde una y otra vez). Baja
    lógica (activo=0), igual que eliminar_direccion -- no se pierden, se
    pueden reactivar si hiciera falta."""
    conn = get_connection()
    if tienda:
        cur = conn.execute(
            "UPDATE agregadores_direcciones SET activo=0 WHERE origen='limite' AND activo=1 AND tienda=?",
            (tienda,),
        )
    else:
        cur = conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE origen='limite' AND activo=1")
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def buscar_chequeo_cercano(lat: float, lng: float, agregador: str, radio_km: float = 0.1, horas_max: int = 24) -> dict | None:
    """Busca un chequeo real ya hecho (de CUALQUIER tienda) muy cerca de
    este punto exacto para este agregador -- si existe, se puede reutilizar
    su resultado en vez de scrapear la misma dirección real otra vez desde
    otra tienda (zonas de solape entre sucursales vecinas) o en una ronda
    posterior (8->16->32 ángulos). El radio es deliberadamente pequeño
    (100m): es "¿ya probamos ESTA calle?", no "¿ya sabemos algo de esta
    zona?" -- no se puede asumir que toda una zona comparte resultado (la
    frontera real entre dos tiendas no es el punto medio geométrico,
    aclarado por el usuario 09/08). Solo cuenta chequeos de las últimas
    horas_max horas, para no reutilizar datos ya viejos."""
    conn = get_connection()
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas_max)).isoformat()
    filas = conn.execute(
        """SELECT d.tienda, d.lat, d.lng, d.direccion_text, c.disponible, c.timestamp
           FROM agregadores_chequeos c
           JOIN agregadores_direcciones d ON d.id = c.direccion_id
           WHERE c.agregador = ? AND c.error_texto IS NULL AND c.timestamp >= ? AND d.activo = 1
           ORDER BY c.timestamp DESC""",
        (agregador, desde),
    ).fetchall()
    conn.close()

    mejor = None
    mejor_distancia = None
    vistas = set()
    for fila in filas:
        # Ya vienen ordenadas por timestamp desc -- solo el chequeo más
        # reciente por dirección real (la misma dirección puede tener
        # muchos chequeos a lo largo de la noche).
        clave = (fila["tienda"], round(fila["lat"], 6), round(fila["lng"], 6))
        if clave in vistas:
            continue
        vistas.add(clave)
        distancia, _ = _distancia_y_angulo(fila["lat"], fila["lng"], lat, lng)
        if distancia <= radio_km and (mejor_distancia is None or distancia < mejor_distancia):
            mejor, mejor_distancia = fila, distancia
    if mejor is None:
        return None
    return {
        "disponible": bool(mejor["disponible"]),
        "distancia_km": round(mejor_distancia, 4),
        "tienda_origen": mejor["tienda"],
        "direccion_text": mejor["direccion_text"],
    }


def agregar_o_reusar_direccion_otra_tienda(tienda: str, lat: float, lng: float, direccion_text: str | None) -> dict | None:
    """Como agregar_direccion_manual, pero reutiliza un punto ya existente
    si hay uno muy cercano (<0.05km) para esta tienda en vez de duplicar.

    Pensado para cuando la búsqueda de límite de OTRA tienda descubre por
    casualidad un punto disponible que en realidad está más cerca de esta
    (ver 'contaminado' en buscar_limite_cobertura.py) -- en vez de
    descartar ese dato, se guarda aquí como punto suelto real de esta
    tienda. Sin el dedup, la misma zona de solape generaría un punto
    duplicado cada vez que otra tienda vuelve a pasar por ahí en rondas
    sucesivas (8->16->32 ángulos, o entre agregadores distintos)."""
    if tienda not in TIENDAS:
        return None
    conn = get_connection()
    existentes = conn.execute(
        "SELECT * FROM agregadores_direcciones WHERE tienda=? AND activo=1", (tienda,)
    ).fetchall()
    for fila in existentes:
        distancia_a_existente, _ = _distancia_y_angulo(fila["lat"], fila["lng"], lat, lng)
        if distancia_a_existente < 0.05:
            conn.close()
            return dict(fila)
    conn.close()
    return agregar_direccion_manual(tienda, lat, lng, direccion_text)


def _con_datos_reales(conn, resultado: list[dict], agregador: str) -> set:
    """IDs de direcciones que ya tienen al menos un chequeo real (sin contar
    fallos técnicos, que no dicen nada sobre si reparte o no) de este
    agregador."""
    if not resultado:
        return set()
    ids = [r["id"] for r in resultado]
    marcadores = ",".join("?" * len(ids))
    return {
        row["direccion_id"]
        for row in conn.execute(
            f"""SELECT DISTINCT direccion_id FROM agregadores_chequeos
                WHERE agregador=? AND error_texto IS NULL AND direccion_id IN ({marcadores})""",
            (agregador, *ids),
        ).fetchall()
    }


def _radio_limite(fila) -> float | None:
    """Mismo criterio que agrRadioDeLimite() en el frontend (agregadores.js):
    limite_km si existe, si no un número aprovechable del texto de la nota
    (">= 5.0km", "no disponible incluso a 0.77km"...). Se mantiene igual en
    los dos sitios a propósito -- si un punto ya "cuenta" como cobertura
    confirmada aquí, el polígono que ve el usuario en el mapa debe estar de
    acuerdo, si no parecería que el scraper se salta puntos sin motivo
    visible."""
    if fila["limite_km"] is not None:
        return fila["limite_km"]
    m = re.search(r"(\d+\.?\d*)\s*km", fila["nota"] or "")
    return float(m.group(1)) if m else None


def _cobertura_confirmada_por_limite(conn, tienda: str, agregador: str, resultado: list[dict]) -> set:
    """IDs de direcciones que caen DENTRO del polígono de límite real ya
    confirmado de este agregador en esta tienda -- no hace falta comprobarlas
    aunque no tengan chequeo propio: la búsqueda de límite (binaria, por
    ángulo) ya demuestra que ese punto está en zona de reparto. Cada
    agregador tiene su propio límite, así que un punto "sin datos" de JustEat
    con el límite de JustEat ya confirmado ahí puede seguir siendo frontera
    real para Glovo si el límite de Glovo no ha llegado tan lejos todavía --
    por eso esto se calcula por agregador, no una vez por tienda (pedido
    explícito del usuario 10/08, con un caso real: los mismos puntos grises
    de JustEat, ya dentro de su borde confirmado, seguían siendo frontera
    real de Glovo con un polígono bastante más pequeño)."""
    info = TIENDAS.get(tienda)
    if not info or not resultado:
        return set()
    limites = conn.execute(
        "SELECT * FROM agregadores_limites WHERE tienda=? AND agregador=?", (tienda, agregador)
    ).fetchall()
    vertices = []
    for fila in limites:
        radio = _radio_limite(fila)
        if radio is None:
            continue
        if fila["lat"] is not None and fila["lng"] is not None:
            _, angulo = _distancia_y_angulo(info["lat"], info["lng"], fila["lat"], fila["lng"])
        else:
            angulo = fila["angulo_grados"] % 360
        vertices.append((angulo, max(radio, 0.05)))
    # Con menos de 3 vértices no hay polígono real que cierre -- sin límite
    # fiable, todo sigue contando como "sin datos" (se prefiere comprobar de
    # más a asumir cobertura sin base).
    if len(vertices) < 3:
        return set()
    vertices.sort(key=lambda v: v[0])
    n = len(vertices)

    def radio_interpolado(bearing: float) -> float | None:
        for i in range(n):
            a_ang, a_rad = vertices[i]
            b_ang, b_rad = vertices[(i + 1) % n]
            b_ext = b_ang if b_ang > a_ang else b_ang + 360
            ang = bearing if bearing >= a_ang else bearing + 360
            if a_ang <= ang <= b_ext:
                span = b_ext - a_ang
                return a_rad if span <= 0 else a_rad + (b_rad - a_rad) * (ang - a_ang) / span
        return None

    confirmados = set()
    for d in resultado:
        if d["lat"] is None or d["lng"] is None:
            continue
        distancia, angulo = _distancia_y_angulo(info["lat"], info["lng"], d["lat"], d["lng"])
        radio = radio_interpolado(angulo)
        if radio is not None and distancia < radio:
            confirmados.add(d["id"])
    return confirmados


def _priorizar_sin_datos(conn, resultado: list[dict], agregador: str) -> list[dict]:
    """Reordena para que las direcciones sin datos reales de este agregador
    vayan primero (ver _con_datos_reales). Se aplica en CADA tienda por
    igual -- como el scheduler recorre las 6 tiendas en cada pasada (ver
    scheduler.py), esto ya prioriza "los puntos sin datos" en conjunto sin
    tener que tocar el scheduler ni conocer el resto de tiendas: si una
    pasada se corta a medias (ha pasado de verdad -- ver
    logs/catchup_20260807_111914_completo.log), lo que sí se llegó a
    comprobar son los puntos que más falta hacía cubrir, en vez de repetir
    de nuevo los primeros de la lista."""
    if not resultado:
        return resultado
    con_datos = _con_datos_reales(conn, resultado, agregador)
    sin_datos = [r for r in resultado if r["id"] not in con_datos]
    # Entre los "sin datos", los añadidos a mano van primero -- si no, se
    # mezclan sin orden con los cientos de puntos de la búsqueda de límite
    # también sin datos y pueden tardar pasadas enteras en tocarles el turno
    # (pedido explícito del usuario 09/08).
    sin_datos.sort(key=lambda r: r.get("origen") != "manual")
    con_datos_lista = [r for r in resultado if r["id"] in con_datos]
    return sin_datos + con_datos_lista


def get_o_crear_direcciones(
    tienda: str, radios_km=None, agregador: str | None = None, solo_sin_datos: bool = False
) -> list[dict]:
    """Genera (si hace falta) y devuelve el grid de puntos de test de una
    tienda. Determinista: mismos radios/ángulos siempre dan los mismos
    puntos, así se puede comparar disponibilidad de un punto en el tiempo.

    `agregador`, si se pasa, prioriza al principio de la lista los puntos que
    ese agregador concreto todavía no ha comprobado nunca de verdad (ver
    _priorizar_sin_datos) -- el orden base del grid no cambia para nada más.

    `solo_sin_datos=True` (requiere `agregador`) va más allá de solo
    reordenar: DEVUELVE únicamente esos puntos sin datos, para que el
    scheduler pueda hacer una pasada previa "solo huecos" cruzando las 6
    tiendas antes de empezar la pasada completa normal por tienda (ver
    scheduler.py) -- así el hueco se cubre esté donde esté, no solo dentro de
    la tienda que le toque primero por orden."""
    if tienda not in TIENDAS:
        return []
    radios_km = radios_km or GRID_RADIOS_KM
    info = TIENDAS[tienda]

    conn = get_connection()
    try:
        resultado = []
        for radio in radios_km:
            for i in range(GRID_ANGULOS_COUNT):
                angulo = (360 / GRID_ANGULOS_COUNT) * i
                fila = conn.execute(
                    "SELECT * FROM agregadores_direcciones WHERE tienda=? AND distancia_km=? AND angulo_grados=?",
                    (tienda, radio, int(angulo)),
                ).fetchone()
                if fila:
                    # Existe pero puede estar eliminado (activo=0) -- no se
                    # regenera (el hueco sigue "ocupado" por esa fila), solo no
                    # se devuelve para que el scraper no lo compruebe.
                    if fila["activo"]:
                        resultado.append(dict(fila))
                    continue

                lat_dest, lng_dest = _mover_punto(info["lat"], info["lng"], angulo, radio)
                lat_dest, lng_dest, direccion_text = _punto_geocodificado_valido(lat_dest, lng_dest)
                try:
                    cur = conn.execute(
                        """INSERT INTO agregadores_direcciones
                           (tienda, lat, lng, distancia_km, angulo_grados, direccion_text, origen)
                           VALUES (?, ?, ?, ?, ?, ?, 'grid')""",
                        (tienda, lat_dest, lng_dest, radio, int(angulo), direccion_text),
                    )
                    conn.commit()
                    resultado.append(
                        {
                            "id": cur.lastrowid,
                            "tienda": tienda,
                            "lat": lat_dest,
                            "lng": lng_dest,
                            "distancia_km": radio,
                            "angulo_grados": int(angulo),
                            "direccion_text": direccion_text,
                        }
                    )
                except sqlite3.IntegrityError:
                    # Los 3 agregadores piden el grid de la tienda en paralelo al
                    # empezar un chequeo -- si el punto no existía, los tres lo ven
                    # libre a la vez y solo uno gana la inserción. En vez de fallar
                    # toda la petición, se recupera la fila que sí se creó.
                    conn.rollback()
                    fila = conn.execute(
                        "SELECT * FROM agregadores_direcciones WHERE tienda=? AND distancia_km=? AND angulo_grados=?",
                        (tienda, radio, int(angulo)),
                    ).fetchone()
                    if fila and fila["activo"]:
                        resultado.append(dict(fila))

        # Puntos añadidos a mano desde el mapa (no encajan en el grid de radios
        # fijos que se recorrió arriba) -- se incluyen igual si están activos.
        ids_grid = {r["id"] for r in resultado}
        extra = conn.execute(
            "SELECT * FROM agregadores_direcciones WHERE tienda=? AND activo=1", (tienda,)
        ).fetchall()
        for fila in extra:
            if fila["id"] not in ids_grid:
                resultado.append(dict(fila))

        if agregador and solo_sin_datos:
            con_datos = _con_datos_reales(conn, resultado, agregador)
            con_datos |= _cobertura_confirmada_por_limite(conn, tienda, agregador, resultado)
            resultado = [r for r in resultado if r["id"] not in con_datos]
        elif agregador:
            resultado = _priorizar_sin_datos(conn, resultado, agregador)

        return resultado
    finally:
        conn.close()


def borrar_alertas_excepcion_vacia():
    """Mantenimiento puntual: borra las alertas "excepción no controlada — "
    con el mensaje vacío tras el guion (asyncio.TimeoutError y similares no
    llevan texto) -- quedaron así de un blip de red real del 06/08 antes de
    que scheduler.py empezara a loguear repr(exc) en vez de str(exc). No
    toca ninguna otra alerta."""
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM agregadores_alertas WHERE tipo='scraper_error' AND mensaje LIKE '%excepción no controlada — '"
    )
    conn.commit()
    borradas = cur.rowcount
    conn.close()
    return {"alertas_borradas": borradas}


def borrar_chequeos_error_texto():
    """Mantenimiento puntual: borra los chequeos marcados como fallo técnico
    (error_texto IS NOT NULL) -- no toca los chequeos con resultado real
    (disponible/no disponible), solo el ruido de bugs de scraper ya
    corregidos (p.ej. el selector sin :visible de Uber Eats del 06/08).
    También borra las alertas scraper_error asociadas, para no dejar
    alertas huérfanas de chequeos que ya no existen."""
    conn = get_connection()
    cur_chequeos = conn.execute("DELETE FROM agregadores_chequeos WHERE error_texto IS NOT NULL")
    cur_alertas = conn.execute("DELETE FROM agregadores_alertas WHERE tipo='scraper_error'")
    conn.commit()
    borrados = {"chequeos": cur_chequeos.rowcount, "alertas": cur_alertas.rowcount}
    conn.close()
    return borrados


def resetear_estadisticas():
    """Borra todo el historial de chequeos y alertas de los 3 agregadores
    (las 6 tiendas) -- deja los puntos del grid (agregadores_direcciones)
    intactos, solo limpia el histórico de resultados. Uso puntual: varios
    bugs de lectura (Glovo marcaba "cerrado" mirando toda la página, JustEat
    recibía coordenadas en bruto, timeouts demasiado cortos) contaminaron el
    historial de hoy antes de arreglarse -- sin esto, las estadísticas
    tardarían días en "diluir" los datos incorrectos ya guardados."""
    conn = get_connection()
    cur_chequeos = conn.execute("DELETE FROM agregadores_chequeos")
    cur_alertas = conn.execute("DELETE FROM agregadores_alertas")
    conn.commit()
    borrados = {"chequeos": cur_chequeos.rowcount, "alertas": cur_alertas.rowcount}
    conn.close()
    return borrados


def resetear_estadisticas_hoy():
    """Como resetear_estadisticas() pero solo borra el día de hoy (hora de
    Madrid), conservando días anteriores intactos para no perder histórico de
    los reportes semanales. El corte usa el inicio del día en Europe/Madrid
    convertido a UTC, porque los timestamps se guardan en UTC."""
    inicio_hoy_madrid = datetime.now(ZoneInfo("Europe/Madrid")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    inicio_hoy_utc = inicio_hoy_madrid.astimezone(timezone.utc).isoformat()

    conn = get_connection()
    cur_chequeos = conn.execute(
        "DELETE FROM agregadores_chequeos WHERE timestamp >= ?", (inicio_hoy_utc,)
    )
    cur_alertas = conn.execute(
        "DELETE FROM agregadores_alertas WHERE timestamp >= ?", (inicio_hoy_utc,)
    )
    conn.commit()
    borrados = {"chequeos": cur_chequeos.rowcount, "alertas": cur_alertas.rowcount}
    conn.close()
    return borrados


def guardar_chequeo(data: dict) -> int:
    """`data` es el JSON que manda el scraper: tienda, agregador,
    direccion_id, disponible, tiempo_entrega_min, mensaje_bloqueo,
    error_texto. `timestamp` es opcional (por defecto ahora). Devuelve el id
    insertado -- lo necesita el scraper para poder subir una captura ligada
    a este chequeo concreto si resulta ser una transición (ver
    hubo_transicion_a_no_disponible)."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO agregadores_chequeos
           (tienda, agregador, direccion_id, timestamp, disponible, tiempo_entrega_min,
            mensaje_bloqueo, error_texto, verificado_por)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["tienda"],
            data["agregador"],
            data.get("direccion_id"),
            data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            1 if data.get("disponible") else 0,
            data.get("tiempo_entrega_min"),
            data.get("mensaje_bloqueo"),
            data.get("error_texto"),
            data.get("verificado_por"),
        ),
    )
    conn.commit()
    chequeo_id = cur.lastrowid
    conn.close()
    return chequeo_id


def hubo_transicion_a_no_disponible(direccion_id: int | None, agregador: str) -> bool:
    """True si el chequeo anterior (real, sin error) de este punto+agregador
    estaba disponible -- es decir, este chequeo es el momento exacto en que
    un punto que sí repartía dejó de hacerlo. Se consulta ANTES de insertar
    el chequeo actual, así que "el anterior" es simplemente el último que ya
    existe en la tabla."""
    if direccion_id is None:
        return False
    conn = get_connection()
    fila = conn.execute(
        """SELECT disponible FROM agregadores_chequeos
           WHERE direccion_id=? AND agregador=? AND error_texto IS NULL
           ORDER BY timestamp DESC LIMIT 1""",
        (direccion_id, agregador),
    ).fetchone()
    conn.close()
    return bool(fila and fila["disponible"])


CAPTURAS_DIR = os.path.join(DATA_DIR, "uploads", "agregadores_capturas")


def guardar_captura_chequeo(chequeo_id: int, contenido: bytes) -> str:
    os.makedirs(CAPTURAS_DIR, exist_ok=True)
    ruta = os.path.join(CAPTURAS_DIR, f"{chequeo_id}.png")
    with open(ruta, "wb") as f:
        f.write(contenido)
    conn = get_connection()
    conn.execute("UPDATE agregadores_chequeos SET url_captura=? WHERE id=?", (ruta, chequeo_id))
    conn.commit()
    conn.close()
    return ruta


def get_ruta_captura(chequeo_id: int) -> str | None:
    conn = get_connection()
    fila = conn.execute(
        "SELECT url_captura FROM agregadores_chequeos WHERE id=?", (chequeo_id,)
    ).fetchone()
    conn.close()
    if fila and fila["url_captura"] and os.path.isfile(fila["url_captura"]):
        return fila["url_captura"]
    return None


CAPTURAS_DIAS_A_CONSERVAR = 3


def limpiar_capturas_viejas() -> int:
    """Borra los ARCHIVOS de captura de más de CAPTURAS_DIAS_A_CONSERVAR días
    (no la fila del chequeo ni el resto de sus datos -- get_ruta_captura ya
    devuelve None si el archivo no existe, así que "Ver captura" simplemente
    deja de ofrecerse para esos chequeos viejos). Pensado para correr
    periódicamente (ver start_scheduler_limpieza) y no dejar crecer sin
    límite el volumen de uploads."""
    if not os.path.isdir(CAPTURAS_DIR):
        return 0
    limite = time.time() - CAPTURAS_DIAS_A_CONSERVAR * 86400
    borrados = 0
    for nombre in os.listdir(CAPTURAS_DIR):
        ruta = os.path.join(CAPTURAS_DIR, nombre)
        try:
            if os.path.isfile(ruta) and os.path.getmtime(ruta) < limite:
                os.remove(ruta)
                borrados += 1
        except OSError:
            pass
    return borrados


def _tamano_dir(ruta: str) -> dict:
    if not os.path.isdir(ruta):
        return {"archivos": 0, "bytes": 0}
    total = 0
    n = 0
    for raiz, _, nombres in os.walk(ruta):
        for nombre in nombres:
            try:
                total += os.path.getsize(os.path.join(raiz, nombre))
                n += 1
            except OSError:
                pass
    return {"archivos": n, "bytes": total}


def info_almacenamiento() -> dict:
    """Diagnóstico del volumen entero (no solo agregadores) -- para saber de
    verdad qué se está comiendo el espacio antes de borrar nada a ciegas.
    Todas las carpetas de subida del backend viven bajo el mismo DATA_DIR."""
    from db import DB_PATH

    carpetas = {
        "db_principal": {"archivos": 1, "bytes": os.path.getsize(DB_PATH)} if os.path.isfile(DB_PATH) else {"archivos": 0, "bytes": 0},
        "backups": _tamano_dir(os.path.join(DATA_DIR, "backups")),
        "agregadores_capturas": _tamano_dir(CAPTURAS_DIR),
        "reclutamiento_candidatos": _tamano_dir(os.path.join(DATA_DIR, "uploads", "candidatos")),
        "informes_cv": _tamano_dir(os.path.join(DATA_DIR, "uploads", "cv")),
        "boletines": _tamano_dir(os.path.join(DATA_DIR, "uploads", "boletines")),
        "boletines_imagenes": _tamano_dir(os.path.join(DATA_DIR, "uploads", "boletines_imagenes")),
        "encuestas_fondos": _tamano_dir(os.path.join(DATA_DIR, "uploads", "encuestas_fondos")),
    }
    total_bytes = sum(c["bytes"] for c in carpetas.values())
    for c in carpetas.values():
        c["mb"] = round(c["bytes"] / 1024 / 1024, 1)
    return {"carpetas": carpetas, "total_mb": round(total_bytes / 1024 / 1024, 1)}


def info_capturas() -> dict:
    """Diagnóstico: cuántos archivos hay en CAPTURAS_DIR y cuánto pesan en
    total, para saber si de verdad son las capturas las que se están comiendo
    el volumen antes de decidir qué tan agresivo ser limpiando."""
    if not os.path.isdir(CAPTURAS_DIR):
        return {"archivos": 0, "bytes_total": 0}
    total = 0
    n = 0
    for nombre in os.listdir(CAPTURAS_DIR):
        ruta = os.path.join(CAPTURAS_DIR, nombre)
        try:
            if os.path.isfile(ruta):
                total += os.path.getsize(ruta)
                n += 1
        except OSError:
            pass
    return {"archivos": n, "bytes_total": total, "mb_total": round(total / 1024 / 1024, 1)}


def limpiar_capturas_direcciones_inactivas() -> dict:
    """Borra los ARCHIVOS de captura (no filas ni datos) de chequeos ligados a
    direcciones ya desactivadas (activo=0) -- los puntos inválidos que la
    búsqueda de límite de cobertura descarta sobre la marcha. Esos puntos ni
    siquiera se ven ya en el mapa, así que sus capturas no aportan nada, pero
    sí ocupan espacio real en el volumen (confirmado 08/08: la búsqueda de
    límite sube una captura por cada chequeo, y generó cientos en una sola
    tarde -- llevó el volumen cerca del límite de Railway)."""
    if not os.path.isdir(CAPTURAS_DIR):
        return {"borrados": 0, "bytes_liberados": 0}
    conn = get_connection()
    filas = conn.execute(
        """SELECT c.url_captura FROM agregadores_chequeos c
           JOIN agregadores_direcciones d ON d.id = c.direccion_id
           WHERE d.activo = 0 AND c.url_captura IS NOT NULL"""
    ).fetchall()
    conn.close()
    borrados = 0
    bytes_liberados = 0
    for fila in filas:
        ruta = fila["url_captura"]
        try:
            if ruta and os.path.isfile(ruta):
                bytes_liberados += os.path.getsize(ruta)
                os.remove(ruta)
                borrados += 1
        except OSError:
            pass
    return {"borrados": borrados, "bytes_liberados": bytes_liberados}


_limpieza_capturas_iniciada = False


def start_scheduler_limpieza_capturas():
    """Hilo en segundo plano (mismo patrón que backups.start_scheduler) que
    borra capturas de más de 3 días una vez al día."""
    global _limpieza_capturas_iniciada
    if _limpieza_capturas_iniciada:
        return
    _limpieza_capturas_iniciada = True

    def _loop():
        while True:
            try:
                borrados = limpiar_capturas_viejas()
                if borrados:
                    print(f"[agregadores] Limpieza de capturas: {borrados} archivos de más de {CAPTURAS_DIAS_A_CONSERVAR} días borrados.", flush=True)
            except Exception as e:
                print(f"[agregadores] Fallo en limpieza de capturas: {e}", flush=True)
            time.sleep(24 * 3600)

    threading.Thread(target=_loop, daemon=True).start()


def eliminar_chequeo(chequeo_id: int) -> bool:
    """Borra un chequeo puntual y su captura si tiene -- para corregir un
    dato confirmado como erróneo (p.ej. el bug de coordenadas en bruto que
    comprobó una dirección distinta a la real, ver main.py del scraper), no
    para limpiar en bloque. Uso puntual vía /admin/chequeo/{id}."""
    conn = get_connection()
    fila = conn.execute(
        "SELECT url_captura FROM agregadores_chequeos WHERE id=?", (chequeo_id,)
    ).fetchone()
    if not fila:
        conn.close()
        return False
    if fila["url_captura"] and os.path.isfile(fila["url_captura"]):
        try:
            os.remove(fila["url_captura"])
        except OSError:
            pass
    conn.execute("DELETE FROM agregadores_chequeos WHERE id=?", (chequeo_id,))
    conn.commit()
    conn.close()
    return True


def get_transiciones(tienda: str | None, horas: int = 24):
    """Puntos que aparecían disponibles y, en el chequeo siguiente (real, sin
    error), dejaron de estarlo. Amplía el resultado con timestamp del cambio,
    duración en disponible, y detalles de por qué se bloqueó."""
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_connection()
    condicion_tienda = "AND c.tienda=?" if tienda else ""
    params = (tienda, desde) if tienda else (desde,)

    # Consulta principal: detecta transiciones DD→DND
    filas = conn.execute(
        f"""
        WITH chequeos_ordenados AS (
            SELECT c.id, c.tienda, c.agregador, c.direccion_id, c.timestamp,
                   c.disponible, c.tiempo_entrega_min, c.mensaje_bloqueo,
                   (c.url_captura IS NOT NULL) AS tiene_captura,
                   d.direccion_text, d.lat, d.lng,
                   LAG(c.disponible) OVER (
                       PARTITION BY c.direccion_id, c.agregador ORDER BY c.timestamp
                   ) AS disponible_anterior,
                   LAG(c.timestamp) OVER (
                       PARTITION BY c.direccion_id, c.agregador ORDER BY c.timestamp
                   ) AS timestamp_anterior
            FROM agregadores_chequeos c
            LEFT JOIN agregadores_direcciones d ON d.id = c.direccion_id
            WHERE c.error_texto IS NULL {condicion_tienda}
        )
        SELECT id, tienda, agregador, direccion_id, timestamp, timestamp_anterior,
               disponible, tiempo_entrega_min, mensaje_bloqueo,
               tiene_captura, direccion_text, lat, lng
        FROM chequeos_ordenados
        WHERE disponible_anterior = 1 AND disponible = 0 AND timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT 200
        """,
        params,
    ).fetchall()

    # Post-procesamiento: calcula duración en disponible y nombre de tienda
    resultado = []
    for fila in filas:
        fila_dict = dict(fila)
        # Calcula cuánto tiempo estuvo disponible (desde timestamp_anterior hasta timestamp)
        if fila_dict["timestamp_anterior"]:
            try:
                ts_ant = datetime.fromisoformat(fila_dict["timestamp_anterior"])
                ts_act = datetime.fromisoformat(fila_dict["timestamp"])
                duracion = ts_act - ts_ant
                # Expresa como "X min" o "X h Y min"
                total_seg = int(duracion.total_seconds())
                horas, resto = divmod(total_seg, 3600)
                minutos = resto // 60
                if horas > 0:
                    fila_dict["duracion_disponible"] = f"{horas}h {minutos}m"
                else:
                    fila_dict["duracion_disponible"] = f"{minutos}m"
            except Exception:
                fila_dict["duracion_disponible"] = None
        else:
            fila_dict["duracion_disponible"] = None

        # Nombre de la tienda desde TIENDAS
        fila_dict["nombre_tienda"] = TIENDAS.get(fila_dict["tienda"], {}).get("nombre", fila_dict["tienda"])

        # timestamp_anterior se deja tal cual (hora de la última vez que se
        # vio disponible) -- el frontend lo muestra junto a "timestamp" (hora
        # en que se detectó que ya no lo estaba), no solo la duración.
        resultado.append(fila_dict)

    conn.close()
    return resultado


def get_cobertura_mapa(tienda: str | None = None, agregador: str | None = None):
    """Obtiene último estado conocido de cada dirección para dibujar mapas
    de cobertura. Devuelve puntos verdes (disponible) y amarillos (no disponible).
    Útil para polígono convex de cobertura real."""
    conn = get_connection()
    condicion_tienda = "AND c.tienda=?" if tienda else ""
    condicion_agregador = "AND c.agregador=?" if agregador else ""
    params = []
    if tienda:
        params.append(tienda)
    if agregador:
        params.append(agregador)

    # Últimos chequeos (sin error) de cada punto
    filas = conn.execute(
        f"""
        WITH ultimo_por_punto AS (
            SELECT c.direccion_id, c.tienda, c.agregador, c.disponible,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.direccion_id, c.tienda, c.agregador
                       ORDER BY c.timestamp DESC
                   ) AS rn
            FROM agregadores_chequeos c
            WHERE c.error_texto IS NULL {condicion_tienda} {condicion_agregador}
        )
        SELECT d.id, d.tienda, d.lat, d.lng, d.direccion_text,
               u.agregador, u.disponible
        FROM ultimo_por_punto u
        LEFT JOIN agregadores_direcciones d ON d.id = u.direccion_id
        WHERE u.rn = 1 AND d.activo = 1
        ORDER BY u.tienda, u.agregador, d.id
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def registrar_alerta(tipo: str, mensaje: str, tienda: str = None, agregador: str = None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO agregadores_alertas (timestamp, tienda, agregador, tipo, mensaje) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), tienda, agregador, tipo, mensaje),
    )
    conn.commit()
    conn.close()


def iniciar_sesion(modo: str, total_planeado: int | None = None) -> int:
    conn = get_connection()
    # Si el proceso del daemon se mató a media pasada (crash, reinicio manual,
    # el kill de la tarea programada de las 22:00 pillando algo a medias...)
    # esa sesión se queda "en_curso" para siempre -- nadie llama a
    # cerrar_sesion. get_estado() la sigue viendo como "la última sesión" y
    # cuenta TODOS los chequeos guardados desde su fecha_inicio como
    # progreso, mezclando pasadas de reinicios distintos en un solo número
    # disparatado (confirmado en vivo 10/08: "1944" sin total, acumulado de
    # varias pasadas ya muertas). Con max_instances=1 en el scheduler nunca
    # debería haber dos sesiones "en_curso" del mismo modo a la vez, así que
    # cualquiera que quede así al empezar una nueva es, por definición, una
    # huérfana de un proceso anterior -- se cierra aquí antes de abrir la
    # siguiente.
    conn.execute(
        """UPDATE agregadores_sesiones SET fecha_fin=?, estado='interrumpido'
           WHERE modo=? AND fecha_fin IS NULL""",
        (datetime.now(timezone.utc).isoformat(), modo),
    )
    cur = conn.execute(
        """INSERT INTO agregadores_sesiones (modo, fecha_inicio, estado, total_planeado)
           VALUES (?, ?, 'en_curso', ?)""",
        (modo, datetime.now(timezone.utc).isoformat(), total_planeado),
    )
    conn.commit()
    sesion_id = cur.lastrowid
    conn.close()
    return sesion_id


def cerrar_sesiones_huerfanas() -> int:
    """Mantenimiento puntual: cierra cualquier sesión que haya quedado
    'en_curso' sin fecha_fin (ver el comentario en iniciar_sesion -- ahora
    esto se evita solo hacia adelante, pero no arregla lo que ya estaba
    huérfano en la BD antes de ese fix)."""
    conn = get_connection()
    cur = conn.execute(
        """UPDATE agregadores_sesiones SET fecha_fin=?, estado='interrumpido'
           WHERE fecha_fin IS NULL""",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    cerradas = cur.rowcount
    conn.close()
    return cerradas


def cerrar_sesion(sesion_id: int, estado: str, exitosos: int, fallidos: int):
    conn = get_connection()
    conn.execute(
        """UPDATE agregadores_sesiones SET fecha_fin=?, estado=?, chequeos_exitosos=?,
           chequeos_fallidos=? WHERE id=?""",
        (datetime.now(timezone.utc).isoformat(), estado, exitosos, fallidos, sesion_id),
    )
    conn.commit()
    conn.close()


def get_tiendas():
    return [{"tienda": k, **v} for k, v in TIENDAS.items()]


def get_ultimos(tienda: str, horas: int = 24):
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_connection()
    filas = conn.execute(
        """SELECT c.*, d.direccion_text FROM agregadores_chequeos c
           LEFT JOIN agregadores_direcciones d ON d.id = c.direccion_id
           WHERE c.tienda=? AND c.timestamp>=? ORDER BY c.timestamp DESC LIMIT 200""",
        (tienda, desde),
    ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def get_mapa_datos(tienda: str):
    conn = get_connection()
    direcciones = conn.execute(
        "SELECT * FROM agregadores_direcciones WHERE tienda=? AND activo=1", (tienda,)
    ).fetchall()

    resultado = []
    for d in direcciones:
        ultimos_por_agregador = {}
        chequeos = conn.execute(
            "SELECT * FROM agregadores_chequeos WHERE direccion_id=? ORDER BY timestamp DESC LIMIT 50",
            (d["id"],),
        ).fetchall()
        for c in chequeos:
            if c["agregador"] not in ultimos_por_agregador:
                ultimos_por_agregador[c["agregador"]] = c

        detalle = {}
        disponible_count = no_disponible_count = error_count = 0
        for nombre, c in ultimos_por_agregador.items():
            if c["error_texto"]:
                estado = "error"
                error_count += 1
            elif c["disponible"]:
                estado = "disponible"
                disponible_count += 1
            else:
                estado = "no_disponible"
                no_disponible_count += 1
            detalle[nombre] = {
                "estado": estado,
                "disponible": bool(c["disponible"]),
                "tiempo_entrega_min": c["tiempo_entrega_min"],
                "timestamp": c["timestamp"],
                "verificado_por": c["verificado_por"],
            }

        resultado.append(
            {
                "id": d["id"],
                "lat": d["lat"],
                "lng": d["lng"],
                "distancia_km": d["distancia_km"],
                "angulo_grados": d["angulo_grados"],
                "direccion_text": d["direccion_text"],
                "origen": d["origen"],
                "disponible_count": disponible_count,
                "no_disponible_count": no_disponible_count,
                "error_count": error_count,
                "total_agregadores": len(AGREGADORES),
                "detalle": detalle,
            }
        )
    conn.close()

    tienda_info = TIENDAS.get(tienda)
    return {
        "tienda": {"tienda": tienda, **tienda_info} if tienda_info else None,
        "direcciones": resultado,
    }


def get_mapa_datos_todas():
    """Igual que get_mapa_datos pero de las 6 tiendas a la vez, para la
    vista "Todas" del mapa -- cada dirección lleva su slug de tienda para
    poder identificar de cuál es en el popup."""
    tiendas = []
    direcciones = []
    for slug in TIENDAS:
        datos = get_mapa_datos(slug)
        if datos["tienda"]:
            tiendas.append(datos["tienda"])
        for d in datos["direcciones"]:
            d["tienda"] = slug
            direcciones.append(d)
    return {"tiendas": tiendas, "direcciones": direcciones}


def get_alertas(tienda: str = None, horas: int = 24):
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_connection()
    if tienda:
        filas = conn.execute(
            "SELECT * FROM agregadores_alertas WHERE timestamp>=? AND tienda=? ORDER BY timestamp DESC LIMIT 100",
            (desde, tienda),
        ).fetchall()
    else:
        filas = conn.execute(
            "SELECT * FROM agregadores_alertas WHERE timestamp>=? ORDER BY timestamp DESC LIMIT 100",
            (desde,),
        ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def get_reporte(tienda: str | None, desde: datetime, hasta: datetime, resets: dict[str, str] | None = None):
    """tienda=None agrega las 6 tiendas juntas (vista "Todas").

    Los tres porcentajes (disponible/no_disponible/error) se calculan sobre
    el MISMO total de intentos -- suman 100%, para que no haya ambigüedad
    sobre a qué total se refiere cada uno (antes "disponibilidad_pct" se
    calculaba solo sobre los intentos validos, distinto del total de la
    tarjeta de al lado, lo que confundía más que aclaraba).

    `resets` (opcional): {agregador: iso_timestamp} -- para ese agregador,
    ignora los chequeos anteriores al timestamp al calcular sus %. Es un
    filtro de lectura nada más (no borra ni modifica filas) para poder ver
    "cómo va desde que reinicié el contador" sin que los fallos de antes de
    un fix sigan contaminando el % del día."""
    conn = get_connection()
    if tienda:
        filas = conn.execute(
            "SELECT * FROM agregadores_chequeos WHERE tienda=? AND timestamp>=? AND timestamp<?",
            (tienda, desde.isoformat(), hasta.isoformat()),
        ).fetchall()
    else:
        filas = conn.execute(
            "SELECT * FROM agregadores_chequeos WHERE timestamp>=? AND timestamp<?",
            (desde.isoformat(), hasta.isoformat()),
        ).fetchall()
    conn.close()

    por_agregador: dict[str, list] = {}
    for f in filas:
        por_agregador.setdefault(f["agregador"], []).append(f)

    reporte = {}
    for nombre, lista in por_agregador.items():
        reset_ts = resets.get(nombre) if resets else None
        if reset_ts:
            lista = [f for f in lista if f["timestamp"] >= reset_ts]

        total = len(lista)
        errores = [f for f in lista if f["error_texto"]]
        validos = [f for f in lista if not f["error_texto"]]
        disponibles = sum(1 for f in validos if f["disponible"])
        no_disponibles = len(validos) - disponibles
        tiempos = [f["tiempo_entrega_min"] for f in validos if f["tiempo_entrega_min"]]
        tiempo_medio = sum(tiempos) / len(tiempos) if tiempos else None

        reporte[nombre] = {
            "total_chequeos": total,
            "disponibles": disponibles,
            "no_disponibles": no_disponibles,
            "errores": len(errores),
            "disponible_pct": round(disponibles / total * 100, 1) if total else 0.0,
            "no_disponible_pct": round(no_disponibles / total * 100, 1) if total else 0.0,
            "error_pct": round(len(errores) / total * 100, 1) if total else 0.0,
            "tiempo_medio_entrega": round(tiempo_medio, 1) if tiempo_medio else None,
            "reiniciado_desde": reset_ts,
        }

    return {
        "fecha_desde": desde.isoformat(),
        "fecha_hasta": hasta.isoformat(),
        "tienda": tienda,
        "agregadores": reporte,
    }


def es_horario_apertura(ahora: datetime = None) -> bool:
    # datetime.now() sin zona da la hora del sistema del servidor -- en
    # Railway corre en UTC, así que a las 10:05 de Madrid (CEST, UTC+2)
    # marcaba "fuera de horario" porque para el servidor eran las 08:05.
    ahora = ahora or datetime.now(MADRID_TZ)
    return any(r["inicio"] <= ahora.hour < r["fin"] for r in HORARIOS_APERTURA)


def get_estado():
    conn = get_connection()

    def _estado_modo(modo, frecuencia_min):
        fila = conn.execute(
            "SELECT * FROM agregadores_sesiones WHERE modo=? ORDER BY fecha_inicio DESC LIMIT 1",
            (modo,),
        ).fetchone()
        if not fila:
            return {
                "ultima_sesion_inicio": None,
                "ultima_sesion_fin": None,
                "ultima_sesion_estado": None,
                "chequeos_exitosos": None,
                "chequeos_fallidos": None,
                "frecuencia_esperada_min": frecuencia_min,
                "retrasado": es_horario_apertura(),
                "minutos_desde_ultima": None,
            }
        referencia = fila["fecha_fin"] or fila["fecha_inicio"]
        minutos_desde = (
            datetime.now(timezone.utc) - datetime.fromisoformat(referencia)
        ).total_seconds() / 60
        margen = frecuencia_min * 3
        retrasado = es_horario_apertura() and minutos_desde > margen

        # Progreso en vivo: solo tiene sentido con la sesión todavía abierta
        # (fecha_fin IS NULL). "hechos" se cuenta directamente de los
        # chequeos ya guardados desde que empezó -- cada chequeo individual
        # los va insertando en tiempo real (ver main.chequear_tienda), así
        # que no hace falta que el scheduler reporte progreso aparte, solo
        # el total planeado al principio (ver iniciar_sesion).
        en_curso = fila["fecha_fin"] is None
        hechos = None
        if en_curso:
            hechos = conn.execute(
                "SELECT COUNT(*) FROM agregadores_chequeos WHERE timestamp>=?",
                (fila["fecha_inicio"],),
            ).fetchone()[0]

        return {
            "ultima_sesion_inicio": fila["fecha_inicio"],
            "ultima_sesion_fin": fila["fecha_fin"],
            "ultima_sesion_estado": fila["estado"],
            "chequeos_exitosos": fila["chequeos_exitosos"],
            "chequeos_fallidos": fila["chequeos_fallidos"],
            "frecuencia_esperada_min": frecuencia_min,
            "retrasado": retrasado,
            "minutos_desde_ultima": round(minutos_desde, 1),
            "en_curso": en_curso,
            "progreso_hechos": hechos,
            "progreso_total": fila["total_planeado"] if en_curso else None,
        }

    resultado = {
        "hora_servidor": datetime.now(timezone.utc).isoformat(),
        "es_horario_apertura": es_horario_apertura(),
        "cercano": _estado_modo("cercano", FRECUENCIA_CHEQUEO_CERCANO_MIN),
        "completo": _estado_modo("completo", FRECUENCIA_CHEQUEO_COMPLETO_MIN),
    }
    conn.close()
    return resultado


ensure_tables()
