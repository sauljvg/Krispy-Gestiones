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
from db import DATA_DIR, DB_PATH

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
# Antes cada 6h, confiando en que el backup-al-apagarse (ver main.py) cubriera
# el hueco de un redeploy. En la práctica, Replit Autoscale no le da a la app
# ocasión de reaccionar a la señal de apagado (comprobado: tras un redeploy,
# el backup subido justo después resultó ser una simple re-subida del backup
# ANTERIOR, no una copia fresca del estado justo antes de morir — más chico
# de lo que debía, señal de que el evento shutdown nunca llegó a ejecutarse).
# Bajar el intervalo a minutos es la mitigación real para este hosting: en el
# peor caso solo se pierde lo que entró en esta ventana, no hasta 6h.
BACKUP_INTERVAL_MINUTES = 10
BACKUPS_A_CONSERVAR = 30  # ~5 horas de historial local a razón de una copia cada 10 min

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
        time.sleep(BACKUP_INTERVAL_MINUTES * 60)


def start_scheduler():
    """Arranca (una sola vez) el hilo en segundo plano que copia la base de
    datos cada BACKUP_INTERVAL_MINUTES minutos, empezando por una copia
    inmediata al arrancar el backend."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_loop, daemon=True).start()
    print(f"[backup] Copia de seguridad automática cada {BACKUP_INTERVAL_MINUTES} min en {BACKUP_DIR}", flush=True)
