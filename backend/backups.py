"""Copia de seguridad periódica de krispy_kreme.db.

Mientras no se resuelva la persistencia de verdad (Reserved VM en vez de
Autoscale, o migrar a Postgres), esto es una red de seguridad barata: si el
despliegue pierde el archivo en vivo (redeploy, reinicio del contenedor,
error humano...), al menos queda una copia de hace pocas horas en vez de
partir de cero como ha pasado ya un par de veces.
"""
import datetime
import os
import shutil
import threading
import time

import storage_sync
from db import DB_PATH

BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
BACKUP_INTERVAL_HOURS = 6
BACKUPS_A_CONSERVAR = 20  # ~5 dias de historial a razon de una copia cada 6h

_scheduler_started = False


def hacer_backup():
    if not os.path.exists(DB_PATH):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"krispy_kreme_{marca}.db"
    destino = os.path.join(BACKUP_DIR, nombre)
    shutil.copy2(DB_PATH, destino)
    # El disco local también se pierde en cada reinicio de Autoscale, así
    # que la copia local sola no basta como red de seguridad — se sube
    # además a Object Storage (persistente de verdad) para poder restaurarla
    # al arrancar si el disco viene vacío (ver storage_sync.py).
    storage_sync.subir_backup(destino, nombre)
    _rotar_backups()


def _rotar_backups():
    archivos = sorted(
        f for f in os.listdir(BACKUP_DIR) if f.startswith("krispy_kreme_") and f.endswith(".db")
    )
    de_mas = len(archivos) - BACKUPS_A_CONSERVAR
    for nombre in archivos[: max(de_mas, 0)]:
        os.remove(os.path.join(BACKUP_DIR, nombre))


def _loop():
    while True:
        try:
            hacer_backup()
        except Exception as e:
            print(f"[backup] Fallo al hacer backup: {e}", flush=True)
        time.sleep(BACKUP_INTERVAL_HOURS * 3600)


def start_scheduler():
    """Arranca (una sola vez) el hilo en segundo plano que copia la base de
    datos cada BACKUP_INTERVAL_HOURS horas, empezando por una copia
    inmediata al arrancar el backend."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_loop, daemon=True).start()
    print(f"[backup] Copia de seguridad automática cada {BACKUP_INTERVAL_HOURS}h en {BACKUP_DIR}", flush=True)
