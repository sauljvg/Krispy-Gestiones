import json
import mimetypes
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    formacion_json: list[dict[str, str]] = []
    experiencia_json: list[dict[str, str]] = []


class EstadoMultipleIn(BaseModel):
    candidato_ids: list[int]
    estado: str


class VacanteMultipleIn(BaseModel):
    candidato_ids: list[int]
    vacante_id: int | None = None


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
    contacto_estado: str | None = None
    extra_fields: dict[str, str] | None = None
    formacion_json: list[dict[str, str]] | None = None
    experiencia_json: list[dict[str, str]] | None = None


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


class FusionarVacanteIn(BaseModel):
    destino_id: int


@router.post("/vacantes/{vacante_id}/fusionar")
def fusionar_vacantes_route(vacante_id: int, body: FusionarVacanteIn, _user: dict = Depends(require_informes)):
    if reclutamiento_module.get_vacante(vacante_id) is None or reclutamiento_module.get_vacante(body.destino_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    if vacante_id == body.destino_id:
        raise HTTPException(status_code=400, detail="Elige una solicitud distinta como destino")
    reclutamiento_module.fusionar_vacantes(vacante_id, body.destino_id)
    return {"ok": True}


class CompartirVacanteIn(BaseModel):
    usuario_ids: list[int]


@router.post("/vacantes/{vacante_id}/compartir")
def compartir_vacante_route(vacante_id: int, body: CompartirVacanteIn, user: dict = Depends(require_informes)):
    """Asigna uno o más gerentes/responsables a TODA la solicitud -- a
    diferencia de /candidatos/compartir (candidato a candidato), esto da
    acceso a todos sus candidatos de una vez, presentes y futuros."""
    if reclutamiento_module.get_vacante(vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    reclutamiento_module.compartir_vacante(vacante_id, body.usuario_ids, user["username"])
    return {"ok": True}


@router.delete("/vacantes/{vacante_id}/compartir/{usuario_id}")
def dejar_de_compartir_vacante_route(vacante_id: int, usuario_id: int, _user: dict = Depends(require_informes)):
    reclutamiento_module.dejar_de_compartir_vacante(vacante_id, usuario_id)
    return {"ok": True}


@router.get("/vacantes-compartidas-conmigo")
def vacantes_compartidas_conmigo_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    """Igual que /candidatos/compartir a nivel de solicitud: vacantes de las
    que este usuario es responsable, con TODOS sus candidatos juntos --
    accesible sin el módulo completo, igual que /informes/compartidos."""
    return reclutamiento_module.get_vacantes_compartidas_con(user["id"], empresa=empresa)


@router.get("/vacantes-compartidas-por-mi")
def vacantes_compartidas_por_mi_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    return reclutamiento_module.get_vacantes_compartidas_por(user["username"], empresa=empresa)


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


@router.put("/candidatos/vacante-multiple")
def actualizar_vacante_multiple_route(body: VacanteMultipleIn, _user: dict = Depends(require_informes)):
    if body.vacante_id is not None and reclutamiento_module.get_vacante(body.vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    reclutamiento_module.actualizar_vacante_multiple(body.candidato_ids, body.vacante_id)
    return {"ok": True}


class MarcarInvitadosTestIn(BaseModel):
    candidato_ids: list[int]
    encuesta_id: int


@router.post("/candidatos/marcar-invitados-test")
def marcar_invitados_test_route(body: MarcarInvitadosTestIn, _user: dict = Depends(require_informes)):
    reclutamiento_module.marcar_invitados_test(body.candidato_ids, body.encuesta_id)
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
    if body.contacto_estado is not None and body.contacto_estado not in reclutamiento_module.CONTACTO_ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado de contacto inválido: {body.contacto_estado}")
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


@router.post("/candidatos/adjuntar-pdf-lote")
async def adjuntar_pdf_lote_route(empresa: str = "kk", file: UploadFile = File(...), _user: dict = Depends(require_informes)):
    """Vista previa para el caso de "subí un PDF con 50 CVs, se crearon las
    50 fichas, pero el PDF en sí nunca se guardó en ninguna" -- lee el mismo
    PDF, extrae los nombres, y por cada uno busca si YA existe una ficha con
    ese nombre exacto (ver buscar_candidato_por_nombre). También calcula en
    qué páginas está cada candidato (detectar_paginas_por_candidato) para
    poder adjuntar solo SU parte del PDF en vez del lote entero -- si el
    número de rangos detectado no coincide con el número de candidatos
    extraídos, se marca division_disponible=false para ese caso y se deja
    que el frontend recorte a mano o adjunte el PDF completo como antes. No
    adjunta nada todavía: eso lo hace /candidatos/adjuntar-pdf-lote/confirmar."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el PDF con todos los candidatos")
    contenido = await file.read()
    try:
        candidatos, metodo = cv_extraction.extraer_cv(contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    try:
        rangos = cv_extraction.detectar_paginas_por_candidato(contenido)
    except Exception:
        rangos = []
    division_disponible = len(rangos) == len(candidatos)
    resultado = []
    for i, c in enumerate(candidatos):
        nombre = (c.get("nombre_completo") or "").strip()
        candidato_id = reclutamiento_module.buscar_candidato_por_nombre(empresa, nombre) if nombre else None
        item = {"nombre": nombre or "(sin nombre detectado)", "candidato_id": candidato_id}
        if division_disponible:
            item["pagina_inicio"], item["pagina_fin"] = rangos[i]
        resultado.append(item)
    return {"ok": True, "metodo": metodo, "candidatos": resultado, "division_disponible": division_disponible, "total_paginas": len(rangos) if not division_disponible else None}


@router.post("/candidatos/adjuntar-pdf-lote/confirmar")
async def adjuntar_pdf_lote_confirmar_route(
    file: UploadFile = File(...),
    mapeo: str = Form(...),
    _user: dict = Depends(require_informes),
):
    """Recorta y adjunta -- recibe el PDF de lote UNA sola vez (en vez de
    subirlo N veces, una por candidato, como hacía antes el frontend) más la
    lista [{candidato_id, pagina_inicio, pagina_fin}] (rangos ya revisados o
    corregidos a mano en la vista previa). Si a algún candidato le falta el
    rango de páginas (detección no disponible para ese caso), se le adjunta
    el PDF completo -- mismo comportamiento que la herramienta original."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el PDF con todos los candidatos")
    try:
        items = json.loads(mapeo)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="mapeo inválido")
    contenido = await file.read()
    adjuntados = 0
    for item in items:
        candidato_id = item.get("candidato_id")
        if not candidato_id:
            continue
        pagina_inicio = item.get("pagina_inicio")
        pagina_fin = item.get("pagina_fin")
        if pagina_inicio and pagina_fin:
            try:
                recorte = cv_extraction.recortar_pdf(contenido, int(pagina_inicio), int(pagina_fin))
            except Exception:
                recorte = contenido
        else:
            recorte = contenido
        reclutamiento_module.agregar_archivo(candidato_id, file.filename, recorte)
        adjuntados += 1
    return {"ok": True, "adjuntados": adjuntados}


@router.post("/candidatos/{candidato_id}/archivos")
async def agregar_archivo_route(candidato_id: int, file: UploadFile = File(...), _user: dict = Depends(require_informes)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    contenido = await file.read()
    archivo_id = reclutamiento_module.agregar_archivo(candidato_id, file.filename, contenido)
    return {"ok": True, "id": archivo_id}


def _leer_archivo_pdf(candidato_id: int, archivo_id: int) -> bytes:
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None or archivo_id not in {a["id"] for a in candidato["archivos"]}:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    archivo = reclutamiento_module.get_archivo(archivo_id)
    if archivo is None or not archivo["nombre_original"].lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Este archivo no es un PDF")
    if not archivo["ruta"] or not os.path.exists(archivo["ruta"]):
        raise HTTPException(status_code=404, detail="El archivo ya no está disponible en el servidor")
    with open(archivo["ruta"], "rb") as f:
        return f.read()


@router.post("/candidatos/{candidato_id}/archivos/{archivo_id}/reextraer")
def reextraer_archivo_route(candidato_id: int, archivo_id: int, _user: dict = Depends(require_acceso_candidato)):
    """Vuelve a leer un PDF que YA está adjunto a esta ficha -- pensado para
    candidatos cuyo CV se extrajo con el metodo "local" (sin IA, mas propenso
    a mezclar columnas) antes de que GEMINI_API_KEY estuviera configurada, o
    cuando Gemini fallo puntualmente en su momento. No sobreescribe nada por
    su cuenta: el frontend rellena el formulario con el resultado para que
    el reclutador lo revise antes de guardar, igual que al subir un CV
    nuevo."""
    contenido = _leer_archivo_pdf(candidato_id, archivo_id)
    try:
        candidatos, metodo = cv_extraction.extraer_cv(contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not candidatos:
        raise HTTPException(status_code=422, detail="No se reconoció ningún candidato en este PDF")
    if len(candidatos) == 1:
        return {"ok": True, "metodo": metodo, "candidato": candidatos[0], "de_lote": False}
    # El PDF adjunto es un lote con varias personas (ver
    # /candidatos/adjuntar-pdf-lote, que adjunta la misma copia a cada
    # ficha) -- hay que identificar cuál de todas es ESTA ficha, por nombre.
    candidato_actual = reclutamiento_module.get_candidato(candidato_id)
    objetivo = reclutamiento_module.normalizar_nombre(candidato_actual.get("nombre_completo") or "")
    encontrado = next(
        (c for c in candidatos if objetivo and reclutamiento_module.normalizar_nombre(c.get("nombre_completo") or "") == objetivo),
        None,
    )
    if encontrado is None:
        raise HTTPException(
            status_code=422,
            detail="Este PDF trae varios candidatos y no se pudo identificar cuál es este por el nombre. "
                   "Comprueba que el campo \"Nombre completo\" de la ficha coincide exactamente con el del PDF.",
        )
    return {"ok": True, "metodo": metodo, "candidato": encontrado, "de_lote": True}


@router.post("/candidatos/{candidato_id}/archivos/{archivo_id}/extraer-foto")
def extraer_foto_route(candidato_id: int, archivo_id: int, _user: dict = Depends(require_acceso_candidato)):
    """Busca la foto de perfil dentro de un PDF ya adjunto y, si encuentra
    una, la guarda como foto del candidato -- se llama automáticamente justo
    después de subir/re-leer un CV (ver compartidos.js), nunca hace falta
    pedirla aparte."""
    contenido = _leer_archivo_pdf(candidato_id, archivo_id)
    foto = cv_extraction.extraer_foto(contenido)
    if foto is None:
        return {"ok": True, "foto_encontrada": False}
    datos, ext = foto
    reclutamiento_module.guardar_foto(candidato_id, datos, ext)
    return {"ok": True, "foto_encontrada": True}


@router.get("/candidatos/{candidato_id}/foto")
def foto_candidato_route(candidato_id: int, _user: dict = Depends(require_acceso_candidato)):
    ruta = reclutamiento_module.get_foto_ruta(candidato_id)
    if not ruta or not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Este candidato no tiene foto")
    media_type = mimetypes.guess_type(ruta)[0] or "image/jpeg"
    return FileResponse(ruta, media_type=media_type)


@router.delete("/candidatos/{candidato_id}/foto")
def quitar_foto_route(candidato_id: int, _user: dict = Depends(require_acceso_candidato)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    reclutamiento_module.quitar_foto(candidato_id)
    return {"ok": True}


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
