import json
import mimetypes
import os
import secrets
import threading
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
from utils import rows_to_xlsx

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
    archivada: bool | None = None


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


class ExportarExcelIn(BaseModel):
    candidato_ids: list[int]
    columnas: list[str]


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
def list_vacantes_route(
    empresa: str | None = None, estado: str | None = None, archivadas: bool = False,
    _user: dict = Depends(require_informes),
):
    return reclutamiento_module.list_vacantes(empresa=empresa, estado=estado, archivadas=archivadas)


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


@router.get("/candidatos/columnas-exportables")
def columnas_exportables_route(_user: dict = Depends(get_current_user)):
    return reclutamiento_module.CAMPOS_EXPORTABLES


@router.post("/candidatos/exportar-excel")
def exportar_excel_route(body: ExportarExcelIn, user: dict = Depends(get_current_user)):
    # A diferencia del resto de acciones en lote de "Base de candidatos"
    # (que exigen el módulo completo con require_informes), exportar debe
    # poder usarlo también quien solo tiene candidatos sueltos compartidos
    # (un gerente al que solo le comparten fichas, ver require_acceso_candidato)
    # -- así que en vez de bloquear a quien no tiene el módulo, se filtran en
    # silencio los ids a los que de verdad tiene acceso, y se exporta solo esos.
    if auth_module.tiene_modulo(user, "informes") or auth_module.tiene_modulo(user, "saona_informes"):
        candidato_ids = body.candidato_ids
    else:
        candidato_ids = [
            cid for cid in body.candidato_ids
            if reclutamiento_module.usuario_tiene_acceso_candidato(user["id"], cid)
        ]
    filas = reclutamiento_module.exportar_candidatos(candidato_ids, body.columnas)
    contenido = rows_to_xlsx(filas)
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=candidatos.xlsx"},
    )


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


