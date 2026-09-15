import asyncio
import json

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

# Pedido explícito del usuario 16/09: "la fecha de nacimiento aceptamos a
# partir de 15 años, menores de eso no" -- el <input type="date"> del
# formulario ya limita la fecha elegible con el mismo mínimo (ver
# ie-formulario.html), pero eso es solo UX: la comprobación real, la que de
# verdad protege el dato, tiene que vivir aquí (un formulario sin autenticar
# se puede llamar directamente sin pasar por ese <input>).
EDAD_MINIMA_IE = 15

# Claves conocidas de una entrada de experiencia laboral (mismo shape que
# reclutamiento.py::experiencia_json en el resto de la app, ver
# _parsear_experiencia_local en cv_extraction.py) -- se filtra a esto antes
# de guardar para que un formulario sin autenticar no pueda colar claves
# arbitrarias dentro del JSON.
CAMPOS_EXPERIENCIA = {"puesto", "empresa", "fecha_inicio", "fecha_fin", "descripcion"}


def _sanear_experiencia_json(raw: str | None) -> list[dict]:
    """Parsea y sanea la experiencia laboral que manda el formulario público
    (viaja como texto JSON dentro de un campo de formulario, ver
    ie-formulario.html) -- solo se aceptan las claves conocidas
    (CAMPOS_EXPERIENCIA), el resto se descarta en vez de fallar entero, y una
    entrada sin puesto ni empresa se descarta por vacía."""
    if not raw:
        return []
    try:
        datos = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="No se pudo leer la experiencia laboral enviada")
    if not isinstance(datos, list):
        raise HTTPException(status_code=400, detail="No se pudo leer la experiencia laboral enviada")
    resultado = []
    for entrada in datos:
        if not isinstance(entrada, dict):
            continue
        limpio = {k: (str(v).strip() if v else "") for k, v in entrada.items() if k in CAMPOS_EXPERIENCIA}
        if limpio.get("puesto") or limpio.get("empresa"):
            resultado.append(limpio)
    return resultado


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
    fecha_nacimiento: str = Form(...),
    carrera: str | None = Form(None),
    idiomas: str | None = Form(None),
    nacionalidad: str | None = Form(None),
    disponibilidad: str | None = Form(None),
    notas: str | None = Form(None),
    experiencia_json: str | None = Form(None),
    rgpd_aceptado: bool = Form(...),
    cv: UploadFile | None = File(None),
):
    if not rgpd_aceptado:
        raise HTTPException(status_code=400, detail="Debes aceptar el tratamiento de tus datos para continuar")
    if not nombre_completo.strip():
        raise HTTPException(status_code=400, detail="Falta el nombre")
    edad = bbdd_module._edad(fecha_nacimiento)
    if edad is None:
        raise HTTPException(status_code=400, detail="La fecha de nacimiento no es válida")
    if edad < EDAD_MINIMA_IE:
        raise HTTPException(status_code=400, detail=f"Debes tener al menos {EDAD_MINIMA_IE} años para completar este formulario")
    campos = {
        "nombre_completo": nombre_completo.strip(),
        "telefono": telefono, "email": email, "fecha_nacimiento": fecha_nacimiento,
        "carrera": carrera, "idiomas": idiomas, "nacionalidad": nacionalidad,
        "disponibilidad": disponibilidad, "notas": notas,
        "experiencia_json": _sanear_experiencia_json(experiencia_json),
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
