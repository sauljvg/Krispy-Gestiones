"""Poda de copias de seguridad locales para no llenar el disco.

Antes este módulo también subía cada backup a Replit Object Storage (la app
corría en Replit Autoscale, con disco efímero que se perdía en cada
redeploy). En Railway el volumen es persistente de verdad, así que esa capa
extra ya no aporta nada — solo generaba un intento fallido cada 10 min
(Object Storage de Replit no existe fuera de Replit). Se quitó, dejando solo
la poda local de espacio.
"""
import os

# Misma variable DATA_DIR que db.py — se recalcula aquí para no depender de
# ese módulo (ver db.py: importarlo ejecuta la creación de tablas al vuelo).
DATA_DIR = os.environ.get("DATA_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def podar_backups_locales(dejar=1):
    """Borra copias locales de `backups/` dejando solo las `dejar` más
    recientes — se llama ANTES de cualquier otra cosa (incluso antes de que
    arranque el resto de la app) porque borrar no necesita espacio libre, a
    diferencia de escribir. Es el único recurso real cuando el volumen se
    llenó del todo y ni una INSERT normal puede ejecutarse (visto en Railway
    con un volumen de 500 MB): sin esto, la app no llega ni a arrancar para
    que la rotación normal de backups.py actúe. Nunca lanza excepción."""
    try:
        carpeta = os.path.join(DATA_DIR, "backups")
        if not os.path.isdir(carpeta):
            return
        archivos = sorted(
            f for f in os.listdir(carpeta) if f.startswith("krispy_kreme_") and f.endswith(".db")
        )
        de_mas = len(archivos) - dejar
        for nombre in archivos[: max(de_mas, 0)]:
            os.remove(os.path.join(carpeta, nombre))
        if de_mas > 0:
            print(f"[storage_sync] Podadas {de_mas} copias de seguridad locales antiguas para liberar espacio.", flush=True)
    except Exception as e:
        print(f"[storage_sync] No se pudieron podar los backups locales: {e}", flush=True)
