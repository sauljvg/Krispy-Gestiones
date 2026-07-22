import mimetypes
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# En Windows, mimetypes no siempre trae registrados los tipos de fuentes
# (depende del registro del sistema) — sin esto, StaticFiles las sirve como
# application/octet-stream y Chrome rechaza silenciosamente los @font-face.
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import scrape_jobs
from auth_routes import get_current_user
from auth_routes import router as auth_router
from clima_routes import router as clima_router
from informes_routes import router as informes_router
from routes import router

app = FastAPI(title="Krispy Kreme Reseñas API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api/auth/* queda público (login/logout) o resuelve su propia auth (me,
# users). El resto de /api/* exige sesión iniciada. /api/informes/* y
# /api/clima/* exigen además el rol "Todo" (admin/rrhh), ya resuelto en cada
# endpoint de esos routers.
app.include_router(auth_router, prefix="/api/auth")
app.include_router(informes_router, prefix="/api/informes")
app.include_router(clima_router, prefix="/api/clima")
app.include_router(router, prefix="/api", dependencies=[Depends(get_current_user)])


@app.on_event("startup")
def _start_daily_scraper():
    scrape_jobs.start_daily_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
