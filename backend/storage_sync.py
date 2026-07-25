"""Copia de seguridad fuera del disco efímero de Autoscale, usando Replit
Object Storage (persiste independientemente del tipo de deployment, a
diferencia del disco local que Autoscale resetea en cada redeploy).

Se importa DELIBERADAMENTE sin depender de db.py: importar db.py ejecuta de
inmediato, a nivel de módulo, la creación de tablas — lo que crea
krispy_kreme.db vacío si no existe. Si eso pasara antes de comprobar si hay
que restaurar, restaurar_si_hace_falta() encontraría un archivo "presente" y
ya no sabría que en realidad está vacío por el reinicio del contenedor. Por
eso este módulo calcula la misma ruta por su cuenta y main.py lo ejecuta
antes de importar cualquier otro módulo del backend.
"""
import os

# Misma variable DATA_DIR que db.py (ver ahí el porqué) — se recalcula aquí
# en vez de importarla porque este módulo no puede depender de db.py, según
# se explica arriba.
DATA_DIR = os.environ.get("DATA_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(DATA_DIR, "krispy_kreme.db")
PREFIJO = "backups/"
# Una base con solo el esquema (sin datos reales) pesa unos 8 KB — muy por
# debajo de lo que pesa la base real con datos de producción. Se usa de
# umbral para decidir si el archivo local "parece" recién reseteado.
TAMANO_SOSPECHOSO_BYTES = 200_000


def _client():
    from replit.object_storage import Client

    return Client()


def subir_backup(ruta_local, nombre_objeto):
    """Sube una copia de seguridad ya hecha en disco a Object Storage. Nunca
    lanza excepción — si Object Storage no está disponible (paquete no
    instalado en local, bucket no configurado todavía, etc.) simplemente lo
    registra y sigue: es una capa extra, no debe tumbar el backup local que
    ya funciona sin ella."""
    try:
        _client().upload_from_filename(PREFIJO + nombre_objeto, ruta_local)
    except Exception as e:
        print(f"[storage_sync] No se pudo subir el backup a Object Storage: {e}", flush=True)


def _ultimo_backup_remoto(client):
    nombres = [o.name for o in client.list() if o.name.startswith(PREFIJO)]
    if not nombres:
        return None
    return sorted(nombres)[-1]


def estado():
    """Diagnóstico para comprobar desde fuera (sin depender de mirar los
    logs del despliegue en Replit) si Object Storage está realmente
    disponible y con backups recientes — pensado para verificar que el
    bucket configurado en .replit funciona de verdad en producción, ya que
    en local siempre falla (no existe el paquete 'replit')."""
    resultado = {
        "modulo_replit_disponible": False,
        "bucket_alcanzable": False,
        "num_backups_remotos": 0,
        "ultimo_backup_remoto": None,
        "db_local_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
        "error": None,
    }
    try:
        client = _client()
        resultado["modulo_replit_disponible"] = True
        nombres = [o.name for o in client.list() if o.name.startswith(PREFIJO)]
        resultado["bucket_alcanzable"] = True
        resultado["num_backups_remotos"] = len(nombres)
        resultado["ultimo_backup_remoto"] = sorted(nombres)[-1] if nombres else None
    except Exception as e:
        resultado["error"] = str(e)
    return resultado


def restaurar_si_hace_falta():
    """Si el archivo local no existe o pesa sospechosamente poco (indicio de
    que el contenedor se reinició y perdió el disco), trae la copia más
    reciente de Object Storage antes de que arranque el resto de la app —
    así un redeploy en Autoscale, en el peor caso, pierde solo lo que haya
    entrado desde el último backup (hasta 6h) en vez de todo el histórico.
    Nunca lanza excepción: si algo falla, arranca igual con lo que haya en
    disco (el comportamiento de siempre, sin esta capa)."""
    try:
        local_parece_ok = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > TAMANO_SOSPECHOSO_BYTES
        if local_parece_ok:
            return
        client = _client()
        nombre = _ultimo_backup_remoto(client)
        if not nombre:
            print(
                "[storage_sync] Base de datos local ausente o vacía y no hay backups en Object Storage todavía — arranca de cero.",
                flush=True,
            )
            return
        client.download_to_filename(nombre, DB_PATH)
        print(f"[storage_sync] Base de datos local ausente o vacía: restaurada desde Object Storage ({nombre}).", flush=True)
    except Exception as e:
        print(f"[storage_sync] No se pudo comprobar/restaurar desde Object Storage: {e}", flush=True)
