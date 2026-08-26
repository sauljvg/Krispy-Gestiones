"""Monitoreo de disponibilidad en JustEat/Glovo/Uber Eats.

El scraper corre en un portátil aparte (necesita un navegador real, headed
para Uber Eats — ver scraper_agregadores/ en la raíz del repo) y llama a la
API en vivo (POST /api/agregadores/chequeo) con cada resultado; aquí solo se
guarda y se sirve. Nada de esto toca Selenium ni el scraper de Reseñas."""
import json
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
    cols = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_direcciones)")}
    if "activo" not in cols:
        conn.execute("ALTER TABLE agregadores_direcciones ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
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
    cols_chequeos = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_chequeos)")}
    if "url_captura" not in cols_chequeos:
        conn.execute("ALTER TABLE agregadores_chequeos ADD COLUMN url_captura TEXT")
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
    cols_limites = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_limites)")}
    if "lat" not in cols_limites:
        conn.execute("ALTER TABLE agregadores_limites ADD COLUMN lat REAL")
    if "lng" not in cols_limites:
        conn.execute("ALTER TABLE agregadores_limites ADD COLUMN lng REAL")
    if "direccion_text" not in cols_limites:
        conn.execute("ALTER TABLE agregadores_limites ADD COLUMN direccion_text TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_direcciones_estado (
            direccion_id INTEGER NOT NULL,
            agregador TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (direccion_id, agregador)
        )
    """)

    # El relleno automático entre vértices se quitó (ver agregadores.js,
    # 10/08) porque no había forma fiable de distinguir un hueco real de uno
    # con contaminación de otra sucursal -- pero el usuario SÍ puede verlo a
    # ojo en el mapa ("estos dos dots verdes tienen un hueco entre medias, y
    # sé que en realidad está todo cubierto"). Esta tabla guarda esa decisión
    # manual: un puente entre dos puntos concretos (por lat/lng, no por
    # direccion_id -- los vértices del borde ya calculados no siempre tienen
    # una fila de dirección real detrás, ver resultado_punto/agregadores_limites,
    # y el usuario también quiere poder unir esos, no solo los dots del grid),
    # por tienda y agregador, para que el polígono conecte esos dos puntos en
    # línea recta sin dejar que un vértice intermedio más corto cree un
    # hueco/pico.
    cols_uniones = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_uniones)")}
    if cols_uniones and "lat_a" not in cols_uniones:
        # Esquema viejo (solo direccion_id, NOT NULL) de la primera versión
        # de esta tabla -- se creó en esta misma sesión con un único registro
        # de prueba, seguro recrearla con el esquema nuevo.
        conn.execute("DROP TABLE agregadores_uniones")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_uniones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tienda TEXT NOT NULL,
            agregador TEXT NOT NULL,
            lat_a REAL NOT NULL,
            lng_a REAL NOT NULL,
            lat_b REAL NOT NULL,
            lng_b REAL NOT NULL,
            direccion_id_a INTEGER,
            direccion_id_b INTEGER,
            creado_en TEXT NOT NULL
        )
    """)

    # "Pincel": zona pintada a mano por el usuario (varios puntos formando un
    # área, no solo dos) que se fusiona (turf.union en el frontend) con el
    # polígono calculado -- para huecos DENTRO del polígono que "unir puntos"
    # (un puente recto entre dos puntos del borde) no puede resolver, porque
    # el hueco no está en el borde sino en medio de la figura (pedido
    # explícito del usuario 10/08: "hay unas zonas que debemos poder rellenar
    # dentro del mismo polígono").
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_rellenos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tienda TEXT NOT NULL,
            agregador TEXT NOT NULL,
            puntos TEXT NOT NULL,
            creado_en TEXT NOT NULL
        )
    """)

    # total_planeado: cuántos chequeos individuales (tienda x agregador x
    # dirección) va a hacer la pasada en curso -- el scheduler lo calcula al
    # empezar (ver scheduler.py) y lo manda aquí para que el dashboard pueda
    # mostrar un progreso real ("22/66") en vez de solo "activo/inactivo".
    cols_sesiones = {row[1] for row in conn.execute("PRAGMA table_info(agregadores_sesiones)")}
    if "total_planeado" not in cols_sesiones:
        conn.execute("ALTER TABLE agregadores_sesiones ADD COLUMN total_planeado INTEGER")
    if "tienda_actual" not in cols_sesiones:
        # Qué tienda está recorriendo el daemon AHORA MISMO dentro de la
        # pasada en curso -- el scheduler la va actualizando según avanza el
        # bucle por TIENDAS_SCHEDULER (ver scheduler.py), para un contador
        # en vivo en el dashboard (solo visible para el admin, pedido
        # explícito del usuario 10/08).
        conn.execute("ALTER TABLE agregadores_sesiones ADD COLUMN tienda_actual TEXT")

    # Vuelta completa REAL (ver scraper_agregadores/revalidar_completo.py): revalida
    # cada punto activo de un agregador con varios workers en paralelo (20+), a
    # diferencia de agregadores_sesiones (pensada para UN daemon lineal). No hace
    # falta que cada worker reporte su propio avance -- "hechos" se calcula del lado
    # del backend contando agregadores_chequeos posteriores a iniciada_en (ver
    # get_ronda_actual), así que ningún worker necesita saber lo que hacen los demás.
    # iniciar_ronda/finalizar_ronda son idempotentes a propósito: los 20 workers de
    # un mismo agregador llaman a las dos al arrancar/terminar sin coordinarse entre
    # sí (el primero en llegar gana, el resto son no-ops), pedido explícito del
    # usuario 26/08 para ver progreso en vivo en el dashboard integrado.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agregadores_rondas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agregador TEXT NOT NULL,
            iniciada_en TEXT NOT NULL,
            total_objetivo INTEGER NOT NULL,
            finalizada_en TEXT
        )
    """)
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
_NOMINATIM_INTERVALO_MIN_SEG = 1.1


