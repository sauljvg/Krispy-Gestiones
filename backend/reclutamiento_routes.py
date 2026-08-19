import json
import mimetypes
import os
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import cv_extraction
import cv_pdf
import notificaciones as notificaciones_module
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
        candidatos, metodo, motivo_local = cv_extraction.extraer_cv(contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "metodo": metodo, "motivo_local": motivo_local, "candidatos": candidatos}


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
        candidatos, metodo, motivo_local = cv_extraction.extraer_cv(contenido)
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
    return {
        "ok": True, "metodo": metodo, "motivo_local": motivo_local, "candidatos": resultado,
        "division_disponible": division_disponible, "total_paginas": len(rangos) if not division_disponible else None,
    }


# Progreso del relleno en segundo plano, en memoria -- un proceso Railway
# único (ver el incidente de más arriba), así que no hace falta nada más
# elaborado que un diccionario para que el frontend pueda sondear "cuántos
# van". Se pierde si el servidor se reinicia a media tanda, pero es solo un
# indicador de progreso, no un dato que haga falta conservar.
_progreso_lotes: dict[str, dict] = {}


# Margen bajo el límite de 10 peticiones/minuto del plan gratuito de Gemini
# (ver GEMINI_MODEL en cv_extraction) -- con esto de por medio, un lote de 37
# candidatos tarda más en procesarse pero prácticamente no choca con el
# límite de RPM, así que casi todos acaban pasando por IA en vez de solo los
# primeros ~9 antes de que saltara el 429 (ver GeminiLimiteTemporalError).
GEMINI_ESPACIADO_SEGUNDOS = 7
GEMINI_MAX_REINTENTOS_RPM = 2


def _rellenar_huecos_en_segundo_plano(lote_id: str, recortes: list[tuple[int, bytes]], usuario_id: int):
    """Re-extrae con IA cada recorte y rellena huecos -- se ejecuta DESPUÉS
    de responder al navegador (ver BackgroundTasks en la ruta de abajo).
    Antes esto iba dentro de la propia petición: con Gemini saturado, cada
    llamada podía tardar hasta el timeout (ver cv_extraction) y encadenar
    hasta 37 de esas dejó el proceso bloqueado cerca de una hora, tumbando
    el resto del sitio para todo el mundo mientras tanto (usuarios en línea,
    tests en directo...). Aquí ya no bloquea nada.

    Dentro del lote se reparten las llamadas a Gemini con una pausa fija
    (GEMINI_ESPACIADO_SEGUNDOS) para no chocar con el límite de peticiones
    por minuto del plan gratuito, y si aun así llega un 429 "por minuto"
    (GeminiLimiteTemporalError, con el retryDelay que da la propia Gemini) se
    espera y se reintenta ESE candidato en vez de rendirse para el resto del
    lote -- solo se deja de intentar Gemini del todo si el fallo es de otro
    tipo (cupo diario agotado, clave inválida, Gemini caído), que no se
    arregla esperando un momento."""
    intentar_gemini = True
    ultimo_intento_gemini = 0.0
    con_ia = 0
    con_local = 0
    for candidato_id, recorte in recortes:
        try:
            extraidos, metodo = None, "local"
            if intentar_gemini:
                reintentos = 0
                while True:
                    espera = GEMINI_ESPACIADO_SEGUNDOS - (time.monotonic() - ultimo_intento_gemini)
                    if espera > 0:
                        time.sleep(espera)
                    ultimo_intento_gemini = time.monotonic()
                    try:
                        extraidos, metodo = cv_extraction.extraer_con_gemini(recorte), "gemini"
                        break
                    except cv_extraction.GeminiLimiteTemporalError as exc:
                        reintentos += 1
                        if reintentos > GEMINI_MAX_REINTENTOS_RPM:
                            break  # solo este candidato cae a local, el resto del lote sigue con Gemini
                        time.sleep(min(exc.retry_after_segundos, 90))
                    except (cv_extraction.GeminiNoConfiguradoError, cv_extraction.GeminiNoDisponibleError) as exc:
                        print(f"[adjuntar-pdf-lote] Gemini no disponible, resto del lote en local: {exc}")
                        intentar_gemini = False
                        break
            if metodo != "gemini":
                extraidos, metodo, _motivo = cv_extraction.extraer_cv(recorte, intentar_gemini=False)
            if metodo == "gemini":
                con_ia += 1
            else:
                con_local += 1
            if extraidos:
                reclutamiento_module.rellenar_huecos_candidato(candidato_id, extraidos[0])
        except Exception as exc:
            print(f"[adjuntar-pdf-lote] No se pudo rellenar huecos del candidato {candidato_id}: {exc}")
        finally:
            _progreso_lotes[lote_id]["procesados"] += 1
    _progreso_lotes[lote_id]["terminado"] = True

    total = len(recortes)
    if con_ia and con_local:
        resumen = f"{con_ia} con IA, {con_local} con método local"
    elif con_ia:
        resumen = "todos con IA"
    else:
        resumen = "todos con método local (Gemini no disponible)"
    notificaciones_module.crear_notificacion(
        usuario_id,
        f"Relleno de CVs terminado: {total}/{total} candidatos procesados ({resumen}).",
        "/compartidos.html",
    )


