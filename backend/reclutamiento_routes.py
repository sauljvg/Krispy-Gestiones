import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import cv_extraction
import reclutamiento as reclutamiento_module
from auth_routes import get_current_user
from informes_routes import require_informes

router = APIRouter()


def require_acceso_candidato(candidato_id: int, user: dict = Depends(get_current_user)) -> dict:
    """A diferencia de require_informes (para la sección propia de
    Reclutamiento), esto también deja pasar a quien no tiene el módulo
    Informes pero SÍ recibió justo este candidato compartido — mismo
    espíritu que /informes/compartidos (get_current_user a secas) para que
    un gerente o area manager pueda abrir la ficha completa que le
    compartieron, no solo la tarjeta resumen."""
    if auth_module.tiene_modulo(user, "informes") or auth_module.tiene_modulo(user, "saona_informes"):
        return user
    if reclutamiento_module.usuario_tiene_acceso_candidato(user["id"], candidato_id):
        return user
    raise HTTPException(status_code=403, detail="No tienes acceso a este candidato")


class VacanteIn(BaseModel):
    empresa: str = "kk"
    puesto: str
    centro: str | None = None
    notas: str | None = None


class VacanteUpdateIn(BaseModel):
    puesto: str | None = None
    centro: str | None = None
    notas: str | None = None
    estado: str | None = None


class CandidatoIn(BaseModel):
    empresa: str = "kk"
    vacante_id: int | None = None
    nombre_completo: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    fecha_nacimiento: str | None = None
    dni: str | None = None
    formacion: str | None = None
    experiencia: str | None = None
    disponibilidad: str | None = None
    puesto_solicitado: str | None = None
    fecha_solicitud: str | None = None
    notas: str | None = None
    extra_fields: dict[str, str] = {}


class EstadoMultipleIn(BaseModel):
    candidato_ids: list[int]
    estado: str


class CompartirCandidatosIn(BaseModel):
    candidato_ids: list[int]
    usuario_id: int


class CandidatoUpdateIn(BaseModel):
    vacante_id: int | None = None
    nombre_completo: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    fecha_nacimiento: str | None = None
    dni: str | None = None
    formacion: str | None = None
    experiencia: str | None = None
    disponibilidad: str | None = None
    puesto_solicitado: str | None = None
    fecha_solicitud: str | None = None
    estado: str | None = None
    notas: str | None = None
    extra_fields: dict[str, str] | None = None


@router.get("/vacantes")
def list_vacantes_route(empresa: str | None = None, estado: str | None = None, _user: dict = Depends(require_informes)):
    return reclutamiento_module.list_vacantes(empresa=empresa, estado=estado)


@router.get("/vacantes/{vacante_id}")
def get_vacante_route(vacante_id: int, _user: dict = Depends(require_informes)):
    vacante = reclutamiento_module.get_vacante(vacante_id)
    if vacante is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    return vacante


@router.post("/vacantes")
def crear_vacante_route(body: VacanteIn, user: dict = Depends(require_informes)):
    vacante_id = reclutamiento_module.crear_vacante(
        body.empresa, body.puesto, centro=body.centro, notas=body.notas, creado_por=user["username"]
    )
    return {"ok": True, "id": vacante_id}


@router.put("/vacantes/{vacante_id}")
def actualizar_vacante_route(vacante_id: int, body: VacanteUpdateIn, _user: dict = Depends(require_informes)):
    if reclutamiento_module.get_vacante(vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    if body.estado is not None and body.estado not in reclutamiento_module.VACANTE_ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.estado}")
    campos = {k: v for k, v in body.model_dump().items() if v is not None}
    reclutamiento_module.actualizar_vacante(vacante_id, campos)
    return {"ok": True}


