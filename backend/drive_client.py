"""Cliente mínimo de Google Drive para las capturas de pantalla del scraper de
agregadores (ver agregadores.py::guardar_captura_chequeo). El volumen de Railway
es de 500MB y las capturas (una por cada chequeo, no solo errores/transiciones)
se comían el 70% de eso -- 276.6MB en 5095 archivos el 26/08 (pedido explícito
del usuario: "esas capturas podemos enviarlas a un google drive y que se
guarden allí?").

Autenticación: cuenta de servicio de Google Cloud (sin login/consentimiento de
por medio, sin caducidad) -- el JSON completo de la clave va en la variable de
entorno GOOGLE_DRIVE_SA_JSON, y la carpeta de destino (compartida a mano con el
email de esa cuenta de servicio, rol Editor) en GOOGLE_DRIVE_CAPTURAS_FOLDER_ID.
Sin ambas variables, todas las funciones de aquí devuelven None/False sin
lanzar excepción -- el resto del código (agregadores.py) hace fallback al disco
local si Drive no está configurado, para no romper nada en un entorno sin esto
puesto (dev local, tests, etc.).

Scope drive.file (no drive completo): la cuenta de servicio solo necesita
acceso a los archivos que ELLA MISMA crea -- todas las capturas, viejas
(migradas) y nuevas, se suben a través de esta misma cuenta, así que nunca
hace falta el scope amplio "drive" (acceso a todo el Drive del usuario)."""
import io
import json
import os

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

FOLDER_ID = os.environ.get("GOOGLE_DRIVE_CAPTURAS_FOLDER_ID")

_servicio = None
_intentado = False

# nombre de carpeta -> file id, para no buscar/crear la misma carpeta de ronda
# en cada captura -- con miles de capturas por ronda, sin esta caché cada
# subida haría una llamada extra de "files.list" solo para encontrar la
# carpeta que ya se creó hace 2 capturas.
_carpetas_cache: dict[str, str] = {}


def _get_servicio():
    """Construye el cliente de Drive una sola vez por proceso (crear el
    objeto de credenciales/servicio en cada request sería trabajo de más sin
    ningún beneficio -- las credenciales de cuenta de servicio no expiran ni
    cambian en caliente)."""
    global _servicio, _intentado
    if _servicio is not None or _intentado:
        return _servicio
    _intentado = True
    creds_json = os.environ.get("GOOGLE_DRIVE_SA_JSON")
    if not creds_json or not FOLDER_ID:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(creds_json)
        credenciales = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        _servicio = build("drive", "v3", credentials=credenciales, cache_discovery=False)
    except Exception as e:
        print(f"[drive_client] No se pudo inicializar Google Drive: {e!r}", flush=True)
        _servicio = None
    return _servicio


def disponible() -> bool:
    return _get_servicio() is not None


def _get_or_create_subcarpeta(nombre: str) -> str | None:
    """Busca (o crea) una subcarpeta con este nombre directamente dentro de la
    carpeta raíz compartida -- una por ronda, para no dejar miles de capturas
    sueltas en un único listado (pedido explícito del usuario 27/08:
    "organizarlas por ronda... para saber de que vuelta fue"). Cacheada en
    memoria: con miles de capturas de la misma ronda, sin esto cada subida
    repetiría la búsqueda."""
    if nombre in _carpetas_cache:
        return _carpetas_cache[nombre]
    servicio = _get_servicio()
    if not servicio:
        return None
    try:
        nombre_escapado = nombre.replace("'", "\\'")
        query = (
            f"name = '{nombre_escapado}' and mimeType = 'application/vnd.google-apps.folder' "
            f"and '{FOLDER_ID}' in parents and trashed = false"
        )
        resultado = servicio.files().list(
            q=query, spaces="drive", fields="files(id)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        encontradas = resultado.get("files", [])
        if encontradas:
            carpeta_id = encontradas[0]["id"]
        else:
            carpeta = servicio.files().create(
                body={"name": nombre, "mimeType": "application/vnd.google-apps.folder", "parents": [FOLDER_ID]},
                fields="id", supportsAllDrives=True,
            ).execute()
            carpeta_id = carpeta["id"]
        _carpetas_cache[nombre] = carpeta_id
        return carpeta_id
    except Exception as e:
        print(f"[drive_client] Fallo creando/buscando la carpeta '{nombre}': {e!r}", flush=True)
        return None


def subir_captura(nombre: str, contenido: bytes, carpeta_ronda: str | None = None) -> str | None:
    """Sube una captura a la carpeta compartida (o a la subcarpeta de la ronda
    correspondiente, si se pasa `carpeta_ronda`), devuelve el file id de Drive
    (o None si Drive no está configurado o falla la subida -- el llamador
    decide el fallback)."""
    servicio = _get_servicio()
    if not servicio:
        return None
    parent = FOLDER_ID
    if carpeta_ronda:
        parent = _get_or_create_subcarpeta(carpeta_ronda) or FOLDER_ID
    try:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype="image/png", resumable=False)
        archivo = servicio.files().create(
            body={"name": nombre, "parents": [parent]},
            media_body=media,
            fields="id",
            supportsAllDrives=True,  # el destino es una Unidad compartida, no "Mi unidad"
        ).execute()
        return archivo["id"]
    except Exception as e:
        print(f"[drive_client] Fallo subiendo '{nombre}' a Drive: {e!r}", flush=True)
        return None


def descargar_captura(file_id: str) -> bytes | None:
    servicio = _get_servicio()
    if not servicio:
        return None
    try:
        from googleapiclient.http import MediaIoBaseDownload

        peticion = servicio.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, peticion)
        terminado = False
        while not terminado:
            _, terminado = downloader.next_chunk()
        return buffer.getvalue()
    except Exception as e:
        print(f"[drive_client] Fallo descargando '{file_id}' de Drive: {e!r}", flush=True)
        return None


def borrar_captura(file_id: str) -> bool:
    servicio = _get_servicio()
    if not servicio:
        return False
    try:
        servicio.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        return True
    except Exception as e:
        print(f"[drive_client] Fallo borrando '{file_id}' de Drive: {e!r}", flush=True)
        return False
