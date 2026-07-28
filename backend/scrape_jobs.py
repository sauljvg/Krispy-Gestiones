"""Lanza scraper_v2.py --update como subproceso desde el botón "Actualizar"
del dashboard, y expone su progreso (que el propio scraper vuelca a un JSON
vía KT_STATUS_FILE) para que el frontend pinte una barra/spinner.
"""
import datetime
import json
import os
import subprocess
import sys
import threading
import time

SCRAPER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scraper"))
SCRAPER_SCRIPT = os.path.join(SCRAPER_DIR, "scraper_v2.py")
STATUS_DIR = os.path.join(SCRAPER_DIR, "status")
os.makedirs(STATUS_DIR, exist_ok=True)

sys.path.insert(0, SCRAPER_DIR)
from stores import STORES  # noqa: E402

_NOMBRE_TO_KEY = {data["nombre"]: key for key, data in STORES.items()}


def resolve_tienda_key(tienda):
    """Acepta tanto la clave del scraper ('parquesur') como el nombre público
    ('ParqueSur') y devuelve la clave, o None si no existe."""
    if tienda in STORES:
        return tienda
    return _NOMBRE_TO_KEY.get(tienda)


def all_tienda_keys():
    return list(STORES.keys())


def tienda_keys_de_empresa(empresa):
    """Claves de scraper ('parquesur', 'saona_madnum'...) de una marca — para
    que el botón "Actualizar" sin tienda concreta en el dashboard de SAONA no
    lance también las 6 tiendas de Krispy Kreme (y viceversa)."""
    return [key for key, data in STORES.items() if data.get("empresa", "kk") == empresa]


def tiendas_de_empresa(empresa):
    """Nombres públicos de las tiendas de una marca ("kk" o "saona") — lo usa
    el middleware de main.py para que el dashboard de Reseñas de una marca no
    pueda ver reseñas de la otra (misma tabla `reviews`, sin columna propia
    de empresa: la separación vive aquí, en el registro de tiendas)."""
    return [data["nombre"] for data in STORES.values() if data.get("empresa", "kk") == empresa]

_lock = threading.Lock()
_running = {}  # tienda_key -> Popen


def _status_path(tienda_key):
    return os.path.join(STATUS_DIR, f"{tienda_key}.json")


def read_status(tienda_key):
    path = _status_path(tienda_key)
    if not os.path.exists(path):
        return {"tienda_key": tienda_key, "status": "idle"}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"tienda_key": tienda_key, "status": "idle"}
    data["tienda_key"] = tienda_key
    data["en_ejecucion"] = is_running(tienda_key)
    return data


def is_running(tienda_key):
    proc = _running.get(tienda_key)
    return proc is not None and proc.poll() is None


def _run_one(tienda_key, completo=False):
    status_file = _status_path(tienda_key)
    try:
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump({"status": "running", "mensaje": "Iniciando…"}, f)
    except OSError:
        pass

    args = [sys.executable, "-u", SCRAPER_SCRIPT, tienda_key]
    if not completo:
        args.append("--update")
    env = {**os.environ, "KT_STATUS_FILE": status_file}
    try:
        proc = subprocess.Popen(
            args,
            cwd=SCRAPER_DIR,
            env=env,
        )
        _running[tienda_key] = proc
        proc.wait()
        if proc.returncode != 0:
            # Si el propio scraper ya dejó un mensaje de error específico (vía
            # write_status en su except), no lo pisamos con uno genérico.
            current = read_status(tienda_key)
            if current.get("status") != "error":
                with open(status_file, "w", encoding="utf-8") as f:
                    json.dump({"status": "error", "mensaje": f"El scraper terminó con código {proc.returncode}"}, f)
    except Exception as e:
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump({"status": "error", "mensaje": str(e)}, f)
        except OSError:
            pass
    finally:
        _running.pop(tienda_key, None)


def _run_queue(tienda_keys):
    for tienda_key in tienda_keys:
        _run_one(tienda_key)


def start_update(tienda_key=None, all_keys=None, completo=False):
    """Lanza la actualización de una tienda, o de todas en cola si
    `tienda_key` es None. `completo=True` hace un escaneo completo (sin
    --update): recorre todo el histórico en vez de parar al pisar territorio
    ya conocido — solo tiene sentido para una tienda concreta (tarda mucho
    más), por eso se ignora si no hay `tienda_key`. Devuelve (ok, mensaje_error)."""
    all_keys = list(all_keys or [])
    with _lock:
        if tienda_key:
            if is_running(tienda_key):
                return False, "Ya hay una actualización en curso para esta tienda."
            threading.Thread(target=_run_one, args=(tienda_key, completo), daemon=True).start()
            return True, None

        if any(is_running(k) for k in all_keys):
            return False, "Ya hay una actualización en curso."
        threading.Thread(target=_run_queue, args=(all_keys,), daemon=True).start()
        return True, None


DAILY_SCRAPE_HOUR = 2  # 02:00 — recauda las reseñas nuevas de todas las tiendas cada noche
_scheduler_started = False


def _seconds_until_next_run(hour=DAILY_SCRAPE_HOUR):
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def _daily_scheduler_loop():
    while True:
        time.sleep(_seconds_until_next_run())
        print(f"[scheduler] {datetime.datetime.now().isoformat(timespec='seconds')} — lanzando actualización diaria de todas las tiendas", flush=True)
        ok, error = start_update(all_keys=all_tienda_keys())
        if not ok:
            print(f"[scheduler] No se pudo iniciar la actualización diaria: {error}", flush=True)
        # Si el hilo tarda <1 minuto en arrancar y la comparación de arriba
        # aún cae en la misma franja horaria, este sleep evita relanzarla dos
        # veces seguidas por redondeos.
        time.sleep(60)


def start_daily_scheduler():
    """Arranca (una sola vez) el hilo en segundo plano que dispara --update
    para las 6 tiendas cada noche a las 02:00. Requiere que el proceso del
    backend siga vivo a esa hora — si el ordenador está apagado no se
    ejecuta, se retoma en el siguiente arranque del backend."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_daily_scheduler_loop, daemon=True).start()
    print(f"[scheduler] Actualización automática diaria programada a las {DAILY_SCRAPE_HOUR:02d}:00.", flush=True)