def _geocodificar(lat, lng):
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
    t = texto.strip()
    primer_segmento = t.split(",", 1)[0].strip()
    if _PATRON_VIA_NO_DIRECCION.match(primer_segmento):
        return False
    if _PATRON_NUMERO_LIMPIO.match(primer_segmento):
        resto = t.split(",", 2)
        siguiente = resto[1].strip() if len(resto) > 1 else ""
        return not re.match(r"^\d", siguiente)
    ultima_palabra = primer_segmento.rsplit(" ", 1)[-1] if primer_segmento else ""
    return bool(_PATRON_NUMERO_LIMPIO.match(ultima_palabra)) and " " in primer_segmento


def _punto_geocodificado_valido(lat, lng, intentos_extra=7, paso_km=0.07, radio_max_km=0.5):
    lat0, lng0 = lat, lng
    texto_plano, componentes = _geocodificar(lat, lng)
    texto = _construir_direccion(componentes)
    if texto:
        return lat, lng, texto

    mejor = (lat, lng, texto_plano)
    for intento in range(1, intentos_extra + 1):
        radio = min(paso_km * intento, radio_max_km)
        bearing = (intento * 137) % 360
        lat_i, lng_i = _mover_punto(lat0, lng0, bearing, radio)
        texto_plano_i, componentes_i = _geocodificar(lat_i, lng_i)
        texto_i = _construir_direccion(componentes_i)
        mejor = (lat_i, lng_i, texto_i or texto_plano_i)
        if texto_i:
            return lat_i, lng_i, texto_i
    return mejor


def reparar_direcciones_invalidas() -> dict:
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
        conn.commit()
        reparadas.append({"id": fila["id"], "antes": fila["direccion_text"], "despues": texto})
    conn.close()
    return {"reparadas": len(reparadas), "detalle": reparadas}


def reformatear_direcciones() -> dict:
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
    conn = get_connection()
    fila = conn.execute("SELECT id FROM agregadores_direcciones WHERE id=?", (direccion_id,)).fetchone()
    if not fila:
        conn.close()
        return None
    if not direccion_text:
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


def eliminar_direccion(direccion_id: int, agregador: str | None = None) -> bool:
    conn = get_connection()
    fila = conn.execute("SELECT id FROM agregadores_direcciones WHERE id=?", (direccion_id,)).fetchone()
    if not fila:
        conn.close()
        return False
    if agregador:
        conn.execute(
            """INSERT INTO agregadores_direcciones_estado (direccion_id, agregador, activo)
               VALUES (?, ?, 0)
               ON CONFLICT(direccion_id, agregador) DO UPDATE SET activo=0""",
            (direccion_id, agregador),
        )
    else:
        conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE id=?", (direccion_id,))
    conn.commit()
    conn.close()
    return True


def podar_grid_reducido() -> dict:
    angulos_validos = {round((360 / GRID_ANGULOS_COUNT) * i) for i in range(GRID_ANGULOS_COUNT)}
    radios_validos = set(GRID_RADIOS_KM)

    conn = get_connection()
    filas = conn.execute(
        "SELECT id, distancia_km, angulo_grados FROM agregadores_direcciones WHERE activo=1"
    ).fetchall()
    podados = 0
    for fila in filas:
        es_del_grid_original = fila["angulo_grados"] % 30 == 0
        if not es_del_grid_original:
            continue
        if fila["distancia_km"] not in radios_validos or fila["angulo_grados"] not in angulos_validos:
            conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE id=?", (fila["id"],))
            podados += 1
    conn.commit()
    conn.close()
    return {"podados": podados}


def crear_punto_calculado(tienda: str, distancia_km: float, angulo_grados: float) -> dict | None:
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
    resultado["direccion_valida"] = _direccion_valida(direccion_text)
    resultado["tienda_mas_cercana"] = _tienda_mas_cercana(fila["lat"], fila["lng"])
    return resultado


def _tienda_mas_cercana(lat: float, lng: float) -> str:
    mejor_tienda, mejor_distancia = None, None
    for nombre, info in TIENDAS.items():
        distancia, _ = _distancia_y_angulo(info["lat"], info["lng"], lat, lng)
        if mejor_distancia is None or distancia < mejor_distancia:
            mejor_tienda, mejor_distancia = nombre, distancia
    return mejor_tienda


# Umbral único para "¿es esto el mismo sitio real?" -- decide el resumen
# deduplicado, la fusión de duplicados existentes Y (get_o_crear_direcciones) si
# vale la pena crear un punto nuevo o ya hay uno cerca. Subido de 100m a 200m el
# 26/08 tras revisar el resultado a mano: a 100m se quedaban fuera pares que a
# simple vista en el mapa eran claramente el mismo sitio. Distinto (más amplio) que
# los 100m de buscar_chequeo_cercano a propósito -- ese umbral decide si REUTILIZAR
# un chequeo ya hecho en vez de scrapear, más conservador porque un falso positivo
# ahí da un dato incorrecto; este decide si dos filas representan el mismo sitio,
# donde ya se revisó a mano que 200m no mezcla sitios distintos (ver
# _agrupar_por_proximidad, que además ya no encadena transitivamente).
UMBRAL_DUPLICADO_KM = 0.2


