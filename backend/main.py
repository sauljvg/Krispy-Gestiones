import datetime
import mimetypes
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))

import storage_sync

# Podar antes de que arranque el resto de la app: si el volumen está lleno
# del todo, borrar es lo único que no necesita espacio libre. Ver
# storage_sync.podar_backups_locales.
storage_sync.podar_backups_locales()

# En Windows, mimetypes no siempre trae registrados los tipos de fuentes
# (depende del registro del sistema) — sin esto, StaticFiles las sirve como
# application/octet-stream y Chrome rechaza silenciosamente los @font-face.
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import agregadores as agregadores_module
import auth as auth_module
import backups as backups_module
import db as db_module
import encuestas as encuestas_module
import scrape_jobs
from auth_routes import COOKIE_NAME, require_admin, require_resenas
from auth_routes import router as auth_router
from agregadores_routes import router as agregadores_router
from boletines_routes import router as boletines_router
from boletines_routes import router_publico as boletines_router_publico
from clima_routes import router as clima_router
from david_routes import router as david_router
from disc_module import router as disc_router
from disc_module import router_publico as disc_router_publico
from encuestas_routes import router as encuestas_router
from encuestas_routes import router_publico as encuestas_router_publico
from entrevistas_routes import router as entrevistas_router
from evaluaciones360_routes import router as evaluaciones360_router
from informes_routes import router as informes_router
from manuales_routes import router as manuales_router
from notificaciones_routes import router as notificaciones_router
import reclutamiento as reclutamiento_module
from reclutamiento_routes import reanudar_lotes_ia_pendientes
from reclutamiento_routes import router as reclutamiento_router
from request_context import tiendas_permitidas_actual
from routes import router

app = FastAPI(title="Krispy Kreme Reseñas API")

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] es más abierto de lo que hace falta -- el frontend
    # se sirve desde este mismo proceso (ver app.mount("/", StaticFiles...)
    # más abajo), así que un fetch normal del propio portal no necesita CORS
    # en absoluto. Se deja así (bajo riesgo real: no hay allow_credentials,
    # así que un fetch cross-origin con la cookie de sesión no funciona por
    # defecto en el navegador) por si algún día hace falta un tercero
    # consumiendo la API -- si nunca aparece ese caso, restringir
    # allow_origins al dominio propio sería lo correcto.
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
            # Historial de accesos (solo lo consulta Saúl, ver
            # historial_accesos_route) -- se aprovecha esta misma resolución
            # de usuario (ya hecha en CADA request autenticado para lo de
            # arriba) para no añadir una segunda consulta a la sesión.
            partes = request.url.path.strip("/").split("/")
            if len(partes) >= 2 and partes[0] == "api" and partes[1] not in ("auth", "notificaciones"):
                auth_module.registrar_acceso_modulo(user["id"], partes[1])
    tiendas = [t for t in tiendas_usuario if t in tiendas_empresa] if tiendas_usuario else tiendas_empresa

    reset_token = tiendas_permitidas_actual.set(tiendas)
    try:
        return await call_next(request)
    finally:
        tiendas_permitidas_actual.reset(reset_token)