@router.get("/candidatos/lotes-en-progreso")
def lotes_en_progreso_route(user: dict = Depends(get_current_user)):
    """Todos los lotes de relleno con IA en curso (no terminados) del usuario
    que pide la ruta -- alimenta el banner persistente del topbar (ver
    topbar-menu.js), visible en cualquier pantalla mientras algo sigue
    trabajando en segundo plano. Definida ANTES de /candidatos/{candidato_id}
    a propósito: FastAPI resuelve por orden de registro, así que si fuera
    después, "lotes-en-progreso" se colaría como candidato_id de esa otra
    ruta en vez de llegar aquí."""
    return [
        {"lote_id": lote_id, **p}
        for lote_id, p in _progreso_lotes.items()
        if p.get("usuario_id") == user["id"] and not p["terminado"]
    ]


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
async def extraer_cv_route(
    intentar_gemini: bool = True, file: UploadFile = File(...), _user: dict = Depends(require_informes)
):
    """intentar_gemini=False para una lectura local instantánea (sin esperar
    a la IA) -- el frontend la usa primero para saber cuántos candidatos trae
    el PDF: si es uno solo, repite la llamada con intentar_gemini=True (un
    único CV, la espera es corta) para la calidad de siempre; si son varios,
    crea las fichas ya mismo con estos datos locales y mejora cada una en
    segundo plano (ver adjuntar_pdf_lote_confirmar_route, que es quien de
    verdad hace ese enriquecido -- aquí solo se detectan los rangos de
    página de cada candidato para poder pedírselo después)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el CV en formato PDF")
    contenido = await file.read()
    try:
        candidatos, metodo, motivo_local = cv_extraction.extraer_cv(contenido, intentar_gemini=intentar_gemini)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    rangos = []
    if len(candidatos) > 1:
        try:
            rangos = cv_extraction.detectar_paginas_por_candidato(contenido)
        except Exception:
            rangos = []
    division_disponible = len(rangos) == len(candidatos)
    return {
        "ok": True, "metodo": metodo, "motivo_local": motivo_local, "candidatos": candidatos,
        "division_disponible": division_disponible,
        "rangos_paginas": rangos if division_disponible else None,
    }


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
    ya_enriquecidos = reclutamiento_module.candidatos_ya_enriquecidos(
        [it["candidato_id"] for it in resultado if it["candidato_id"]]
    )
    for it in resultado:
        it["ya_enriquecido"] = it["candidato_id"] in ya_enriquecidos
    return {
        "ok": True, "metodo": metodo, "motivo_local": motivo_local, "candidatos": resultado,
        "division_disponible": division_disponible, "total_paginas": len(rangos) if not division_disponible else None,
    }


# Progreso del relleno en segundo plano, en memoria -- solo es el indicador
# que sondea el frontend ("cuántos van"), así que un diccionario en memoria
# basta. El TRABAJO en sí (qué candidatos faltan) SÍ se conserva en disco
# (ver lotes_ia/lotes_ia_pendientes en reclutamiento.py): si el proceso se
# reinicia a media tanda, este diccionario se pierde pero
# reanudar_lotes_ia_pendientes lo reconstruye al arrancar con el total y lo
# ya hecho reales, y relanza el resto -- no hace falta que el usuario lo
# note ni que rehaga nada a mano.
_progreso_lotes: dict[str, dict] = {}


# Margen bajo el límite de 10 peticiones/minuto del plan gratuito de Gemini
# (ver GEMINI_MODEL en cv_extraction) -- con esto de por medio, un lote de 37
# candidatos tarda más en procesarse pero prácticamente no choca con el
# límite de RPM, así que casi todos acaban pasando por IA en vez de solo los
# primeros ~9 antes de que saltara el 429 (ver GeminiLimiteTemporalError).
GEMINI_ESPACIADO_SEGUNDOS = 7
GEMINI_MAX_REINTENTOS_RPM = 2


def _rellenar_huecos_en_segundo_plano(lote_id: str, items: list[tuple[int, int]], usuario_id: int, titulo: str):
    """Re-extrae con IA cada candidato pendiente y rellena huecos -- se
    ejecuta DESPUÉS de responder al navegador (ver BackgroundTasks en la
    ruta de abajo) o al arrancar el proceso si retoma un lote a medias (ver
    _reanudar_lotes_al_arrancar). Antes esto iba dentro de la propia
    petición: con Gemini saturado, cada llamada podía tardar hasta el
    timeout (ver cv_extraction) y encadenar hasta 37 de esas dejó el proceso
    bloqueado cerca de una hora, tumbando el resto del sitio para todo el
    mundo mientras tanto (usuarios en línea, tests en directo...). Aquí ya
    no bloquea nada.

    `items` son (candidato_id, archivo_id) -- se lee el PDF de disco en cada
    vuelta (ya lo dejó guardado agregar_archivo antes de programar esto) en
    vez de recibir los bytes por parámetro, precisamente para poder
    reconstruir la llamada desde cero si el proceso se reinició a media
    tanda: lo único que hace falta conservar es la cola en
    lotes_ia_pendientes (ver reclutamiento_module), no los bytes del PDF.

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
    inicio = time.monotonic()
    procesados_esta_tanda = 0
    for candidato_id, archivo_id in items:
        try:
            archivo = reclutamiento_module.get_archivo(archivo_id)
            if archivo is None or not os.path.exists(archivo["ruta"]):
                continue
            with open(archivo["ruta"], "rb") as f:
                recorte = f.read()
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
                # Se marca aunque Gemini no haya encontrado nada que rellenar
                # (candidato sin formación/experiencia real en su CV) -- lo
                # que importa aquí es que SÍ lo procesó, no si el resultado
                # tenía contenido (ver candidatos_ya_enriquecidos).
                reclutamiento_module.marcar_ia_extraida(candidato_id)
            else:
                con_local += 1
            if extraidos:
                reclutamiento_module.rellenar_huecos_candidato(candidato_id, extraidos[0])
        except Exception as exc:
            print(f"[adjuntar-pdf-lote] No se pudo rellenar huecos del candidato {candidato_id}: {exc}")
        finally:
            reclutamiento_module.marcar_candidato_lote_terminado(lote_id, candidato_id)
            procesados_esta_tanda += 1
            p = _progreso_lotes.get(lote_id)
            if p is not None:
                p["procesados"] += 1
                # Ritmo medio real de ESTA tanda (incluye esperas de espaciado y
                # reintentos) proyectado sobre lo que queda -- si el lote viene
                # retomado tras un reinicio, procesados_esta_tanda arranca en 0
                # aunque p["procesados"] ya venga con lo hecho antes, para no
                # calcular el ritmo como si lo de antes también hubiera
                # tardado lo de ahora.
                restantes = p["total"] - p["procesados"]
                p["eta_segundos"] = round((time.monotonic() - inicio) / procesados_esta_tanda * restantes) if restantes > 0 else 0
    p = _progreso_lotes.get(lote_id)
    if p is not None:
        p["terminado"] = True
        total = p["total"]
    else:
        total = len(items)

    if con_ia and con_local:
        resumen = f"{con_ia} con IA, {con_local} con método local"
    elif con_ia:
        resumen = "todos con IA"
    else:
        resumen = "todos con método local (Gemini no disponible)"
    notificaciones_module.crear_notificacion(
        usuario_id,
        f"{titulo}: relleno con IA terminado, {total}/{total} candidatos procesados ({resumen}).",
        "/compartidos.html",
    )