def _agrupar_por_proximidad(puntos: list[dict], umbral_km: float = UMBRAL_DUPLICADO_KM) -> list[list[dict]]:
    """Agrupa direcciones (con lat/lng) en clusters de "mismo sitio real".

    Cada cluster tiene un punto "ancla" (el primero que entra) -- un punto nuevo se
    une a un cluster existente solo si está a <umbral_km del ANCLA, no de cualquier
    otro miembro ya unido. Antes esto era un cierre transitivo (union-find: si A-B y
    B-C están cerca, A/B/C entraban en el mismo cluster aunque A-C por sí solos no lo
    estuvieran) -- confirmado en vivo 26/08 con umbral_km=0.2 que eso encadenaba
    puntos claramente distintos (un cluster de 22 acabó mezclando una autovía M-40,
    un carril bici y tres números de portal distintos de la misma calle, porque cada
    eslabón individual estaba <200m del siguiente aunque los extremos de la cadena
    quedaran mucho más lejos). Con el ancla, ningún miembro puede estar a más de
    2×umbral_km de otro miembro cualquiera del mismo cluster."""
    clusters: list[list[dict]] = []
    for punto in puntos:
        destino = None
        for cluster in clusters:
            ancla = cluster[0]
            distancia, _ = _distancia_y_angulo(ancla["lat"], ancla["lng"], punto["lat"], punto["lng"])
            if distancia < umbral_km:
                destino = cluster
                break
        if destino is not None:
            destino.append(punto)
        else:
            clusters.append([punto])
    return clusters


def resumen_cobertura_deduplicada() -> dict:
    """Como el conteo normal de vistos/faltan por tienda, pero agrupando primero los
    puntos que son el mismo sitio real repetido en varias tiendas -- para que "cuántas
    direcciones hay vistas/faltan" refleje sitios únicos, no filas infladas por el
    solape de grids entre tiendas vecinas.

    Sin caché (se quitó 26/08): con el scraper corriendo en vivo, una foto de hasta
    120s desincronizaba este número respecto al desglose bruto por tienda (que sí se
    calcula fresco en cada carga) -- confundía más de lo que ahorraba. Tras la
    fusión/limpieza de direcciones del 26/08 el total activo bajó a menos de 1000
    puntos, así que recalcularlo en cada llamada ya no pesa lo que pesaba antes."""
    conn = get_connection()
    try:
        puntos = [dict(fila) for fila in conn.execute("SELECT * FROM agregadores_direcciones WHERE activo=1").fetchall()]
        clusters = _agrupar_por_proximidad(puntos)

        resultado = {}
        for agregador in AGREGADORES:
            # Un punto puede estar globalmente activo (agregadores_direcciones.activo)
            # pero desactivado solo para ESTE agregador (agregadores_direcciones_estado)
            # -- sin filtrar esto, "total" salía distinto (más alto) que la suma del
            # desglose bruto por tienda, que sí aplica este filtro (ver
            # get_o_crear_direcciones). Un cluster sin ningún punto elegible para este
            # agregador no cuenta ni como visto ni como faltante para él.
            inactivos_agregador = {
                row["direccion_id"]
                for row in conn.execute(
                    "SELECT direccion_id FROM agregadores_direcciones_estado WHERE agregador=? AND activo=0",
                    (agregador,),
                ).fetchall()
            }

            total = vistos = 0
            faltan_direcciones = []
            for cluster in clusters:
                elegibles = [p for p in cluster if p["id"] not in inactivos_agregador]
                if not elegibles:
                    continue
                total += 1
                tiene_dato = False
                for tienda in {p["tienda"] for p in elegibles}:
                    puntos_tienda = [p for p in elegibles if p["tienda"] == tienda]
                    con_datos = _con_datos_reales(conn, puntos_tienda, agregador)
                    con_datos |= _cobertura_confirmada_por_limite(conn, tienda, agregador, puntos_tienda)
                    if con_datos:
                        tiene_dato = True
                        break
                if tiene_dato:
                    vistos += 1
                else:
                    faltan_direcciones.append(elegibles[0]["direccion_text"])
            resultado[agregador] = {
                "total": total,
                "vistos": vistos,
                "faltan": total - vistos,
                "faltan_direcciones": sorted(faltan_direcciones),
            }
    finally:
        conn.close()

    return resultado