@router.post("/candidatos/adjuntar-pdf-lote/confirmar")
async def adjuntar_pdf_lote_confirmar_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mapeo: str = Form(...),
    user: dict = Depends(require_informes),
):
    """Recorta y adjunta -- recibe el PDF de lote UNA sola vez (en vez de
    subirlo N veces, una por candidato, como hacía antes el frontend) más la
    lista [{candidato_id, pagina_inicio, pagina_fin}] (rangos ya revisados o
    corregidos a mano en la vista previa). Si a algún candidato le falta el
    rango de páginas (detección no disponible para ese caso), se le adjunta
    el PDF completo -- mismo comportamiento que la herramienta original.

    Además, cuando SÍ hay un rango de páginas propio (un recorte limpio de
    una sola persona), se programa volver a extraer con IA y rellenar los
    huecos de la ficha (formación/experiencia estructuradas y cualquier otro
    campo vacío) como tarea en segundo plano -- así resubir el mismo PDF de
    lote sobre fichas que ya existían las deja al día sin tener que entrar
    una a una, y sin que la petición se quede esperando a la IA (ver
    _rellenar_huecos_en_segundo_plano). Nunca pisa datos que el reclutador
    ya haya rellenado (ver rellenar_huecos_candidato) ni crea fichas nuevas
    -- eso lo sigue haciendo solo la extracción original al subir el PDF por
    primera vez."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el PDF con todos los candidatos")
    try:
        items = json.loads(mapeo)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="mapeo inválido")
    contenido = await file.read()
    adjuntados = 0
    recortes_para_rellenar = []
    for item in items:
        candidato_id = item.get("candidato_id")
        if not candidato_id:
            continue
        pagina_inicio = item.get("pagina_inicio")
        pagina_fin = item.get("pagina_fin")
        recorte = contenido
        if pagina_inicio and pagina_fin:
            try:
                recorte = cv_extraction.recortar_pdf(contenido, int(pagina_inicio), int(pagina_fin))
            except Exception:
                recorte = contenido
        reclutamiento_module.agregar_archivo(candidato_id, file.filename, recorte)
        adjuntados += 1
        if pagina_inicio and pagina_fin:
            recortes_para_rellenar.append((candidato_id, recorte))
    lote_id = None
    if recortes_para_rellenar:
        lote_id = secrets.token_hex(8)
        _progreso_lotes[lote_id] = {"total": len(recortes_para_rellenar), "procesados": 0, "terminado": False}
        background_tasks.add_task(_rellenar_huecos_en_segundo_plano, lote_id, recortes_para_rellenar, user["id"])
    return {"ok": True, "adjuntados": adjuntados, "procesando_relleno": len(recortes_para_rellenar), "lote_id": lote_id}


@router.get("/candidatos/adjuntar-pdf-lote/progreso/{lote_id}")
def progreso_relleno_lote_route(lote_id: str, _user: dict = Depends(require_informes)):
    """Para que el frontend pueda sondear 'cuántos van' del relleno con IA en
    segundo plano (ver _rellenar_huecos_en_segundo_plano) -- 404 si el
    servidor se reinició desde entonces o el id no existe."""
    progreso = _progreso_lotes.get(lote_id)
    if progreso is None:
        raise HTTPException(status_code=404, detail="No hay ningún proceso en marcha con ese id")
    return progreso


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
        candidatos, metodo, motivo_local = cv_extraction.extraer_cv(contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not candidatos:
        raise HTTPException(status_code=422, detail="No se reconoció ningún candidato en este PDF")
    if len(candidatos) == 1:
        return {"ok": True, "metodo": metodo, "motivo_local": motivo_local, "candidato": candidatos[0], "de_lote": False}
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
    return {"ok": True, "metodo": metodo, "motivo_local": motivo_local, "candidato": encontrado, "de_lote": True}


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


@router.get("/candidatos/{candidato_id}/cv.pdf")
def cv_pdf_route(candidato_id: int, _user: dict = Depends(require_acceso_candidato)):
    """CV con diseño propio a partir de los datos ya extraídos (formación/
    experiencia estructuradas, foto, resto de campos) -- para tener algo
    presentable que descargar y compartir aparte de la ficha web."""
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    foto_ruta = reclutamiento_module.get_foto_ruta(candidato_id)
    pdf_bytes = cv_pdf.generar_cv_pdf(candidato, empresa=candidato.get("empresa", "kk"), foto_ruta=foto_ruta)
    nombre = f"cv_{(candidato.get('nombre_completo') or 'candidato').replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


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
