"""Monitoreo de disponibilidad en JustEat/Glovo/Uber Eats.

El scraper corre en un portátil aparte (necesita un navegador real, headed
para Uber Eats — ver scraper_agregadores/ en la raíz del repo) y llama a la
API en vivo (POST /api/agregadores/chequeo) con cada resultado; aquí solo se
guarda y se sirve. Nada de esto toca Selenium ni el scraper de Reseñas."""
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from db import get_connection

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

GRID_RADIOS_KM = [1.0, 2.5, 5.0, 7.0]
GRID_RADIOS_CERCANO_KM = [1.0]
GRID_ANGULOS_COUNT = 12

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
    r"^(Autov[ií]a|Autopista|Carretera|[AMN]-\d+\b)", re.IGNORECASE
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


def _punto_geocodificado_valido(lat, lng, intentos_extra=5, paso_km=0.05, radio_max_km=0.3):
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


def get_o_crear_direcciones(tienda: str, radios_km=None) -> list[dict]:
    """Genera (si hace falta) y devuelve el grid de puntos de test de una
    tienda. Determinista: mismos radios/ángulos siempre dan los mismos
    puntos, así se puede comparar disponibilidad de un punto en el tiempo."""
    if tienda not in TIENDAS:
        return []
    radios_km = radios_km or GRID_RADIOS_KM
    info = TIENDAS[tienda]

    conn = get_connection()
    resultado = []
    for radio in radios_km:
        for i in range(GRID_ANGULOS_COUNT):
            angulo = (360 / GRID_ANGULOS_COUNT) * i
            fila = conn.execute(
                "SELECT * FROM agregadores_direcciones WHERE tienda=? AND distancia_km=? AND angulo_grados=?",
                (tienda, radio, int(angulo)),
            ).fetchone()
            if fila:
                resultado.append(dict(fila))
                continue

            lat_dest, lng_dest = _mover_punto(info["lat"], info["lng"], angulo, radio)
            lat_dest, lng_dest, direccion_text = _punto_geocodificado_valido(lat_dest, lng_dest)
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
    conn.close()
    return resultado


def guardar_chequeo(data: dict):
    """`data` es el JSON que manda el scraper: tienda, agregador,
    direccion_id, disponible, tiempo_entrega_min, mensaje_bloqueo,
    error_texto. `timestamp` es opcional (por defecto ahora)."""
    conn = get_connection()
    conn.execute(
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
    conn.close()


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
        "SELECT * FROM agregadores_direcciones WHERE tienda=?", (tienda,)
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


def get_reporte(tienda: str, desde: datetime, hasta: datetime):
    conn = get_connection()
    filas = conn.execute(
        "SELECT * FROM agregadores_chequeos WHERE tienda=? AND timestamp>=? AND timestamp<?",
        (tienda, desde.isoformat(), hasta.isoformat()),
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
        pct = (disponibles / len(validos) * 100) if validos else 0.0
        pct_errores = (len(errores) / total * 100) if total else 0.0
        tiempos = [f["tiempo_entrega_min"] for f in validos if f["tiempo_entrega_min"]]
        tiempo_medio = sum(tiempos) / len(tiempos) if tiempos else None

        reporte[nombre] = {
            "disponibilidad_pct": round(pct, 1),
            "tiempo_medio_entrega": round(tiempo_medio, 1) if tiempo_medio else None,
            "total_chequeos": total,
            "chequeos_validos": len(validos),
            "errores": len(errores),
            "errores_pct": round(pct_errores, 1),
        }

    return {
        "fecha_desde": desde.isoformat(),
        "fecha_hasta": hasta.isoformat(),
        "tienda": tienda,
        "agregadores": reporte,
    }


def es_horario_apertura(ahora: datetime = None) -> bool:
    ahora = ahora or datetime.now()
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