def iniciar_ronda(agregador: str, total_objetivo: int) -> dict:
    """Marca el inicio de una vuelta completa REAL (ver
    scraper_agregadores/revalidar_completo.py) para poder mostrar progreso en vivo en
    el dashboard integrado (panel_resumen_estados_route). Idempotente a propósito:
    los N workers en paralelo de esa vuelta llaman a esto al arrancar sin
    coordinarse entre sí -- si ya hay una ronda activa (sin finalizar) para este
    agregador, la devuelve tal cual en vez de crear otra; el primero en llegar crea
    la fila, el resto la encuentran ya creada."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT id, iniciada_en, total_objetivo FROM agregadores_rondas "
            "WHERE agregador=? AND finalizada_en IS NULL ORDER BY id DESC LIMIT 1",
            (agregador,),
        ).fetchone()
        if fila:
            return dict(fila)
        ahora = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO agregadores_rondas (agregador, iniciada_en, total_objetivo) VALUES (?, ?, ?)",
            (agregador, ahora, total_objetivo),
        )
        conn.commit()
        return {"id": cur.lastrowid, "iniciada_en": ahora, "total_objetivo": total_objetivo}
    finally:
        conn.close()


def finalizar_ronda(agregador: str) -> None:
    """Idempotente igual que iniciar_ronda -- el UPDATE con WHERE finalizada_en IS
    NULL no hace nada si otro worker ya la cerró antes."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agregadores_rondas SET finalizada_en=? WHERE agregador=? AND finalizada_en IS NULL",
            (datetime.now(timezone.utc).isoformat(), agregador),
        )
        conn.commit()
    finally:
        conn.close()


def get_rondas_actuales() -> dict:
    """Para el panel 'Dashboard del scraper': por agregador, la ÚLTIMA vuelta
    completa (en curso o ya terminada), para que al terminar diga "completado" en
    vez de volver a "sin vuelta en curso" como si nunca hubiera pasado nada (pedido
    explícito del usuario 26/08 -- confundía con "nunca se lanzó"). "hechos" se
    calcula contando agregadores_chequeos reales con timestamp posterior a
    iniciada_en -- ningún worker necesita reportar su propio avance, así que da
    igual cuántos corran en paralelo. Si la ronda se relanzó a mitad (worker-count
    distinto, etc.) tiene su propio iniciada_en más reciente, así que "hechos" no
    arrastra chequeos de un intento anterior abandonado. Para una ronda YA
    terminada, el conteo se acota también por arriba (<= finalizada_en) -- si no,
    el daemon normal (24/7) seguiría sumando chequeos de fondo a una foto que
    debería quedar fija en el momento en que la ronda terminó."""
    conn = get_connection()
    try:
        resultado = {}
        for agregador in AGREGADORES:
            fila = conn.execute(
                "SELECT id, iniciada_en, total_objetivo, finalizada_en FROM agregadores_rondas "
                "WHERE agregador=? ORDER BY id DESC LIMIT 1",
                (agregador,),
            ).fetchone()
            if not fila:
                resultado[agregador] = None
                continue
            if fila["finalizada_en"]:
                hechos = conn.execute(
                    "SELECT COUNT(DISTINCT direccion_id) FROM agregadores_chequeos "
                    "WHERE agregador=? AND timestamp >= ? AND timestamp <= ?",
                    (agregador, fila["iniciada_en"], fila["finalizada_en"]),
                ).fetchone()[0]
            else:
                hechos = conn.execute(
                    "SELECT COUNT(DISTINCT direccion_id) FROM agregadores_chequeos "
                    "WHERE agregador=? AND timestamp >= ?",
                    (agregador, fila["iniciada_en"]),
                ).fetchone()[0]
            resultado[agregador] = {
                "iniciada_en": fila["iniciada_en"],
                "finalizada_en": fila["finalizada_en"],
                "en_curso": fila["finalizada_en"] is None,
                "total_objetivo": fila["total_objetivo"],
                "hechos": hechos,
                "faltan": max(fila["total_objetivo"] - hechos, 0),
            }
        return resultado
    finally:
        conn.close()


def deduplicar_direcciones(umbral_km: float = UMBRAL_DUPLICADO_KM, aplicar: bool = False) -> dict:
    """Encuentra grupos de direcciones activas que son el mismo sitio real (ver
    _agrupar_por_proximidad) y, si aplicar=True, los fusiona: el "ganador" de cada
    grupo es el punto cuya PROPIA tienda es la que _tienda_mas_cercana() de verdad
    devuelve para sus coordenadas (desempate: id más bajo); el resto se desactivan
    (activo=0, igual que eliminar_direccion) tras re-apuntar su historial de
    agregadores_chequeos al ganador -- si no se re-apuntara, buscar_chequeo_cercano
    dejaría de ver ese historial (exige d.activo=1 en su JOIN) y se perdería el
    beneficio de no tener que re-scrapear ese sitio.

    aplicar=False (por defecto) no escribe nada, solo devuelve el plan para revisar."""
    conn = get_connection()
    try:
        puntos = [dict(fila) for fila in conn.execute("SELECT * FROM agregadores_direcciones WHERE activo=1").fetchall()]
        clusters = _agrupar_por_proximidad(puntos, umbral_km)

        plan = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            ganador = min(
                cluster,
                key=lambda p: (0 if _tienda_mas_cercana(p["lat"], p["lng"]) == p["tienda"] else 1, p["id"]),
            )
            perdedores = [p for p in cluster if p["id"] != ganador["id"]]
            plan.append({
                "ganador": {"id": ganador["id"], "tienda": ganador["tienda"], "direccion_text": ganador["direccion_text"]},
                "perdedores": [
                    {"id": p["id"], "tienda": p["tienda"], "direccion_text": p["direccion_text"]} for p in perdedores
                ],
            })

        if aplicar:
            # Mismo efecto que eliminar_direccion() sobre cada perdedor, pero en la
            # MISMA conexión/transacción que el re-apuntado de chequeos -- así las dos
            # cosas quedan atómicas por grupo en vez de arriesgarse a un perdedor
            # desactivado sin que su historial haya llegado a re-apuntarse.
            for grupo in plan:
                ganador_id = grupo["ganador"]["id"]
                for perdedor in grupo["perdedores"]:
                    conn.execute(
                        "UPDATE agregadores_chequeos SET direccion_id=? WHERE direccion_id=?",
                        (ganador_id, perdedor["id"]),
                    )
                    conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE id=?", (perdedor["id"],))
            conn.commit()
    finally:
        conn.close()

    return {
        "aplicado": aplicar,
        "grupos_con_duplicados": len(plan),
        "puntos_a_desactivar": sum(len(g["perdedores"]) for g in plan),
        "detalle": plan,
    }