def reanudar_lotes_ia_pendientes():
    """Se llama al arrancar el proceso (ver el startup de main.py) --
    retoma cada lote de relleno con IA que se quedó a medias en el arranque
    anterior (redeploy, reinicio, caída...) en vez de dejarlo perdido para
    siempre. Reconstruye _progreso_lotes con el total real y lo ya
    procesado (no desde 0) para que el indicador del topbar no mienta, y
    lanza el resto en un hilo aparte -- fuera de una petición no hay
    BackgroundTasks de FastAPI que valga."""
    lotes = reclutamiento_module.lotes_ia_incompletos()
    for lote in lotes:
        ya_hechos = lote["total"] - len(lote["pendientes"])
        _progreso_lotes[lote["lote_id"]] = {
            "total": lote["total"], "procesados": ya_hechos, "terminado": False, "eta_segundos": None,
            "usuario_id": lote["usuario_id"], "titulo": lote["titulo"],
        }
        print(f"[adjuntar-pdf-lote] Retomando lote '{lote['titulo']}' ({ya_hechos}/{lote['total']} ya hechos, {len(lote['pendientes'])} pendientes)", flush=True)
        threading.Thread(
            target=_rellenar_huecos_en_segundo_plano,
            args=(lote["lote_id"], lote["pendientes"], lote["usuario_id"], lote["titulo"]),
            daemon=True,
        ).start()


@router.post("/candidatos/adjuntar-pdf-lote/confirmar")
async def adjuntar_pdf_lote_confirmar_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mapeo: str = Form(...),
    titulo: str | None = Form(None),
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
    items_para_rellenar = []
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
        archivo_id = reclutamiento_module.agregar_archivo(candidato_id, file.filename, recorte)
        adjuntados += 1
        if pagina_inicio and pagina_fin:
            items_para_rellenar.append((candidato_id, archivo_id))
    lote_id = None
    if items_para_rellenar:
        lote_id = secrets.token_hex(8)
        titulo_lote = titulo or "Relleno de CVs"
        _progreso_lotes[lote_id] = {
            "total": len(items_para_rellenar), "procesados": 0, "terminado": False, "eta_segundos": None,
            "usuario_id": user["id"], "titulo": titulo_lote,
        }
        # Cola durable ANTES de programar el segundo plano -- si el proceso
        # se reinicia (redeploy, caída...) antes o durante el lote,
        # _reanudar_lotes_al_arrancar lo retoma solo desde aquí sin perder
        # lo que ya se procesó.
        reclutamiento_module.crear_lote_ia_pendiente(lote_id, user["id"], titulo_lote, items_para_rellenar)
        background_tasks.add_task(_rellenar_huecos_en_segundo_plano, lote_id, items_para_rellenar, user["id"], titulo_lote)
    return {"ok": True, "adjuntados": adjuntados, "procesando_relleno": len(items_para_rellenar), "lote_id": lote_id}


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
    presentable que descargar y compartir aparte de la ficha web.

    Mientras la IA todavía no ha rellenado formación/experiencia
    estructuradas (ver candidatos_ya_enriquecidos), el nuestro sale
    prácticamente vacío -- en ese caso se sirve directamente el PDF original
    que se subió (el recorte de InfoJobs/lote), que sí tiene todo. En cuanto
    la IA lo enriquece, vuelve a servirse el nuestro. También se cae al
    original si generar el nuestro falla por lo que sea (dato inesperado de
    algún CV raro) -- mejor entregar el original que un error 500 sin CV
    ninguno."""
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")

    def _archivo_pdf_original():
        for archivo in candidato["archivos"]:
            if archivo["nombre_original"].lower().endswith(".pdf"):
                return reclutamiento_module.get_archivo(archivo["id"])
        return None

    ya_enriquecido = candidato_id in reclutamiento_module.candidatos_ya_enriquecidos([candidato_id])
    original = _archivo_pdf_original() if not ya_enriquecido else None
    if original is None:
        try:
            foto_ruta = reclutamiento_module.get_foto_ruta(candidato_id)
            pdf_bytes = cv_pdf.generar_cv_pdf(candidato, empresa=candidato.get("empresa", "kk"), foto_ruta=foto_ruta)
            nombre = f"cv_{(candidato.get('nombre_completo') or 'candidato').replace(' ', '_')}.pdf"
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
            )
        except Exception as exc:
            print(f"[cv.pdf] Fallo generando el CV propio del candidato {candidato_id}, se sirve el original si lo hay: {exc}")
            original = _archivo_pdf_original()
            if original is None:
                raise HTTPException(status_code=500, detail="No se pudo generar el CV") from exc
    return FileResponse(
        original["ruta"],
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{original["nombre_original"]}"'},
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