@app.middleware("http")
async def no_cachear_estaticos(request, call_next):
    """StaticFiles no manda Cache-Control, así que el navegador cachea el
    HTML/JS/CSS con heurística propia y puede tardar en recoger cambios (hace
    falta recargar sin caché para verlos) -- se vio en producción con el HTML
    de Evaluaciones 360°: alguien con una copia vieja en caché (de antes de
    "hidden" en las pestañas de gestión) las veía parpadear un instante antes
    de que el JS (ese sí, ya actualizado) las ocultara según su rol. "no-cache"
    solo obliga a revalidar (el navegador puede seguir reusando el cuerpo si
    el servidor responde 304); "no-store" prohíbe guardar copia local del
    todo, así que cada carga trae SIEMPRE el HTML/JS/CSS actual, sin lugar a
    ambigüedad de qué versión se está pintando."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response

# /api/auth/* queda público (login/logout) o resuelve su propia auth (me,
# users). El resto de /api/* exige sesión iniciada. /api/informes/* y
# /api/clima/* exigen además el rol "Todo" (admin/rrhh), ya resuelto en cada
# endpoint de esos routers.
app.include_router(auth_router, prefix="/api/auth")
app.include_router(informes_router, prefix="/api/informes")
app.include_router(manuales_router, prefix="/api/manuales")
app.include_router(reclutamiento_router, prefix="/api/reclutamiento")
app.include_router(clima_router, prefix="/api/clima")
app.include_router(entrevistas_router, prefix="/api/entrevistas")
app.include_router(evaluaciones360_router, prefix="/api/evaluaciones360")
app.include_router(boletines_router, prefix="/api/boletines")
app.include_router(boletines_router_publico, prefix="/api/public/boletines")
app.include_router(encuestas_router, prefix="/api/encuestas")
app.include_router(encuestas_router_publico, prefix="/api/public/encuestas")
app.include_router(disc_router, prefix="/api/disc")
app.include_router(disc_router_publico, prefix="/api/public/disc")
app.include_router(david_router, prefix="/api/david")
app.include_router(agregadores_router, prefix="/api/agregadores")
app.include_router(notificaciones_router, prefix="/api")
app.include_router(router, prefix="/api", dependencies=[Depends(require_resenas)])


@app.on_event("startup")
def _start_db_backups():
    backups_module.start_scheduler()
    agregadores_module.start_scheduler_limpieza_capturas()
    reclutamiento_module.start_scheduler_purga_pdfs()
    reanudar_lotes_ia_pendientes()


@app.on_event("shutdown")
def _backup_on_shutdown():
    # Copia extra justo al apagarse (redeploy, reinicio...) para que la
    # próxima arrancada tenga una copia de segundos antes en vez de hasta
    # BACKUP_INTERVAL_MINUTES antes.
    try:
        backups_module.hacer_backup()
    except Exception as e:
        print(f"[backup] Fallo al hacer backup de apagado: {e}", flush=True)


@app.get("/api/health")
def health():
    return {"status": "ok"}


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


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


@app.get("/encuesta.html")
def encuesta_html_route(request: Request, slug: str | None = None):
    """encuesta.html es un archivo estático fijo — el favicon/og:image que
    distingue SAONA de Krispy Kreme hoy se decide en JS (encuesta.js), así
    que un crawler que NO ejecuta JS (WhatsApp, Facebook, etc. generando la
    vista previa de un enlace compartido) siempre ve el favicon de KK sin
    importar el test. Esta ruta intercepta la petición antes del StaticFiles
    de abajo y, si el slug corresponde a un test SAONA, sirve el HTML con el
    favicon y unas meta og: ya correctas — así la vista previa del enlace
    compartido también acierta, no solo lo que ve quien abre el enlace en el
    navegador."""
    import html as html_module

    ruta = os.path.join(FRONTEND_DIR, "encuesta.html")
    with open(ruta, encoding="utf-8") as f:
        contenido = f.read()
    if not slug:
        return HTMLResponse(contenido)
    encuesta = encuestas_module.get_encuesta_publica(slug)
    if not encuesta:
        return HTMLResponse(contenido)
    es_saona = "saona" in encuesta["titulo"].lower()
    favicon = "assets/favicon-saona.png" if es_saona else "assets/favicon-kk.png"
    titulo_seguro = html_module.escape(encuesta["titulo"])
    base_url = str(request.base_url).rstrip("/")
    contenido = contenido.replace(
        '<link rel="icon" type="image/png" href="assets/favicon-kk.png">',
        f'<link rel="icon" type="image/png" href="{favicon}">\n'
        f'<meta property="og:title" content="{titulo_seguro}">\n'
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:image" content="{base_url}/{favicon}">',
    )
    contenido = contenido.replace("<title>Test</title>", f"<title>{titulo_seguro}</title>")
    return HTMLResponse(contenido)


# Sirve el dashboard (HTML/CSS/JS) desde el mismo proceso y puerto que la API,
# para que un único comando de arranque baste tanto en local como en un
# despliegue (Replit, etc.) — antes hacían falta dos servidores (API +
# estático) en dos puertos distintos. Va DESPUÉS de include_router para que
# las rutas /api/* tengan prioridad sobre el catch-all de archivos estáticos.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
