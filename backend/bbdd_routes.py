import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import bbdd as bbdd_module
import cv_extraction
import reclutamiento as reclutamiento_module
from auth_routes import require_admin
from informes_routes import require_informes_o_reclutamiento
from reclutamiento_routes import _exigir_modulo_empresa, require_acceso_candidato

router = APIRouter()
router_publico = APIRouter()

# Tope contra un archivo absurdo desde un formulario sin autenticar (nadie
# más lo valida antes de llegar aquí) -- 10 MB es generoso para un PDF de CV
# real de un par de páginas.
MAX_CV_BYTES = 10 * 1024 * 1024


class EtiquetaIn(BaseModel):
    nombre: str
    color: str | None = None


@router.get("/candidatos")
def listar_bbdd_route(
    empresa: str = "kk",
    etiqueta_id: int | None = None,
    estado: str | None = None,
    carrera: str | None = None,
    idioma: str | None = None,
    nacionalidad: str | None = None,
    edad_min: int | None = None,
    edad_max: int | None = None,
    q: str | None = None,
    user: dict = Depends(require_informes_o_reclutamiento),
):
    _exigir_modulo_empresa(empresa, user)
    return bbdd_module.list_bbdd(
        empresa=empresa, etiqueta_id=etiqueta_id, estado=estado, carrera=carrera,
        idioma=idioma, nacionalidad=nacionalidad, edad_min=edad_min, edad_max=edad_max, q=q,
    )


@router.get("/etiquetas")
def listar_etiquetas_route(_user: dict = Depends(require_informes_o_reclutamiento)):
    return bbdd_module.listar_etiquetas()


@router.post("/etiquetas")
def crear_etiqueta_route(body: EtiquetaIn, user: dict = Depends(require_informes_o_reclutamiento)):
    try:
        etiqueta_id = bbdd_module.crear_etiqueta(body.nombre, body.color, creado_por=user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "id": etiqueta_id}


# Solo admin -- una etiqueta es un catálogo GLOBAL compartido entre KK y
# Saona (ver bbdd.py), borrarla la quita de golpe de todos los candidatos que
# la tuvieran en cualquiera de las dos marcas, así que no basta con tener el
# módulo de una sola empresa.
@router.delete("/etiquetas/{etiqueta_id}")
def eliminar_etiqueta_route(etiqueta_id: int, _user: dict = Depends(require_admin)):
    bbdd_module.eliminar_etiqueta(etiqueta_id)
    return {"ok": True}


@router.post("/candidatos/{candidato_id}/etiquetas/{etiqueta_id}")
def asignar_etiqueta_route(candidato_id: int, etiqueta_id: int, user: dict = Depends(require_acceso_candidato)):
    bbdd_module.asignar_etiqueta(candidato_id, etiqueta_id, asignado_por=user["username"])
    return {"ok": True}


@router.delete("/candidatos/{candidato_id}/etiquetas/{etiqueta_id}")
def quitar_etiqueta_route(candidato_id: int, etiqueta_id: int, _user: dict = Depends(require_acceso_candidato)):
    bbdd_module.quitar_etiqueta(candidato_id, etiqueta_id)
    return {"ok": True}


@router.get("/carreras-ie")
def carreras_ie_route(_user: dict = Depends(require_informes_o_reclutamiento)):
    return bbdd_module.CARRERAS_IE


# --- Público (sin autenticar) -- formulario del evento con el IE ---
#
# Detrás de un QR/NFC en un evento: cualquiera con el enlace puede darse de
# alta aquí, así que estos endpoints no exigen sesión (igual que
# encuestas_routes.router_publico/disc_module.router_publico, mismo patrón ya
# usado en la app para formularios públicos).

@router_publico.get("/carreras-ie")
def carreras_ie_publico_route():
    return bbdd_module.CARRERAS_IE


@router_publico.get("/rgpd-texto-version")
def rgpd_texto_version_route():
    return {"version": bbdd_module.RGPD_TEXTO_VERSION}


@router_publico.post("/ie")
async def alta_publica_ie_route(
    nombre_completo: str = Form(...),
    telefono: str | None = Form(None),
    email: str | None = Form(None),
    fecha_nacimiento: str | None = Form(None),
    carrera: str | None = Form(None),
    idiomas: str | None = Form(None),
    nacionalidad: str | None = Form(None),
    disponibilidad: str | None = Form(None),
    notas: str | None = Form(None),
    rgpd_aceptado: bool = Form(...),
    cv: UploadFile | None = File(None),
):
    if not rgpd_aceptado:
        raise HTTPException(status_code=400, detail="Debes aceptar el tratamiento de tus datos para continuar")
    if not nombre_completo.strip():
        raise HTTPException(status_code=400, detail="Falta el nombre")
    campos = {
        "nombre_completo": nombre_completo.strip(),
        "telefono": telefono, "email": email, "fecha_nacimiento": fecha_nacimiento,
        "carrera": carrera, "idiomas": idiomas, "nacionalidad": nacionalidad,
        "disponibilidad": disponibilidad, "notas": notas,
    }
    candidato_id = bbdd_module.crear_candidato_publico_ie(campos, empresa="kk")
    if cv is not None and cv.filename:
        if not cv.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El CV debe ser un PDF")
        contenido = await cv.read()
        if len(contenido) > MAX_CV_BYTES:
            raise HTTPException(status_code=400, detail="El CV es demasiado grande (máximo 10 MB)")
        reclutamiento_module.agregar_archivo(candidato_id, cv.filename, contenido)
    return {"ok": True, "id": candidato_id}


@router_publico.post("/ie/extraer-cv")
async def extraer_cv_publico_route(file: UploadFile = File(...)):
    """Auto-relleno del formulario público a partir de un CV en PDF -- mismo
    extractor local que ya usa Reclutamiento (ver cv_extraction.extraer_cv),
    sin autenticar porque el propio formulario tampoco lo está. Solo LEE el
    PDF para devolver los datos al navegador, que rellena el formulario; no
    crea ninguna ficha todavía (eso lo hace /ie al enviar, tras aceptar
    RGPD -- leer el CV no implica que la persona ya haya dado su
    consentimiento)."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el CV en formato PDF")
    contenido = await file.read()
    if len(contenido) > MAX_CV_BYTES:
        raise HTTPException(status_code=400, detail="El archivo es demasiado grande (máximo 10 MB)")
    try:
        candidatos = await asyncio.to_thread(cv_extraction.extraer_cv, contenido)
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer el PDF")
    if not candidatos:
        raise HTTPException(status_code=400, detail="No se pudo leer el PDF")
    return candidatos[0]
