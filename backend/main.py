import datetime
import mimetypes
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Tiene que ejecutarse ANTES de cualquier import que toque db.py (auth,
# encuestas, informes...): ese módulo crea krispy_kreme.db vacío en cuanto
# se importa si el archivo no existe, y si eso pasara primero ya no
# tendríamos forma de distinguir "disco recién reseteado por Autoscale" de
# "base de datos real". Ver storage_sync.py para el porqué completo.
import storage_sync

storage_sync.restaurar_si_hace_falta()

# En Windows, mimetypes no siempre trae registrados los tipos de fuentes
# (depende del registro del sistema) — sin esto, StaticFiles las sirve como
# application/octet-stream y Chrome rechaza silenciosamente los @font-face.
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth as auth_module
import backups as backups_module
import db as db_module
import scrape_jobs
from auth_routes import COOKIE_NAME, require_admin, require_resenas
from auth_routes import router as auth_router
from boletines_routes import router as boletines_router
from boletines_routes import router_publico as boletines_router_publico
from clima_routes import router as clima_router
from encuestas_routes import router as encuestas_router
from encuestas_routes import router_publico as encuestas_router_publico
from entrevistas_routes import router as entrevistas_router
from informes_routes import router as informes_router
from reclutamiento_routes import router as reclutamiento_router
from request_context import tiendas_permitidas_actual
from routes import router

app = FastAPI(title="Krispy Kreme Reseñas API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def restringir_tiendas_por_usuario(request, call_next):
    """Resuelve, una vez por petición, a qué tiendas tiene acceso el usuario
    de la sesión (si la hay) y lo deja en un contextvar — así build_filters()
    y las funciones de analytics.py pueden aplicar la restricción sin que
    cada endpoint de Reseñas tenga que pedirla explícitamente.

    La tabla `reviews` no distingue empresa (KK/SAONA) por columna propia —
    la separación vive en el registro de tiendas (ver scrape_jobs.tiendas_de_
    empresa()). Por eso aquí, además de la restricción propia del usuario, se
    intersecta SIEMPRE con las tiendas de la empresa pedida (?empresa=, ver
    dashboard.js EMPRESA): sin esto, un usuario sin restricción de tienda
    ("ve todas") vería mezcladas las reseñas de las dos marcas."""
    empresa = request.query_params.get("empresa") or "kk"
    if empresa not in ("kk", "saona"):
        empresa = "kk"
    tiendas_empresa = scrape_jobs.tiendas_de_empresa(empresa)

    token = request.cookies.get(COOKIE_NAME)
    tiendas_usuario = []
    if token:
        user = auth_module.get_user_by_token(token)
        if user:
            tiendas_usuario = auth_module.get_tiendas_permitidas(user["id"])
    tiendas = [t for t in tiendas_usuario if t in tiendas_empresa] if tiendas_usuario else tiendas_empresa

    reset_token = tiendas_permitidas_actual.set(tiendas)
    try:
        return await call_next(request)
    finally:
        tiendas_permitidas_actual.reset(reset_token)


@app.middleware("http")
async def no_cachear_estaticos(request, call_next):
    """StaticFiles no manda Cache-Control, así que el navegador cachea el
    HTML/JS/CSS con heurística propia y puede tardar en recoger cambios
    (hace falta recargar sin caché para verlos). Forzar revalidación en cada
    carga evita ese desfase sin perder el beneficio del ETag/304."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response

# /api/auth/* queda público (login/logout) o resuelve su propia auth (me,
# users). El resto de /api/* exige sesión iniciada. /api/informes/* y
# /api/clima/* exigen además el rol "Todo" (admin/rrhh), ya resuelto en cada
# endpoint de esos routers.
app.include_router(auth_router, prefix="/api/auth")
app.include_router(informes_router, prefix="/api/informes")
app.include_router(reclutamiento_router, prefix="/api/reclutamiento")
app.include_router(clima_router, prefix="/api/clima")
app.include_router(entrevistas_router, prefix="/api/entrevistas")
app.include_router(boletines_router, prefix="/api/boletines")
app.include_router(boletines_router_publico, prefix="/api/public/boletines")
app.include_router(encuestas_router, prefix="/api/encuestas")
app.include_router(encuestas_router_publico, prefix="/api/public/encuestas")
app.include_router(router, prefix="/api", dependencies=[Depends(require_resenas)])


@app.on_event("startup")
def _start_daily_scraper():
    scrape_jobs.start_daily_scheduler()


@app.on_event("startup")
def _start_db_backups():
    backups_module.start_scheduler()


@app.on_event("shutdown")
def _backup_on_shutdown():
    # El backup periódico es cada 6h — si un redeploy de Autoscale llega
    # antes de esa ventana (lo habitual: cada vez que se hace push/pull en
    # Replit y se republica), storage_sync.restaurar_si_hace_falta() solo
    # tiene esa copia vieja para restaurar y se pierde todo lo recibido
    # desde entonces. Al hacer una copia también AQUÍ (justo cuando Autoscale
    # manda la señal de apagado, antes de matar el contenedor), la próxima
    # restauración parte de segundos antes en vez de hasta 6h antes.
    try:
        backups_module.hacer_backup()
    except Exception as e:
        print(f"[backup] Fallo al hacer backup de apagado: {e}", flush=True)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/admin/backup-status")
def backup_status(_admin: dict = Depends(require_admin)):
    """Comprueba si Object Storage está realmente disponible en este
    despliegue (bucket configurado en .replit) y cuándo se hizo el último
    backup remoto — para verificarlo sin tener que mirar los logs."""
    return storage_sync.estado()


@app.get("/api/admin/backup/descargar")
def descargar_backup(_admin: dict = Depends(require_admin)):
    """Descarga manual de la base de datos completa (Test, Informes,
    Boletines, Reclutamiento...) en un solo archivo — red de seguridad extra
    antes de un pull/publish arriesgado: si algo se pierde al republicar, se
    puede restaurar este mismo archivo desde /api/admin/backup/restaurar. No
    incluye los archivos subidos (PDFs, imágenes, CVs), solo las tablas."""
    if not os.path.exists(db_module.DB_PATH):
        raise HTTPException(status_code=404, detail="No hay base de datos que descargar")
    marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        db_module.DB_PATH, media_type="application/octet-stream",
        filename=f"krispy_kreme_{marca}.db",
    )


@app.post("/api/admin/backup/restaurar")
async def restaurar_backup(file: UploadFile = File(...), _admin: dict = Depends(require_admin)):
    """Restaura la base de datos completa desde un archivo descargado antes
    con /api/admin/backup/descargar. Sobreescribe TODO lo que haya ahora
    mismo — se valida que al menos abra como SQLite antes de reemplazar, así
    subir un archivo equivocado no deja la app con la base de datos rota."""
    contenido = await file.read()
    tmp_path = db_module.DB_PATH + ".subida_tmp"
    with open(tmp_path, "wb") as f:
        f.write(contenido)
    conn = None
    valido = False
    try:
        conn = sqlite3.connect(tmp_path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        valido = True
    except Exception:
        pass
    finally:
        # Cerrar SIEMPRE antes de tocar el archivo de nuevo — en Windows una
        # conexión sqlite3 que falló al validar sigue reteniendo el archivo
        # bloqueado, y borrarlo fallaría con un error sin relación (WinError
        # 32) en vez del 400 que se quiere devolver aquí abajo.
        if conn is not None:
            conn.close()
    if not valido:
        os.remove(tmp_path)
        raise HTTPException(status_code=400, detail="El archivo no es una base de datos SQLite válida")
    os.replace(tmp_path, db_module.DB_PATH)
    return {"ok": True}


# Sirve el dashboard (HTML/CSS/JS) desde el mismo proceso y puerto que la API,
# para que un único comando de arranque baste tanto en local como en un
# despliegue (Replit, etc.) — antes hacían falta dos servidores (API +
# estático) en dos puertos distintos. Va DESPUÉS de include_router para que
# las rutas /api/* tengan prioridad sobre el catch-all de archivos estáticos.
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