def adelgazar_por_estado(agregador: str, umbral_km: float = 0.5, aplicar: bool = False) -> dict:
    """Reduce el volumen de una futura "vuelta completa" (re-verificar TODO
    periódicamente, no solo lo que falta -- ver ESTADO_PROYECTO.md 26/08): entre
    puntos cercanos (<umbral_km) que ya tienen el MISMO estado confirmado
    (disponible/no_disponible) para ESTE agregador, se queda uno solo -- el resto se
    desactiva, pero SOLO para este agregador (agregadores_direcciones_estado), no
    globalmente, porque el estado puede diferir entre agregadores en el mismo punto.

    Si un cluster tiene estados DISTINTOS (algún disponible junto a algún no
    disponible) no se toca NADA de ese cluster -- es una frontera real de cobertura
    (justo lo que el usuario quiere poder ver: "en qué zonas nos apagan la zona de
    entrega"), no ruido a limpiar.

    Solo considera puntos con un chequeo real (sin error) ya hecho -- los "sin
    datos" no tienen estado que comparar, se dejan intactos para su propio flujo
    normal. aplicar=False (por defecto) no escribe nada, solo el plan."""
    conn = get_connection()
    try:
        inactivos_previos = {
            row["direccion_id"]
            for row in conn.execute(
                "SELECT direccion_id FROM agregadores_direcciones_estado WHERE agregador=? AND activo=0",
                (agregador,),
            ).fetchall()
        }
        puntos = [
            dict(fila)
            for fila in conn.execute("SELECT * FROM agregadores_direcciones WHERE activo=1").fetchall()
            if fila["id"] not in inactivos_previos
        ]

        ids = [p["id"] for p in puntos]
        estados = {}
        if ids:
            marcadores = ",".join("?" * len(ids))
            filas = conn.execute(
                f"""SELECT c.direccion_id, c.disponible FROM agregadores_chequeos c
                    WHERE c.agregador=? AND c.error_texto IS NULL AND c.direccion_id IN ({marcadores})
                    AND c.timestamp = (
                        SELECT MAX(c2.timestamp) FROM agregadores_chequeos c2
                        WHERE c2.direccion_id=c.direccion_id AND c2.agregador=?
                    )""",
                (agregador, *ids, agregador),
            ).fetchall()
            estados = {fila["direccion_id"]: bool(fila["disponible"]) for fila in filas}

        con_estado = [p for p in puntos if p["id"] in estados]
        clusters = _agrupar_por_proximidad(con_estado, umbral_km)

        plan = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            valores = {estados[p["id"]] for p in cluster}
            if len(valores) > 1:
                continue  # frontera real -- no se toca ningún punto de este cluster
            ganador = min(
                cluster,
                key=lambda p: (0 if _tienda_mas_cercana(p["lat"], p["lng"]) == p["tienda"] else 1, p["id"]),
            )
            perdedores = [p for p in cluster if p["id"] != ganador["id"]]
            plan.append({
                "estado": "disponible" if estados[ganador["id"]] else "no_disponible",
                "ganador": {"id": ganador["id"], "tienda": ganador["tienda"], "direccion_text": ganador["direccion_text"]},
                "perdedores": [
                    {"id": p["id"], "tienda": p["tienda"], "direccion_text": p["direccion_text"]} for p in perdedores
                ],
            })

        if aplicar:
            for grupo in plan:
                for perdedor in grupo["perdedores"]:
                    conn.execute(
                        """INSERT INTO agregadores_direcciones_estado (direccion_id, agregador, activo)
                           VALUES (?, ?, 0)
                           ON CONFLICT(direccion_id, agregador) DO UPDATE SET activo=0""",
                        (perdedor["id"], agregador),
                    )
            conn.commit()
    finally:
        conn.close()

    return {
        "agregador": agregador,
        "aplicado": aplicar,
        "grupos": len(plan),
        "puntos_a_desactivar": sum(len(g["perdedores"]) for g in plan),
        "detalle": plan,
    }