@router.delete("/vacantes/{vacante_id}")
def eliminar_vacante_route(vacante_id: int, _user: dict = Depends(require_informes)):
    if reclutamiento_module.get_vacante(vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    reclutamiento_module.eliminar_vacante(vacante_id)
    return {"ok": True}


@router.get("/candidatos")
def list_candidatos_route(
    empresa: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    vacante_id: int | None = None,
    sin_vacante: bool = False,
    _user: dict = Depends(require_informes),
):
    return reclutamiento_module.list_candidatos(empresa=empresa, estado=estado, q=q, vacante_id=vacante_id, sin_vacante=sin_vacante)


@router.get("/candidatos/descartados-antiguos")
def descartados_antiguos_route(meses: int = 12, _user: dict = Depends(require_informes)):
    return reclutamiento_module.candidatos_descartados_antiguos(meses)


@router.post("/candidatos/purgar-descartados")
def purgar_descartados_route(meses: int = 12, user: dict = Depends(require_informes)):
    borrados = reclutamiento_module.purgar_descartados(meses)
    return {"ok": True, "borrados": borrados}


@router.post("/candidatos/revincular-tests")
def revincular_candidatos_route(user: dict = Depends(require_informes)):
    enlazados = reclutamiento_module.revincular_candidatos_existentes()
    return {"ok": True, "enlazados": enlazados}


@router.get("/candidatos/conteo-por-estado")
def conteo_por_estado_route(
    empresa: str | None = None,
    q: str | None = None,
    vacante_id: int | None = None,
    sin_vacante: bool = False,
    _user: dict = Depends(require_informes),
):
    return reclutamiento_module.contar_por_estado(empresa=empresa, q=q, vacante_id=vacante_id, sin_vacante=sin_vacante)


@router.put("/candidatos/estado-multiple")
def actualizar_estado_multiple_route(body: EstadoMultipleIn, _user: dict = Depends(require_informes)):
    if body.estado not in reclutamiento_module.ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.estado}")
    reclutamiento_module.actualizar_estado_multiple(body.candidato_ids, body.estado)
    return {"ok": True}


@router.post("/candidatos/compartir")
def compartir_candidatos_route(body: CompartirCandidatosIn, user: dict = Depends(require_informes)):
    reclutamiento_module.compartir_candidatos_directo(body.candidato_ids, body.usuario_id, user["username"])
    return {"ok": True}


@router.delete("/candidatos/{candidato_id}/compartir/{usuario_id}")
def dejar_de_compartir_candidato_route(candidato_id: int, usuario_id: int, _user: dict = Depends(require_informes)):
    reclutamiento_module.dejar_de_compartir_candidato(candidato_id, usuario_id)
    return {"ok": True}


@router.get("/candidatos/{candidato_id}")
def get_candidato_route(candidato_id: int, _user: dict = Depends(require_acceso_candidato)):
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    return candidato


@router.post("/candidatos")
def crear_candidato_route(body: CandidatoIn, user: dict = Depends(require_informes)):
    campos = body.model_dump(exclude={"empresa", "vacante_id"})
    candidato_id = reclutamiento_module.crear_candidato(
        campos, empresa=body.empresa, origen="manual", creado_por=user["username"], vacante_id=body.vacante_id
    )
    return {"ok": True, "id": candidato_id}


@router.put("/candidatos/{candidato_id}")
def actualizar_candidato_route(candidato_id: int, body: CandidatoUpdateIn, _user: dict = Depends(require_acceso_candidato)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if body.estado is not None and body.estado not in reclutamiento_module.ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.estado}")
    # exclude_unset (no "filtrar los None") para poder distinguir "el cliente
    # no mandó este campo, no lo toques" de "el cliente mandó explícitamente
    # null" — necesario para poder desasignar vacante_id (null explícito) sin
    # que las actualizaciones parciales de estado/notas desde "Compartidos"
    # (que no incluyen vacante_id en absoluto) lo desasignen sin querer.
    campos = body.model_dump(exclude_unset=True)
    reclutamiento_module.actualizar_candidato(candidato_id, campos)
    return {"ok": True}


@router.delete("/candidatos/{candidato_id}")
def eliminar_candidato_route(candidato_id: int, _user: dict = Depends(require_informes)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    reclutamiento_module.eliminar_candidato(candidato_id)
    return {"ok": True}


@router.post("/candidatos/extraer-cv")
async def extraer_cv_route(file: UploadFile = File(...), _user: dict = Depends(require_informes)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el CV en formato PDF")
    contenido = await file.read()
    try:
        candidatos, metodo = cv_extraction.extraer_cv(contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "metodo": metodo, "candidatos": candidatos}


@router.post("/candidatos/{candidato_id}/archivos")
async def agregar_archivo_route(candidato_id: int, file: UploadFile = File(...), _user: dict = Depends(require_informes)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    contenido = await file.read()
    archivo_id = reclutamiento_module.agregar_archivo(candidato_id, file.filename, contenido)
    return {"ok": True, "id": archivo_id}


@router.get("/candidatos/{candidato_id}/archivos/{archivo_id}")
def descargar_archivo_route(candidato_id: int, archivo_id: int, _user: dict = Depends(require_acceso_candidato)):
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None or archivo_id not in {a["id"] for a in candidato["archivos"]}:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    archivo = reclutamiento_module.get_archivo(archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    nombre = archivo["nombre_original"] or "archivo"
    media_type = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    return FileResponse(
        archivo["ruta"],
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )
