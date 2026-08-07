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
    pasó: cada llamada tardaba 5-6s y fallaba tras machacarlo sin pausas)."""
    global _nominatim_ultima_llamada
    with _NOMINATIM_LOCK:
        espera = _NOMINATIM_INTERVALO_MIN_SEG - (time.monotonic() - _nominatim_ultima_llamada)
        if espera > 0:
            time.sleep(espera)
        _nominatim_ultima_llamada = time.monotonic()

        try:
            from geopy.geocoders import Nominatim

            geocoder = Nominatim(user_agent="krispy-monitor-kg")
            location = geocoder.reverse(f"{lat}, {lng}", timeout=6)
            if location:
                return location.address
        except Exception:
            pass
        return f"({lat:.4f}, {lng:.4f})"


_PATRON_VIA_NO_DIRECCION = re.compile(
    r"^(Autov[ií]a|Autopista|Carretera|V[ií]a de servicio|[AMNR]-\d+\b)", re.IGNORECASE
)


def _direccion_valida(texto: str) -> bool:
    """Tiene que ser una calle real CON número de portal -- una autovía/M-45,
    un polígono sin número o cualquier vía sin número no es una dirección a
    la que nadie pueda pedir de verdad. Probar ahí solo genera ruido de "no
    disponible" que no dice nada sobre cobertura real."""
    t = texto.strip()
    if _PATRON_VIA_NO_DIRECCION.match(t):
        return False
    return bool(re.match(r"^\d", t))


def _punto_geocodificado_valido(lat, lng, intentos_extra=7, paso_km=0.07, radio_max_km=0.5):
    """Geocodifica un punto y, si no es una calle con número real, prueba
    puntos cercanos en espiral alrededor del MISMO punto original (nunca más
    lejos de radio_max_km, para que siga representando ese sitio del círculo
    y no se desplace de zona) hasta encontrar una dirección numerada válida.
    Si agota los intentos, se queda con el último probado."""
    lat0, lng0 = lat, lng
    texto = _geocodificar(lat, lng)
    if _direccion_valida(texto):
        return lat, lng, texto

    mejor = (lat, lng, texto)
    for intento in range(1, intentos_extra + 1):
        radio = min(paso_km * intento, radio_max_km)
        bearing = (intento * 137) % 360  # ángulo dorado: cubre el círculo sin repetir dirección
        lat_i, lng_i = _mover_punto(lat0, lng0, bearing, radio)
        texto_i = _geocodificar(lat_i, lng_i)
        mejor = (lat_i, lng_i, texto_i)
        if _direccion_valida(texto_i):
            return mejor
    return mejor


def reparar_direcciones_invalidas() -> dict:
    """Recorre los puntos ya guardados y reubica los que cayeron en una
    autovía/M-45/etc (creados antes de que existiera este filtro). Actualiza
    la misma fila (mismo id), así que los chequeos históricos ligados a ese
    punto por direccion_id siguen apuntando al punto correcto, ya reubicado."""
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
        # Commit por fila, no al final: cada punto tarda varios segundos en
        # geocodificar (varios intentos a Nominatim), así que un commit único
        # al final mantendría la escritura abierta -- y el archivo bloqueado
        # para cualquier otra petición -- durante toda la duración del repaso.
        conn.commit()
        reparadas.append({"id": fila["id"], "antes": fila["direccion_text"], "despues": texto})
    conn.close()
    return {"reparadas": len(reparadas), "detalle": reparadas}


def mover_direccion_manual(direccion_id: int, lat: float, lng: float, direccion_text: str = None) -> dict | None:
    """Reubicación manual desde el mapa del dashboard (arrastrar un punto).
    Sin texto de dirección, se geocodifica automáticamente la posición nueva
    -- si no, el texto quedaría desactualizado (el de antes de arrastrar, ya
    no corresponde a dónde está el punto ahora)."""
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
        direccion_text = _geocodificar(lat, lng)
    conn.execute(
        "UPDATE agregadores_direcciones SET lat=?, lng=?, direccion_text=? WHERE id=?",
        (lat, lng, direccion_text, direccion_id),
    )
    conn.commit()
    fila = conn.execute("SELECT * FROM agregadores_direcciones WHERE id=?", (direccion_id,)).fetchone()
    conn.close()
    return dict(fila)


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
        # queda donde se hizo clic.
        direccion_text = _geocodificar(lat, lng)
    distancia_km, angulo_grados = _distancia_y_angulo(info["lat"], info["lng"], lat, lng)

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO agregadores_direcciones
           (tienda, lat, lng, distancia_km, angulo_grados, direccion_text, activo)
           VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (tienda, lat, lng, distancia_km, int(round(angulo_grados)), direccion_text),
    )
    conn.commit()
    fila = conn.execute("SELECT * FROM agregadores_direcciones WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(fila)


def get_o_crear_direcciones(tienda: str, radios_km=None) -> list[dict]:
    """Genera (si hace falta) y devuelve el grid de puntos de test de una
    tienda. Determinista: mismos radios/ángulos siempre dan los mismos
    puntos, así se puede comparar disponibilidad de un punto en el tiempo."""
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
                           (tienda, lat, lng, distancia_km, angulo_grados, direccion_text)
                           VALUES (?, ?, ?, ?, ?, ?)""",
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
            mensaje_bloqueo, error_texto)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["tienda"],
            data["agregador"],
            data.get("direccion_id"),
            data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            1 if data.get("disponible") else 0,
            data.get("tiempo_entrega_min"),
            data.get("mensaje_bloqueo"),
            data.get("error_texto"),
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

        # Limpia timestamp_anterior (no necesario en frontend)
        del fila_dict["timestamp_anterior"]
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


def iniciar_sesion(modo: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO agregadores_sesiones (modo, fecha_inicio, estado) VALUES (?, ?, 'en_curso')",
        (modo, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    sesion_id = cur.lastrowid
    conn.close()
    return sesion_id


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
            }

        resultado.append(
            {
                "id": d["id"],
                "lat": d["lat"],
                "lng": d["lng"],
                "distancia_km": d["distancia_km"],
                "angulo_grados": d["angulo_grados"],
                "direccion_text": d["direccion_text"],
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


def get_reporte(tienda: str | None, desde: datetime, hasta: datetime):
    """tienda=None agrega las 6 tiendas juntas (vista "Todas").

    Los tres porcentajes (disponible/no_disponible/error) se calculan sobre
    el MISMO total de intentos -- suman 100%, para que no haya ambigüedad
    sobre a qué total se refiere cada uno (antes "disponibilidad_pct" se
    calculaba solo sobre los intentos validos, distinto del total de la
    tarjeta de al lado, lo que confundía más que aclaraba)."""
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
        return {
            "ultima_sesion_inicio": fila["fecha_inicio"],
            "ultima_sesion_fin": fila["fecha_fin"],
            "ultima_sesion_estado": fila["estado"],
            "chequeos_exitosos": fila["chequeos_exitosos"],
            "chequeos_fallidos": fila["chequeos_fallidos"],
            "frecuencia_esperada_min": frecuencia_min,
            "retrasado": retrasado,
            "minutos_desde_ultima": round(minutos_desde, 1),
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