def direcciones_sin_numero(aplicar: bool = False) -> dict:
    """Direcciones activas de las 6 tiendas cuyo texto NO tiene un número de portal
    real (ver _direccion_valida) -- geocoding que, al no encontrar un punto exacto,
    colapsó en el nombre genérico de una calle/zona sin poder afinar más (confirmado:
    la causa de los clusters más grandes en deduplicar_direcciones -- p.ej. 19 puntos
    distintos de granplaza2 todos geocodificados a "Calle de los Geólogos" sin
    número). Sin número de portal no son direcciones de entrega reales -- se
    desactivan TODAS las que cumplan esto, tengan o no dato real ya confirmado
    (pedido explícito del usuario 26/08: una dirección sin número no es fiable como
    destino de entrega aunque algún chequeo haya dado una respuesta ahí). El
    historial de chequeos no se borra, solo deja de contar (activo=0, igual que
    eliminar_direccion).

    aplicar=False (por defecto) no escribe nada, solo devuelve el plan para revisar."""
    conn = get_connection()
    try:
        puntos = [dict(fila) for fila in conn.execute("SELECT * FROM agregadores_direcciones WHERE activo=1").fetchall()]
        candidatos = [p for p in puntos if not _direccion_valida(p["direccion_text"])]
        plan = [{"id": p["id"], "tienda": p["tienda"], "direccion_text": p["direccion_text"]} for p in candidatos]

        if aplicar:
            for punto in plan:
                conn.execute("UPDATE agregadores_direcciones SET activo=0 WHERE id=?", (punto["id"],))
            conn.commit()
    finally:
        conn.close()

    return {
        "aplicado": aplicar,
        "candidatos_sin_numero": len(candidatos),
        "a_desactivar": len(plan),
        "detalle": plan,
    }


def guardar_limite(
    tienda: str, agregador: str, angulo_grados: float, limite_km: float | None, nota: str | None,
    lat: float | None = None, lng: float | None = None, direccion_text: str | None = None,
) -> dict:
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


def mover_limite(tienda: str, agregador: str, angulo_grados: float, lat: float, lng: float) -> dict | None:
    """Reajusta a mano un vértice de límite ya guardado, arrastrándolo en el
    mapa -- recalcula limite_km (distancia real al nuevo punto) y limpia la
    nota/dirección vieja (direccion_text vuelve a None; el frontend ya hace
    reverse geocoding perezoso al abrir el popup si falta, ver
    agrDibujarPoligonoLimite). No cambia angulo_grados -- se sigue tratando
    como el mismo vértice, solo con una posición corregida a mano (pedido
    explícito del usuario 10/08: "no quiero quitarlos quiero moverlos")."""
    if tienda not in TIENDAS:
        return None
    info = TIENDAS[tienda]
    limite_km, _ = _distancia_y_angulo(info["lat"], info["lng"], lat, lng)
    return guardar_limite(
        tienda, agregador, angulo_grados, round(limite_km, 3), "ajustado a mano en el mapa",
        lat=lat, lng=lng, direccion_text=None,
    )


def eliminar_limite(tienda: str, agregador: str, angulo_grados: float) -> bool:
    angulo_guardar = int(round(angulo_grados))
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM agregadores_limites WHERE tienda=? AND agregador=? AND angulo_grados=?",
        (tienda, agregador, angulo_guardar),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def crear_union(
    tienda: str, agregador: str, lat_a: float, lng_a: float, lat_b: float, lng_b: float,
    direccion_id_a: int | None = None, direccion_id_b: int | None = None,
) -> dict:
    """Puente manual entre dos puntos (lat/lng, no direccion_id -- ver
    agregadores_uniones en init_db). El usuario decide a ojo que el hueco
    entre esos dos puntos está cubierto, en vez de que un algoritmo
    automático lo adivine mal."""
    conn = get_connection()
    creado_en = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO agregadores_uniones
           (tienda, agregador, lat_a, lng_a, lat_b, lng_b, direccion_id_a, direccion_id_b, creado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tienda, agregador, lat_a, lng_a, lat_b, lng_b, direccion_id_a, direccion_id_b, creado_en),
    )
    conn.commit()
    union_id = cur.lastrowid
    conn.close()
    return {
        "id": union_id, "tienda": tienda, "agregador": agregador,
        "lat_a": lat_a, "lng_a": lng_a, "lat_b": lat_b, "lng_b": lng_b,
        "direccion_id_a": direccion_id_a, "direccion_id_b": direccion_id_b, "creado_en": creado_en,
    }


def get_uniones(tienda: str, agregador: str = None) -> list[dict]:
    conn = get_connection()
    if agregador:
        filas = conn.execute(
            "SELECT * FROM agregadores_uniones WHERE tienda=? AND agregador=?", (tienda, agregador)
        ).fetchall()
    else:
        filas = conn.execute("SELECT * FROM agregadores_uniones WHERE tienda=?", (tienda,)).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def eliminar_union(union_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM agregadores_uniones WHERE id=?", (union_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def crear_relleno(tienda: str, agregador: str, puntos: list[list[float]]) -> dict:
    """Zona pintada a mano (pincel, ver agregadores_rellenos en init_db):
    lista de [lat, lng] que el frontend fusiona (turf.union) con el polígono
    calculado, para huecos DENTRO de la figura que un puente recto entre dos
    puntos del borde no puede resolver."""
    conn = get_connection()
    creado_en = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO agregadores_rellenos (tienda, agregador, puntos, creado_en) VALUES (?, ?, ?, ?)",
        (tienda, agregador, json.dumps(puntos), creado_en),
    )
    conn.commit()
    relleno_id = cur.lastrowid
    conn.close()
    return {"id": relleno_id, "tienda": tienda, "agregador": agregador, "puntos": puntos, "creado_en": creado_en}


def get_rellenos(tienda: str, agregador: str = None) -> list[dict]:
    conn = get_connection()
    if agregador:
        filas = conn.execute(
            "SELECT * FROM agregadores_rellenos WHERE tienda=? AND agregador=?", (tienda, agregador)
        ).fetchall()
    else:
        filas = conn.execute("SELECT * FROM agregadores_rellenos WHERE tienda=?", (tienda,)).fetchall()
    conn.close()
    resultado = []
    for f in filas:
        d = dict(f)
        d["puntos"] = json.loads(d["puntos"])
        resultado.append(d)
    return resultado


def eliminar_relleno(relleno_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM agregadores_rellenos WHERE id=?", (relleno_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_limites(tienda: str, agregador: str = None) -> list[dict]:
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
    if tienda not in TIENDAS:
        return None
    info = TIENDAS[tienda]

    if not direccion_text:
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
    """Devuelve únicamente distancias reales confirmadas de cobertura disponible."""
    if fila["limite_km"] is not None and fila["limite_km"] > 0:
        return fila["limite_km"]
    return None


def _cobertura_confirmada_por_limite(conn, tienda: str, agregador: str, resultado: list[dict]) -> set:
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
    if not resultado:
        return resultado
    con_datos = _con_datos_reales(conn, resultado, agregador)
    sin_datos = [r for r in resultado if r["id"] not in con_datos]
    sin_datos.sort(key=lambda r: r.get("origen") != "manual")
    con_datos_lista = [r for r in resultado if r["id"] in con_datos]
    return sin_datos + con_datos_lista


def get_o_crear_direcciones(
    tienda: str, radios_km=None, agregador: str | None = None, solo_sin_datos: bool = False,
    ignorar_poligono: bool = False,
) -> list[dict]:
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
                    if fila["activo"]:
                        resultado.append(dict(fila))
                    continue

                lat_dest, lng_dest = _mover_punto(info["lat"], info["lng"], angulo, radio)
                lat_dest, lng_dest, direccion_text = _punto_geocodificado_valido(lat_dest, lng_dest)

                # _punto_geocodificado_valido puede agotar sus reintentos sin
                # encontrar ningún punto cercano con número de portal, y como
                # último recurso devuelve el texto plano de Nominatim tal cual
                # (sin número) -- eso colaba direcciones sin número nuevas
                # incluso después de la limpieza de las 193 ya existentes
                # (confirmado en vivo 26/08 por el usuario: "aun hay calles
                # sin números que sigue scrapeando"). No son destinos de
                # entrega reales (mismo criterio que direcciones_sin_numero),
                # así que este hueco del grid se salta sin crear nada -- mejor
                # un ángulo sin punto que un punto que no representa un sitio
                # real donde se pueda entregar.
                if not _direccion_valida(direccion_text):
                    continue

                # Antes de crear un punto nuevo: ¿alguna tienda (esta u otra) ya tiene
                # un punto activo a <UMBRAL_DUPLICADO_KM de aquí? Sin esto, tiendas
                # vecinas con grids solapados (o geocoding que colapsa en la misma
                # calle) siguen naciendo duplicados nuevos sin parar, incluso después
                # de fusionar los que ya existían (confirmado en vivo 26/08: 8
                # duplicados nuevos en unas horas de scraper corriendo tras la
                # limpieza). Si ya hay uno cerca, este hueco del grid se salta -- ese
                # sitio real ya está representado por el otro punto.
                cercano = conn.execute("SELECT lat, lng FROM agregadores_direcciones WHERE activo=1").fetchall()
                if any(
                    _distancia_y_angulo(fila["lat"], fila["lng"], lat_dest, lng_dest)[0] < UMBRAL_DUPLICADO_KM
                    for fila in cercano
                ):
                    continue

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
                    conn.rollback()
                    fila = conn.execute(
                        "SELECT * FROM agregadores_direcciones WHERE tienda=? AND distancia_km=? AND angulo_grados=?",
                        (tienda, radio, int(angulo)),
                    ).fetchone()
                    if fila and fila["activo"]:
                        resultado.append(dict(fila))

        ids_grid = {r["id"] for r in resultado}
        extra = conn.execute(
            "SELECT * FROM agregadores_direcciones WHERE tienda=? AND activo=1", (tienda,)
        ).fetchall()
        for fila in extra:
            if fila["id"] not in ids_grid:
                resultado.append(dict(fila))

        if agregador:
            inactivos = {
                row["direccion_id"]
                for row in conn.execute(
                    "SELECT direccion_id FROM agregadores_direcciones_estado WHERE agregador=? AND activo=0",
                    (agregador,),
                ).fetchall()
            }
            if inactivos:
                resultado = [r for r in resultado if r["id"] not in inactivos]

        if agregador and solo_sin_datos:
            con_datos = _con_datos_reales(conn, resultado, agregador)
            # ignorar_poligono=True: pasada puntual que quiere comprobar cada punto de
            # verdad, sin dar por buenos los que caen dentro del polígono de cobertura
            # ya confirmado -- ver revalidar_ubereats_sin_poligono.py. La regla normal
            # (con el polígono) se queda intacta para el scheduler de siempre.
            if not ignorar_poligono:
                con_datos |= _cobertura_confirmada_por_limite(conn, tienda, agregador, resultado)
            resultado = [r for r in resultado if r["id"] not in con_datos]
        elif agregador:
            resultado = _priorizar_sin_datos(conn, resultado, agregador)

        return resultado
    finally:
        conn.close()


def borrar_alertas_excepcion_vacia():
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM agregadores_alertas WHERE tipo='scraper_error' AND mensaje LIKE '%excepción no controlada — '"
    )
    conn.commit()
    borradas = cur.rowcount
    conn.close()
    return {"alertas_borradas": borradas}


def borrar_chequeos_error_texto():
    conn = get_connection()
    cur_chequeos = conn.execute("DELETE FROM agregadores_chequeos WHERE error_texto IS NOT NULL")
    cur_alertas = conn.execute("DELETE FROM agregadores_alertas WHERE tipo='scraper_error'")
    conn.commit()
    borrados = {"chequeos": cur_chequeos.rowcount, "alertas": cur_alertas.rowcount}
    conn.close()
    return borrados


def resetear_estadisticas():
    conn = get_connection()
    cur_chequeos = conn.execute("DELETE FROM agregadores_chequeos")
    cur_alertas = conn.execute("DELETE FROM agregadores_alertas")
    conn.commit()
    borrados = {"chequeos": cur_chequeos.rowcount, "alertas": cur_alertas.rowcount}
    conn.close()
    return borrados


def resetear_estadisticas_hoy():
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
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_connection()
    condicion_tienda = "AND c.tienda=?" if tienda else ""
    params = (tienda, desde) if tienda else (desde,)

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

    resultado = []
    for fila in filas:
        fila_dict = dict(fila)
        if fila_dict["timestamp_anterior"]:
            try:
                ts_ant = datetime.fromisoformat(fila_dict["timestamp_anterior"])
                ts_act = datetime.fromisoformat(fila_dict["timestamp"])
                duracion = ts_act - ts_ant
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

        fila_dict["nombre_tienda"] = TIENDAS.get(fila_dict["tienda"], {}).get("nombre", fila_dict["tienda"])
        resultado.append(fila_dict)

    conn.close()
    return resultado


def get_cobertura_mapa(tienda: str | None = None, agregador: str | None = None):
    conn = get_connection()
    condicion_tienda = "AND c.tienda=?" if tienda else ""
    condicion_agregador = "AND c.agregador=?" if agregador else ""
    params = []
    if tienda:
        params.append(tienda)
    if agregador:
        params.append(agregador)

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


def actualizar_tienda_actual(sesion_id: int, tienda: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE agregadores_sesiones SET tienda_actual=? WHERE id=?", (tienda, sesion_id))
    conn.commit()
    conn.close()


def cerrar_sesiones_huerfanas() -> int:
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

    inactivos_por_direccion: dict[int, list[str]] = {}
    if direcciones:
        ids = [d["id"] for d in direcciones]
        marcadores = ",".join("?" * len(ids))
        for row in conn.execute(
            f"""SELECT direccion_id, agregador FROM agregadores_direcciones_estado
                WHERE activo=0 AND direccion_id IN ({marcadores})""",
            ids,
        ).fetchall():
            inactivos_por_direccion.setdefault(row["direccion_id"], []).append(row["agregador"])

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
                "inactivo_para": inactivos_por_direccion.get(d["id"], []),
            }
        )
    conn.close()

    tienda_info = TIENDAS.get(tienda)
    return {
        "tienda": {"tienda": tienda, **tienda_info} if tienda_info else None,
        "direcciones": resultado,
    }


def get_resumen_estados_todas() -> dict:
    """Igual que la leyenda del mapa (ver AGR_LEYENDA_AGREGADOR/agrCategoriaDireccion
    y, sobre todo, _tiendaVisual en agrCargarMapa -- frontend/js/agregadores.js),
    pero agregado en conteos por tienda+agregador en vez de una fila por dirección --
    para el mini dashboard local de status_server.py.

    Agrupa por la TIENDA MÁS CERCANA de verdad (_tienda_mas_cercana), no por la
    columna `tienda` guardada en la fila -- el mapa reasigna cada punto así mismo
    (un punto guardado bajo "caleido" pero geográficamente más cerca de "princesa"
    se cuenta como de Princesa en el mapa). Sin este reajuste, el dashboard y el
    mapa daban números distintos para la misma tienda aunque leyeran la misma base
    de datos (confirmado por el usuario 26/08: "los dots no coinciden con el
    dashboard").

    Un punto desactivado para un agregador concreto (inactivo_para) se salta igual
    que en el mapa: ese agregador ya no lo cuenta en ninguna categoría, ni siquiera
    "sin_datos". Un punto borrado del todo (activo=0) ya ni aparece -- get_mapa_datos
    solo lee filas activas, así que un borrado en producción se refleja aquí en la
    siguiente petición, sin caché de por medio."""
    datos = get_mapa_datos_todas()
    resultado = {t: {a: {"disponible": 0, "no_disponible": 0, "error": 0, "sin_datos": 0} for a in AGREGADORES} for t in TIENDAS}
    for d in datos["direcciones"]:
        tienda_visual = _tienda_mas_cercana(d["lat"], d["lng"]) if d.get("lat") is not None and d.get("lng") is not None else d["tienda"]
        if tienda_visual not in resultado:
            continue
        inactivo_para = d.get("inactivo_para") or []
        for a in AGREGADORES:
            if a in inactivo_para:
                continue
            info = (d.get("detalle") or {}).get(a)
            categoria = info["estado"] if info else "sin_datos"
            resultado[tienda_visual][a][categoria] = resultado[tienda_visual][a].get(categoria, 0) + 1
    return resultado


def get_mapa_datos_todas():
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
            "tienda_actual": fila["tienda_actual"] if en_curso else None,
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
