import asyncio
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import threading
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import cv_extraction
import cv_pdf
import notificaciones as notificaciones_module
import reclutamiento as reclutamiento_module
from auth_routes import get_current_user, require_admin
from informes_routes import _exigir_dueno_del_compartido, require_informes_o_reclutamiento
from utils import rows_to_xlsx

router = APIRouter()


def _nombre_archivo_cv(candidato: dict) -> str:
    """Nombre de archivo para cualquier PDF que se descargue de la ficha de
    un candidato (el generado con diseño propio, el original subido...) --
    antes se servía tal cual el nombre del archivo original (a menudo el del
    lote entero, tipo "Krispy Kreme 37-cvs-18-08-2026.pdf", nada útil una
    vez descargado y guardado en el ordenador de quien lo pidió). Se arma
    como "CV Nombre Apellido Vacante" (el centro de la vacante si la tiene
    asignada, que es lo que más ayuda a diferenciar entre tiendas -- si no
    tiene centro se usa el puesto; sin vacante asignada se queda solo con el
    nombre)."""
    nombre = candidato.get("nombre_completo") or "Candidato"
    vacante = candidato.get("vacante_centro") or candidato.get("vacante_puesto") or ""
    base = f"CV {nombre} {vacante}".strip()
    base = re.sub(r'[\\/:*?"<>|]', "", base)
    base = re.sub(r"\s+", " ", base).strip()
    return f"{base}.pdf"


_MODULOS_RECLUTAMIENTO_TODOS = ("informes", "saona_informes", "reclutamiento", "saona_reclutamiento")


def _modulos_para_empresa(empresa: str | None) -> tuple[str, ...]:
    """KK y Saona tienen cada una su propio par de módulos (Informes +
    Reclutamiento) -- tener el de una marca no debe dar acceso a los datos
    de la otra. Si no se conoce la empresa (recurso inexistente), se cae al
    conjunto amplio para no convertir un 404 en un 403 confuso."""
    if empresa == "saona":
        return ("saona_informes", "saona_reclutamiento")
    if empresa == "kk":
        return ("informes", "reclutamiento")
    return _MODULOS_RECLUTAMIENTO_TODOS


def _exigir_modulo_empresa(empresa: str | None, user: dict) -> None:
    """Para rutas donde la empresa la manda el propio cliente (crear
    candidato/vacante, filtros y acciones en lote por empresa)."""
    if not any(auth_module.tiene_modulo(user, m) for m in _modulos_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Reclutamiento de esa empresa")


def require_acceso_candidato(candidato_id: int, user: dict = Depends(get_current_user)) -> dict:
    """A diferencia de require_informes_o_reclutamiento (para la sección
    propia de Reclutamiento), esto también deja pasar a quien no tiene
    ninguno de esos módulos pero SÍ recibió justo este candidato compartido
    — mismo espíritu que /informes/compartidos (get_current_user a secas)
    para que un gerente o area manager pueda abrir la ficha completa que le
    compartieron, no solo la tarjeta resumen. El módulo que vale es el de la
    empresa REAL del candidato, no "cualquiera de los cuatro" -- si no, KK y
    Saona se ven las fichas de la otra marca entre sí."""
    empresa = reclutamiento_module.get_empresa_candidato(candidato_id)
    if any(auth_module.tiene_modulo(user, m) for m in _modulos_para_empresa(empresa)):
        return user
    if reclutamiento_module.usuario_tiene_acceso_candidato(user["id"], candidato_id):
        return user
    raise HTTPException(status_code=403, detail="No tienes acceso a este candidato")


def require_modulo_candidato(candidato_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Como require_acceso_candidato pero SIN el atajo de "me lo compartieron
    a mí" -- para una acción que no debería quedar en manos de quien solo
    recibió esta ficha compartida (borrarla del todo)."""
    empresa = reclutamiento_module.get_empresa_candidato(candidato_id)
    _exigir_modulo_empresa(empresa, user)
    return user


def require_acceso_vacante(vacante_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Equivalente a require_acceso_candidato pero para una vacante entera
    (sin compartido directo, porque una vacante no se "comparte contigo",
    se comparte con un responsable ya con módulo -- ver compartir_vacante)."""
    empresa = reclutamiento_module.get_empresa_vacante(vacante_id)
    if any(auth_module.tiene_modulo(user, m) for m in _modulos_para_empresa(empresa)):
        return user
    raise HTTPException(status_code=403, detail="No tienes acceso a esta solicitud")


def _exigir_modulo_empresas_candidatos(candidato_ids: list[int], user: dict) -> None:
    """Para acciones en lote que reciben candidato_ids directamente y no
    filtran por empresa antes (a diferencia de _candidatos_accesibles, que
    deja pasar en silencio a quien solo tiene un compartido suelto): esto es
    para acciones que exigen el módulo completo, así que basta con exigir
    el módulo de CADA empresa real involucrada -- si alguno de los ids es
    de una empresa a la que este usuario no tiene acceso, 403 en bloque en
    vez de tocar solo los que sí puede (edición en lote no debería aplicarse
    a medias sin que quien lo pidió se entere)."""
    for empresa in set(reclutamiento_module.get_empresas_candidatos(candidato_ids).values()):
        _exigir_modulo_empresa(empresa, user)


def _candidatos_accesibles(user: dict, candidato_ids: list[int]) -> list[int]:
    """Mismo criterio que require_acceso_candidato pero para una LISTA de
    ids de golpe (acciones en lote: exportar Excel, descargar PDFs...) --
    quien tiene el módulo de la empresa de ESE candidato pasa; quien no, se
    queda solo con los que de verdad le compartieron (en vez de un 403 en
    bloque, que le bloquearía también los que sí puede ver)."""
    empresas = reclutamiento_module.get_empresas_candidatos(candidato_ids)
    con_modulo, resto = [], []
    for cid in candidato_ids:
        if any(auth_module.tiene_modulo(user, m) for m in _modulos_para_empresa(empresas.get(cid))):
            con_modulo.append(cid)
        else:
            resto.append(cid)
    compartidos = [cid for cid in resto if reclutamiento_module.usuario_tiene_acceso_candidato(user["id"], cid)]
    orden = {cid: i for i, cid in enumerate(candidato_ids)}
    return sorted(con_modulo + compartidos, key=lambda cid: orden[cid])


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


class ReextraerTodosIn(BaseModel):
    candidato_ids: list[int]


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
    user: dict = Depends(require_informes_o_reclutamiento),
):
    # Sin esto, tener el módulo de UNA marca bastaba para listar (y leer) las
    # vacantes de la otra con solo cambiar el parámetro `empresa` -- ver
    # crear_vacante_route más abajo, que sí lo exige desde siempre.
    if empresa:
        _exigir_modulo_empresa(empresa, user)
    return reclutamiento_module.list_vacantes(empresa=empresa, estado=estado, archivadas=archivadas)


@router.get("/vacantes/{vacante_id}")
def get_vacante_route(vacante_id: int, _user: dict = Depends(require_acceso_vacante)):
    vacante = reclutamiento_module.get_vacante(vacante_id)
    if vacante is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    return vacante


@router.post("/vacantes")
def crear_vacante_route(body: VacanteIn, user: dict = Depends(require_informes_o_reclutamiento)):
    _exigir_modulo_empresa(body.empresa, user)
    vacante_id = reclutamiento_module.crear_vacante(
        body.empresa, body.puesto, centro=body.centro, notas=body.notas, creado_por=user["username"]
    )
    return {"ok": True, "id": vacante_id}


@router.put("/vacantes/{vacante_id}")
def actualizar_vacante_route(vacante_id: int, body: VacanteUpdateIn, _user: dict = Depends(require_acceso_vacante)):
    if reclutamiento_module.get_vacante(vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    if body.estado is not None and body.estado not in reclutamiento_module.VACANTE_ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.estado}")
    campos = {k: v for k, v in body.model_dump().items() if v is not None}
    reclutamiento_module.actualizar_vacante(vacante_id, campos)
    return {"ok": True}


@router.delete("/vacantes/{vacante_id}")
def eliminar_vacante_route(vacante_id: int, _user: dict = Depends(require_admin)):
    if reclutamiento_module.get_vacante(vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    reclutamiento_module.eliminar_vacante(vacante_id)
    return {"ok": True}


class FusionarVacanteIn(BaseModel):
    destino_id: int


@router.post("/vacantes/{vacante_id}/fusionar")
def fusionar_vacantes_route(vacante_id: int, body: FusionarVacanteIn, _user: dict = Depends(require_admin)):
    empresa_origen = reclutamiento_module.get_empresa_vacante(vacante_id)
    empresa_destino = reclutamiento_module.get_empresa_vacante(body.destino_id)
    if empresa_origen is None or empresa_destino is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    if vacante_id == body.destino_id:
        raise HTTPException(status_code=400, detail="Elige una solicitud distinta como destino")
    if empresa_origen != empresa_destino:
        raise HTTPException(status_code=400, detail="Solo se pueden fusionar solicitudes de la misma empresa")
    reclutamiento_module.fusionar_vacantes(vacante_id, body.destino_id)
    return {"ok": True}


class CompartirVacanteIn(BaseModel):
    usuario_ids: list[int]


@router.post("/vacantes/{vacante_id}/compartir")
def compartir_vacante_route(vacante_id: int, body: CompartirVacanteIn, user: dict = Depends(require_admin)):
    """Asigna uno o más gerentes/responsables a TODA la solicitud -- a
    diferencia de /candidatos/compartir (candidato a candidato), esto da
    acceso a todos sus candidatos de una vez, presentes y futuros. Solo
    admin (pedido explícito del usuario): a diferencia de compartir un
    candidato suelto (que puede hacer cualquier responsable, para cubrirse
    entre gerentes), gestionar quién es responsable de una solicitud entera
    es una decisión de más peso -- afecta a todos sus candidatos, presentes
    y futuros."""
    if reclutamiento_module.get_vacante(vacante_id) is None:
        raise HTTPException(status_code=404, detail="Vacante no encontrada")
    for usuario_id in body.usuario_ids:
        if not auth_module.usuario_existe(usuario_id):
            raise HTTPException(status_code=404, detail=f"Usuario no encontrado: {usuario_id}")
    reclutamiento_module.compartir_vacante(vacante_id, body.usuario_ids, user["username"])
    return {"ok": True}


@router.delete("/vacantes/{vacante_id}/compartir/{usuario_id}")
def dejar_de_compartir_vacante_route(vacante_id: int, usuario_id: int, _user: dict = Depends(require_admin)):
    reclutamiento_module.dejar_de_compartir_vacante(vacante_id, usuario_id)
    return {"ok": True}


def _ve_todo_lo_compartido(user: dict) -> bool:
    """Area Manager y Director de Operaciones están por encima de los
    gerentes en la jerarquía -- si un gerente no atendió algo compartido, son
    ellos quienes tienen que verlo para darle seguimiento, así que ven TODO
    lo compartido en la empresa, no solo lo compartido con ellos en concreto
    (pedido explícito del usuario: "area manager esta encima de los
    gerentes... si un gerente no ha hecho algo el que jala las orejas es el
    area o el director de operaciones")."""
    return user["rol"] in ("area_manager", "director_operaciones")


def _empresa_de_usuario(user: dict) -> str | None:
    """Empresa (kk/saona) a la que pertenece este usuario según sus módulos
    (mismo criterio que empresaDeUsuario() en usuarios.js: cualquier módulo
    saona_* lo marca como Saona) -- None si tiene de las dos marcas o de
    ninguna (ambiguo, no se fuerza nada). Para forzar el filtro de empresa
    de _ve_todo_lo_compartido: quien NO tiene el módulo completo de Informes
    (la inmensa mayoría de gerentes/area managers, que solo ven
    "Compartidos") entra a esta pantalla SIN filtro de empresa a propósito
    (ver compartidos.js, esUsuarioRestringido) para no perder de vista algo
    compartido de la otra marca -- pero eso significa "ver todo lo
    compartido de la empresa" (todas=True) se volvería "ver todo lo
    compartido de LAS DOS empresas" para ellos, que es justo lo que no
    queremos: un area manager de Saona (p.ej. Samuel, que solo tiene
    saona_clima) no debe ver vacantes de Krispy Kreme.

    OJO: `user` (de get_current_user) es la fila cruda de `usuarios` -- los
    módulos viven en otra tabla (usuario_modulos) y solo se juntan a mano en
    sitios como /auth/me, NO vienen en este dict. Hay que pedirlos aparte."""
    modulos = auth_module.get_modulos_permitidos(user["id"])
    tiene_saona = any(m.startswith("saona_") for m in modulos)
    tiene_kk = any(not m.startswith("saona_") for m in modulos)
    if tiene_saona and not tiene_kk:
        return "saona"
    if tiene_kk and not tiene_saona:
        return "kk"
    return None


def _todas_efectivo(user: dict, empresa: str | None) -> tuple[bool, str | None]:
    """Envuelve _ve_todo_lo_compartido/_empresa_de_usuario con una salvedad
    (hallazgo de QA): _empresa_de_usuario devuelve None tanto para quien
    tiene módulos de LAS DOS marcas (caso legítimo, se deja ver todo sin
    filtrar) como para quien no tiene NINGÚN módulo de Informes/Reclutamiento
    (cuenta mal configurada -- p.ej. se le quitaron los módulos sin bajarle
    el rol) -- para este segundo caso, forzar todas=True sin poder acotar la
    empresa filtraría por las DOS marcas a la vez para alguien que en
    realidad no debería ver ninguna, así que se cae a todas=False (solo lo
    compartido con él en concreto, que en la práctica será nada)."""
    todas = _ve_todo_lo_compartido(user)
    if not todas or empresa:
        return todas, empresa
    empresa_forzada = _empresa_de_usuario(user)
    if empresa_forzada:
        return todas, empresa_forzada
    if auth_module.get_modulos_permitidos(user["id"]):
        return todas, None  # tiene de las dos marcas -- caso legítimo, sin filtrar
    return False, None  # no tiene ningún módulo -- no forzar "ver todo"


@router.get("/vacantes-compartidas-conmigo")
def vacantes_compartidas_conmigo_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    """Igual que /candidatos/compartir a nivel de solicitud: vacantes de las
    que este usuario es responsable, con TODOS sus candidatos juntos --
    accesible sin el módulo completo, igual que /informes/compartidos."""
    todas, empresa = _todas_efectivo(user, empresa)
    return reclutamiento_module.get_vacantes_compartidas_con(user["id"], empresa=empresa, todas=todas)


@router.get("/vacantes-compartidas-por-mi")
def vacantes_compartidas_por_mi_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    return reclutamiento_module.get_vacantes_compartidas_por(user["username"], empresa=empresa)


@router.get("/candidatos/compartidos-conmigo")
def candidatos_compartidos_conmigo_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    """Todos los candidatos a los que este usuario tiene acceso, por
    cualquiera de las tres vías de compartir (directo, vía Informes, o
    vacante entera) -- una única lista, para que "Compartidos" en
    Reclutamiento sea una sola pantalla en vez de dos con formato distinto.
    Accesible sin el módulo completo, igual que /vacantes-compartidas-conmigo."""
    todas, empresa = _todas_efectivo(user, empresa)
    return reclutamiento_module.candidatos_compartidos_con(user["id"], empresa=empresa, todas=todas)


@router.get("/candidatos/compartidos-por-mi")
def candidatos_compartidos_por_mi_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    """Espejo de candidatos_compartidos_conmigo_route para el lado de quien
    comparte -- une "Solicitudes que has compartido" y "Compartidos por ti"
    en una sola lista de fichas completas."""
    return reclutamiento_module.candidatos_compartidos_por(user["username"], empresa=empresa)


@router.get("/candidatos")
def list_candidatos_route(
    empresa: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    vacante_id: int | None = None,
    sin_vacante: bool = False,
    user: dict = Depends(require_informes_o_reclutamiento),
):
    # Tener el módulo de UNA marca bastaba para listar/buscar candidatos de
    # la otra con solo cambiar `empresa` (o dejarlo vacío -- ver
    # list_vacantes_route más arriba, mismo motivo).
    if empresa:
        _exigir_modulo_empresa(empresa, user)
    return reclutamiento_module.list_candidatos(empresa=empresa, estado=estado, q=q, vacante_id=vacante_id, sin_vacante=sin_vacante)


@router.get("/candidatos/descartados-antiguos")
def descartados_antiguos_route(meses: int = 12, _user: dict = Depends(require_informes_o_reclutamiento)):
    return reclutamiento_module.candidatos_descartados_antiguos(meses)


@router.post("/candidatos/purgar-descartados")
def purgar_descartados_route(meses: int = 12, user: dict = Depends(require_informes_o_reclutamiento)):
    borrados = reclutamiento_module.purgar_descartados(meses)
    return {"ok": True, "borrados": borrados}


@router.post("/candidatos/revincular-tests")
def revincular_candidatos_route(user: dict = Depends(require_informes_o_reclutamiento)):
    enlazados = reclutamiento_module.revincular_candidatos_existentes()
    return {"ok": True, "enlazados": enlazados}


@router.get("/candidatos/conteo-por-estado")
def conteo_por_estado_route(
    empresa: str | None = None,
    q: str | None = None,
    vacante_id: int | None = None,
    sin_vacante: bool = False,
    user: dict = Depends(require_informes_o_reclutamiento),
):
    if empresa:
        _exigir_modulo_empresa(empresa, user)
    return reclutamiento_module.contar_por_estado(empresa=empresa, q=q, vacante_id=vacante_id, sin_vacante=sin_vacante)


@router.put("/candidatos/estado-multiple")
def actualizar_estado_multiple_route(body: EstadoMultipleIn, user: dict = Depends(require_informes_o_reclutamiento)):
    if body.estado not in reclutamiento_module.ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.estado}")
    _exigir_modulo_empresas_candidatos(body.candidato_ids, user)
    reclutamiento_module.actualizar_estado_multiple(body.candidato_ids, body.estado)
    return {"ok": True}


@router.put("/candidatos/vacante-multiple")
def actualizar_vacante_multiple_route(body: VacanteMultipleIn, user: dict = Depends(require_informes_o_reclutamiento)):
    if body.vacante_id is not None:
        empresa_vacante = reclutamiento_module.get_empresa_vacante(body.vacante_id)
        if empresa_vacante is None:
            raise HTTPException(status_code=404, detail="Vacante no encontrada")
        _exigir_modulo_empresa(empresa_vacante, user)
        empresas_candidatos = reclutamiento_module.get_empresas_candidatos(body.candidato_ids)
        if any(e != empresa_vacante for e in empresas_candidatos.values()):
            raise HTTPException(status_code=400, detail="Solo se pueden asignar candidatos de la misma empresa que la solicitud")
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
    candidato_ids = _candidatos_accesibles(user, body.candidato_ids)
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
def marcar_invitados_test_route(body: MarcarInvitadosTestIn, user: dict = Depends(require_informes_o_reclutamiento)):
    _exigir_modulo_empresas_candidatos(body.candidato_ids, user)
    reclutamiento_module.marcar_invitados_test(body.candidato_ids, body.encuesta_id)
    return {"ok": True}


@router.post("/candidatos/compartir")
def compartir_candidatos_route(body: CompartirCandidatosIn, user: dict = Depends(get_current_user)):
    """Ya no exige el módulo completo -- un gerente responsable de una
    vacante (o al que le compartieron un candidato suelto) también puede
    compartirlo con otro gerente, p.ej. para cubrirse mutuamente. Se filtra
    con _candidatos_accesibles para que solo pueda compartir candidatos a
    los que él mismo tiene acceso, nunca cualquiera de la base entera.

    Compartir directo es EXCLUSIVO (ver compartir_candidatos_directo): quita
    el acceso a quien lo tuviera antes. Por eso, de los ya accesibles, se
    descartan en silencio los que ya tiene compartido DIRECTAMENTE otra
    persona (ver get_dueno_compartido_directo) -- si no, cualquiera con
    acceso podría "robarle" a un compañero un candidato que él ya compartió
    con un tercero, sin su permiso."""
    if not auth_module.usuario_existe(body.usuario_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    ids_accesibles = _candidatos_accesibles(user, body.candidato_ids)
    es_admin = user.get("rol") == "admin"
    ids_permitidos = ids_accesibles if es_admin else [
        cid for cid in ids_accesibles
        if (dueno := reclutamiento_module.get_dueno_compartido_directo(cid)) is None or dueno == user["username"]
    ]
    if not ids_permitidos:
        detalle = "No tienes acceso a ninguno de estos candidatos" if not ids_accesibles else \
            "Ya están compartidos directamente por otra persona -- solo quien los compartió (o un admin) puede reasignarlos"
        raise HTTPException(status_code=403, detail=detalle)
    reclutamiento_module.compartir_candidatos_directo(ids_permitidos, body.usuario_id, user["username"])
    return {"ok": True, "compartidos": len(ids_permitidos)}


@router.delete("/candidatos/{candidato_id}/compartir/{usuario_id}")
def dejar_de_compartir_candidato_route(candidato_id: int, usuario_id: int, user: dict = Depends(require_informes_o_reclutamiento)):
    _exigir_dueno_del_compartido(reclutamiento_module.get_candidato_compartido_por(candidato_id, usuario_id), user)
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


@router.get("/candidatos/fotos-duplicadas")
def fotos_duplicadas_route(empresa: str = "kk", user: dict = Depends(require_informes_o_reclutamiento)):
    """Diagnóstico de solo lectura: agrupa a todos los candidatos con foto
    por el CONTENIDO real del archivo (hash), no por si su PDF vuelve a
    analizarse como una o varias personas -- esa segunda vía es la que usa
    limpiar_fotos_de_lote_compartido_route, y depende de que el PDF más
    reciente adjunto a la ficha siga siendo el mismo de cuando se generó el
    problema; si alguien subió un CV nuevo después, o el re-análisis ya no
    coincide, una foto ajena podría colarse sin que esa limpieza la detecte.
    Aquí no: dos candidatos DISTINTOS con el byte a byte la misma foto es en
    la práctica imposible que sea casualidad (dos personas no suben la
    misma imagen exacta), así que cualquier grupo de 2+ aquí es foto
    compartida por error, sin excepción. No borra nada, solo informa.

    Definida ANTES de /candidatos/{candidato_id} a propósito -- mismo motivo
    que /candidatos/lotes-en-progreso un poco más arriba: si fuera después,
    "fotos-duplicadas" se colaría como candidato_id de esa otra ruta."""
    _exigir_modulo_empresa(empresa, user)
    candidatos = reclutamiento_module.candidatos_con_foto(empresa=empresa)
    por_hash: dict[str, list[dict]] = {}
    sin_archivo = []
    for c in candidatos:
        ruta = c["foto_ruta"]
        if not ruta or not os.path.exists(ruta):
            sin_archivo.append({"id": c["id"], "nombre": c["nombre_completo"]})
            continue
        with open(ruta, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        por_hash.setdefault(digest, []).append({"id": c["id"], "nombre": c["nombre_completo"]})
    grupos_duplicados = [grupo for grupo in por_hash.values() if len(grupo) > 1]
    return {
        "ok": True,
        "total_con_foto": len(candidatos),
        "grupos_duplicados": grupos_duplicados,
        "candidatos_afectados": sum(len(g) for g in grupos_duplicados),
        "sin_archivo_en_disco": sin_archivo,
    }


@router.get("/candidatos/{candidato_id}")
def get_candidato_route(candidato_id: int, _user: dict = Depends(require_acceso_candidato)):
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    return candidato


@router.post("/candidatos")
def crear_candidato_route(body: CandidatoIn, user: dict = Depends(require_informes_o_reclutamiento)):
    _exigir_modulo_empresa(body.empresa, user)
    if body.vacante_id is not None:
        empresa_vacante = reclutamiento_module.get_empresa_vacante(body.vacante_id)
        if empresa_vacante is None:
            raise HTTPException(status_code=404, detail="Vacante no encontrada")
        if empresa_vacante != body.empresa:
            raise HTTPException(status_code=400, detail="Esa vacante es de otra empresa")
    campos = body.model_dump(exclude={"empresa", "vacante_id"})
    candidato_id = reclutamiento_module.crear_candidato(
        campos, empresa=body.empresa, origen="manual", creado_por=user["username"], vacante_id=body.vacante_id
    )
    return {"ok": True, "id": candidato_id}


_CAMPOS_EDITABLES_SIN_MODULO = ("notas", "contacto_estado")


@router.put("/candidatos/{candidato_id}")
def actualizar_candidato_route(candidato_id: int, body: CandidatoUpdateIn, user: dict = Depends(require_acceso_candidato)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if body.estado is not None and body.estado not in reclutamiento_module.ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.estado}")
    if body.contacto_estado is not None and body.contacto_estado not in reclutamiento_module.CONTACTO_ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado de contacto inválido: {body.contacto_estado}")
    if body.vacante_id is not None:
        empresa_vacante = reclutamiento_module.get_empresa_vacante(body.vacante_id)
        if empresa_vacante is None:
            raise HTTPException(status_code=404, detail="Vacante no encontrada")
        if empresa_vacante != reclutamiento_module.get_empresa_candidato(candidato_id):
            raise HTTPException(status_code=400, detail="Esa vacante es de otra empresa")
    # exclude_unset (no "filtrar los None") para poder distinguir "el cliente
    # no mandó este campo, no lo toques" de "el cliente mandó explícitamente
    # null" — necesario para poder desasignar vacante_id (null explícito) sin
    # que las actualizaciones parciales de estado/notas desde "Compartidos"
    # (que no incluyen vacante_id en absoluto) lo desasignen sin querer.
    campos = body.model_dump(exclude_unset=True)
    empresa = reclutamiento_module.get_empresa_candidato(candidato_id)
    tiene_modulo_completo = any(auth_module.tiene_modulo(user, m) for m in _modulos_para_empresa(empresa))
    if not tiene_modulo_completo:
        # A quien solo le compartieron esta ficha (sin el módulo) se le deja
        # anotar seguimiento (notas, estado del contacto), pero no tocar los
        # datos del candidato en sí (nombre, teléfono, vacante, DNI...) --
        # se ignoran esos campos en vez de dar error, porque el mismo
        # formulario de la ficha los sigue mandando aunque no se hayan
        # tocado (ver frontend/js/compartidos.js, guardarCandidato).
        campos = {k: v for k, v in campos.items() if k in _CAMPOS_EDITABLES_SIN_MODULO}
    reclutamiento_module.actualizar_candidato(candidato_id, campos)
    return {"ok": True}


@router.delete("/candidatos/{candidato_id}")
def eliminar_candidato_route(candidato_id: int, _user: dict = Depends(require_admin)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    reclutamiento_module.eliminar_candidato(candidato_id)
    return {"ok": True}


@router.post("/candidatos/extraer-cv")
async def extraer_cv_route(file: UploadFile = File(...), _user: dict = Depends(require_informes_o_reclutamiento)):
    """Lee un CV nuevo (sin guardarlo todavía) con el método local -- el
    frontend rellena el formulario con el resultado para que el reclutador
    lo revise antes de guardar. Si trae varios candidatos concatenados (PDF
    por lotes), aquí solo se detectan los rangos de página de cada uno para
    poder recortarlos después (ver adjuntar_pdf_lote_confirmar_route, que es
    quien de verdad crea/rellena cada ficha)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el CV en formato PDF")
    contenido = await file.read()
    try:
        # asyncio.to_thread: extraer_cv es una función normal (bloqueante,
        # de CPU) llamada dentro de una ruta async -- sin esto, mientras lee
        # un PDF grande deja colgado el único hilo que atiende TODAS las
        # peticiones de la app, no solo la de quien subió el archivo (ya
        # pasó en producción con un patrón parecido, ver reextraer_todos_route
        # más abajo). Corriéndolo en otro hilo, quien sube el PDF sigue
        # esperando su propia respuesta igual, pero deja de bloquear a todo
        # el mundo mientras tanto.
        candidatos = await asyncio.to_thread(cv_extraction.extraer_cv, contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    rangos = []
    if len(candidatos) > 1:
        try:
            rangos = await asyncio.to_thread(cv_extraction.detectar_paginas_por_candidato, contenido)
        except Exception:
            rangos = []
    division_disponible = len(rangos) == len(candidatos)
    return {
        "ok": True, "candidatos": candidatos,
        "division_disponible": division_disponible,
        "rangos_paginas": rangos if division_disponible else None,
    }


@router.post("/candidatos/adjuntar-pdf-lote")
async def adjuntar_pdf_lote_route(empresa: str = "kk", file: UploadFile = File(...), user: dict = Depends(require_informes_o_reclutamiento)):
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
    _exigir_modulo_empresa(empresa, user)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sube el PDF con todos los candidatos")
    contenido = await file.read()
    try:
        # Ver el mismo comentario en extraer_cv_route -- esto puede ser un
        # PDF de hasta ~50 candidatos, el caso donde más tarda y más
        # importa no bloquear al resto de la app mientras se procesa.
        candidatos = await asyncio.to_thread(cv_extraction.extraer_cv, contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    try:
        rangos = await asyncio.to_thread(cv_extraction.detectar_paginas_por_candidato, contenido)
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
        "ok": True, "candidatos": resultado,
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


def _rellenar_huecos_en_segundo_plano(lote_id: str, items: list[tuple[int, int]], usuario_id: int, titulo: str):
    """Re-extrae cada candidato pendiente con el método local y rellena
    huecos -- se ejecuta en un hilo aparte DESPUÉS de responder al navegador
    (ver _lanzar_relleno más abajo), tanto recién subido el PDF como al
    retomar un lote a medias (ver reanudar_lotes_ia_pendientes). Va todo en
    segundo plano para no bloquear la petición: un lote de decenas de
    candidatos tarda un rato incluso siendo instantáneo cada uno.

    `items` son (candidato_id, archivo_id) -- se lee el PDF de disco en cada
    vuelta (ya lo dejó guardado agregar_archivo antes de programar esto) en
    vez de recibir los bytes por parámetro, precisamente para poder
    reconstruir la llamada desde cero si el proceso se reinició a media
    tanda: lo único que hace falta conservar es la cola en
    lotes_ia_pendientes (ver reclutamiento_module), no los bytes del PDF."""
    inicio = time.monotonic()
    procesados_esta_tanda = 0
    for candidato_id, archivo_id in items:
        try:
            archivo = reclutamiento_module.get_archivo(archivo_id)
            if archivo is None or not os.path.exists(archivo["ruta"]):
                reclutamiento_module.marcar_candidato_lote_terminado(lote_id, candidato_id)
                continue
            with open(archivo["ruta"], "rb") as f:
                recorte = f.read()
            extraidos = cv_extraction.extraer_cv(recorte)
            reclutamiento_module.marcar_ia_extraida(candidato_id)
            if extraidos:
                reclutamiento_module.rellenar_huecos_candidato(candidato_id, extraidos[0])
            # Foto de perfil: igual que al subir un CV suelto (ver
            # guardarCandidato en compartidos.js) o al pulsar "Re-extraer" a
            # mano en una ficha -- antes esto SOLO pasaba en esos dos casos,
            # nunca aquí, así que ningún candidato creado en lote sacaba foto
            # hasta que alguien entraba a su ficha y la pedía a mano. Cuando
            # este bucle viene de adjuntar_pdf_lote_confirmar_route, `recorte`
            # YA es el PDF individual de este candidato -- pero cuando viene
            # de reextraer_todos_route, candidatos_con_pdf() puede devolver
            # el PDF del LOTE ENTERO tal cual (fichas antiguas de antes de
            # que existiera el recorte por candidato, o casos sin división
            # de páginas disponible), compartido por varios candidatos. Sacar
            # "la foto de la página 1" de un PDF así le pone a TODOS esos
            # candidatos la foto de quien sea que salga primero en el lote
            # (bug real, visto en producción: la misma cara repetida en
            # decenas de fichas). len(extraidos) == 1 es la misma condición
            # que ya usa el botón manual "Re-extraer" (ver de_lote en
            # reextraerCv, compartidos.js) para decidir esto mismo -- solo se
            # saca la foto cuando el PDF adjunto es, de verdad, el de una
            # sola persona. Solo si todavía no tiene, para no pisar una que
            # el reclutador haya subido o cambiado a mano mientras el lote
            # seguía procesando.
            if len(extraidos) == 1 and not reclutamiento_module.get_foto_ruta(candidato_id):
                foto = cv_extraction.extraer_foto(recorte)
                if foto is not None:
                    datos_foto, ext_foto = foto
                    reclutamiento_module.guardar_foto(candidato_id, datos_foto, ext_foto)
            reclutamiento_module.marcar_candidato_lote_terminado(lote_id, candidato_id)
        except Exception as exc:
            # Error real de ESTE candidato (PDF corrupto, lo que sea) -- se
            # da por perdido y se sigue con el resto.
            print(f"[adjuntar-pdf-lote] No se pudo rellenar huecos del candidato {candidato_id}: {exc}")
            reclutamiento_module.marcar_candidato_lote_terminado(lote_id, candidato_id)
        finally:
            procesados_esta_tanda += 1
            p = _progreso_lotes.get(lote_id)
            if p is not None:
                p["procesados"] += 1
                # Ritmo medio real de ESTA tanda proyectado sobre lo que queda -- si
                # el lote viene retomado tras un reinicio, procesados_esta_tanda
                # arranca en 0 aunque p["procesados"] ya venga con lo hecho antes,
                # para no calcular el ritmo como si lo de antes también hubiera
                # tardado lo de ahora.
                restantes = p["total"] - p["procesados"]
                p["eta_segundos"] = round((time.monotonic() - inicio) / procesados_esta_tanda * restantes) if restantes > 0 else 0

    p = _progreso_lotes.get(lote_id)
    if p is not None:
        p["terminado"] = True
        total = p["total"]
    else:
        total = len(items)

    notificaciones_module.crear_notificacion(
        usuario_id,
        f"{titulo}: relleno terminado, {total}/{total} candidatos procesados.",
        "/compartidos.html",
    )


# lote_id de cualquier lote que tenga YA un hilo/tarea corriendo -- evita que
# reanudar_lotes_ia_pendientes() (llamado al arrancar) lance una segunda
# pasada duplicada sobre el mismo lote si la anterior todavía no ha terminado.
_lotes_en_ejecucion: set[str] = set()


def _lanzar_relleno(lote_id: str, items: list[tuple[int, int]], usuario_id: int, titulo: str):
    if lote_id in _lotes_en_ejecucion:
        return
    _lotes_en_ejecucion.add(lote_id)

    def _run():
        try:
            _rellenar_huecos_en_segundo_plano(lote_id, items, usuario_id, titulo)
        finally:
            _lotes_en_ejecucion.discard(lote_id)

    threading.Thread(target=_run, daemon=True).start()


def reanudar_lotes_ia_pendientes():
    """Retoma cada lote de relleno que se quedó a medias -- se llama al
    arrancar el proceso (ver el startup de main.py) para que un
    redeploy/reinicio a media tanda no pierda el trabajo. Reconstruye
    _progreso_lotes con el total real y lo ya procesado (no desde 0) para
    que el indicador del topbar no mienta."""
    lotes = reclutamiento_module.lotes_ia_incompletos()
    for lote in lotes:
        if lote["lote_id"] in _lotes_en_ejecucion:
            continue
        ya_hechos = lote["total"] - len(lote["pendientes"])
        _progreso_lotes[lote["lote_id"]] = {
            "total": lote["total"], "procesados": ya_hechos, "terminado": False, "eta_segundos": None,
            "usuario_id": lote["usuario_id"], "titulo": lote["titulo"],
        }
        print(f"[adjuntar-pdf-lote] Retomando lote '{lote['titulo']}' ({ya_hechos}/{lote['total']} ya hechos, {len(lote['pendientes'])} pendientes)", flush=True)
        _lanzar_relleno(lote["lote_id"], lote["pendientes"], lote["usuario_id"], lote["titulo"])


@router.post("/candidatos/reextraer-todos")
def reextraer_todos_route(
    body: ReextraerTodosIn, empresa: str = "kk", user: dict = Depends(require_informes_o_reclutamiento)
):
    """Vuelve a extraer con el método local el PDF YA guardado de cada
    candidato que tenga uno -- para cuando una mejora del extractor local
    (ver cv_extraction.py) deja desactualizadas fichas que se procesaron
    antes del arreglo, sin tener que volver a subir el PDF de lote original
    ni entrar ficha a ficha con "Re-extraer". Reutiliza exactamente
    la misma cola durable y el mismo mecanismo de progreso/notificación que
    /candidatos/adjuntar-pdf-lote/confirmar (ver _rellenar_huecos_en_segundo_plano)
    -- el banner del topbar y el aviso final al terminar funcionan igual sin
    nada especial aquí.

    `body.candidato_ids` limita esto a los candidatos que la pantalla tiene
    filtrados en ese momento (ver reextraerTodosLocal, compartidos.js) --
    antes se re-extraía SIEMPRE a todo el mundo, algo que con miles de
    candidatos sería carísimo cada vez que hiciera falta corregir solo un
    puñado recién importado."""
    _exigir_modulo_empresa(empresa, user)
    items = reclutamiento_module.candidatos_con_pdf(empresa=empresa, candidato_ids=body.candidato_ids)
    if not items:
        return {"ok": True, "lote_id": None, "total": 0}
    lote_id = secrets.token_hex(8)
    titulo_lote = f"Re-extracción de {len(items)} candidato(s) filtrados"
    _progreso_lotes[lote_id] = {
        "total": len(items), "procesados": 0, "terminado": False, "eta_segundos": None,
        "usuario_id": user["id"], "titulo": titulo_lote,
    }
    reclutamiento_module.crear_lote_ia_pendiente(lote_id, user["id"], titulo_lote, items)
    _lanzar_relleno(lote_id, items, user["id"], titulo_lote)
    return {"ok": True, "lote_id": lote_id, "total": len(items)}


_limpiezas_fotos: dict[str, dict] = {}


def _limpiar_fotos_en_segundo_plano(limpieza_id: str, items: list[tuple[int, int]], usuario_id: int):
    """Ver limpiar_fotos_de_lote_compartido_route -- separado en su propio
    hilo por la misma razón que _rellenar_huecos_en_segundo_plano: releer y
    re-analizar un PDF por candidato (pdfplumber, no es instantáneo) para
    decenas de candidatos de golpe, SÍNCRONO dentro de la petición HTTP,
    bloqueó el único worker de la app entera durante más de un minuto la
    primera vez que se probó esto en producción -- la propia petición acabó
    en 502 y de paso dejó sin responder al resto de usuarios mientras tanto.
    Aquí, igual que el relleno de lotes, responde al momento con un id y
    hace el trabajo de fondo."""
    quitadas = []
    revisados = 0
    for candidato_id, archivo_id in items:
        archivo = reclutamiento_module.get_archivo(archivo_id)
        if archivo is None or not os.path.exists(archivo["ruta"]):
            continue
        revisados += 1
        try:
            with open(archivo["ruta"], "rb") as f:
                contenido = f.read()
            extraidos = cv_extraction.extraer_cv(contenido)
            if len(extraidos) != 1:
                candidato = reclutamiento_module.get_candidato(candidato_id)
                reclutamiento_module.quitar_foto(candidato_id)
                quitadas.append({"id": candidato_id, "nombre": candidato["nombre_completo"] if candidato else None})
        except Exception as exc:
            print(f"[limpiar-fotos] Fallo revisando al candidato {candidato_id}: {exc}")
        finally:
            estado = _limpiezas_fotos.get(limpieza_id)
            if estado is not None:
                estado["procesados"] += 1
    estado = _limpiezas_fotos.get(limpieza_id)
    if estado is not None:
        estado["terminado"] = True
        estado["revisados"] = revisados
        estado["fotos_quitadas"] = quitadas
    notificaciones_module.crear_notificacion(
        usuario_id,
        f"Limpieza de fotos de lote compartido terminada: {len(quitadas)} foto(s) quitada(s) de {revisados} revisado(s).",
        "/compartidos.html",
    )


@router.post("/candidatos/limpiar-fotos-de-lote-compartido")
def limpiar_fotos_de_lote_compartido_route(empresa: str = "kk", user: dict = Depends(require_informes_o_reclutamiento)):
    """Corrige el daño de un bug real: "Reextraer todos los CV" sacaba la
    foto de "la página 1" del PDF más reciente adjunto a cada candidato sin
    comprobar antes si ese PDF era de verdad SOLO suyo -- para fichas
    antiguas (antes del recorte por candidato) o casos sin división de
    páginas disponible, ese PDF era el LOTE ENTERO compartido por varias
    personas, así que a todas les tocó la cara de quien saliera primero en
    el lote (ver el fix en _rellenar_huecos_en_segundo_plano, que ya no deja
    que esto vuelva a pasar hacia delante -- esta ruta es solo para arreglar
    lo que ya quedó mal guardado).

    Revisa cada candidato que hoy tiene foto: si su PDF más reciente vuelve
    a extraerse como MÁS DE UN candidato, esa foto no es de fiar -> se
    quita (queda sin foto, no se inventa una nueva). No toca a quien su PDF
    sí es de una sola persona -- su foto actual sigue siendo válida. Corre
    en segundo plano (ver _limpiar_fotos_en_segundo_plano) -- consulta el
    progreso con GET .../limpiar-fotos-de-lote-compartido/progreso/{id}."""
    _exigir_modulo_empresa(empresa, user)
    items = reclutamiento_module.candidatos_con_pdf_y_foto(empresa=empresa)
    limpieza_id = secrets.token_hex(8)
    _limpiezas_fotos[limpieza_id] = {"total": len(items), "procesados": 0, "terminado": False}
    threading.Thread(
        target=_limpiar_fotos_en_segundo_plano, args=(limpieza_id, items, user["id"]), daemon=True
    ).start()
    return {"ok": True, "limpieza_id": limpieza_id, "total": len(items)}


@router.get("/candidatos/limpiar-fotos-de-lote-compartido/progreso/{limpieza_id}")
def limpiar_fotos_progreso_route(limpieza_id: str, _user: dict = Depends(require_informes_o_reclutamiento)):
    estado = _limpiezas_fotos.get(limpieza_id)
    if estado is None:
        raise HTTPException(status_code=404, detail="No hay ninguna limpieza en marcha con ese id")
    return estado


@router.post("/candidatos/adjuntar-pdf-lote/confirmar")
async def adjuntar_pdf_lote_confirmar_route(
    file: UploadFile = File(...),
    mapeo: str = Form(...),
    titulo: str | None = Form(None),
    user: dict = Depends(require_informes_o_reclutamiento),
):
    """Recorta y adjunta -- recibe el PDF de lote UNA sola vez (en vez de
    subirlo N veces, una por candidato, como hacía antes el frontend) más la
    lista [{candidato_id, pagina_inicio, pagina_fin}] (rangos ya revisados o
    corregidos a mano en la vista previa). Si a algún candidato le falta el
    rango de páginas (detección no disponible para ese caso), se le adjunta
    el PDF completo -- mismo comportamiento que la herramienta original.

    Además, cuando SÍ hay un rango de páginas propio (un recorte limpio de
    una sola persona), se programa volver a extraer y rellenar los huecos de
    la ficha (formación/experiencia estructuradas y cualquier otro campo
    vacío) como tarea en segundo plano -- así resubir el mismo PDF de lote
    sobre fichas que ya existían las deja al día sin tener que entrar una a
    una, y sin que la petición se quede esperando (ver
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
        # reanudar_lotes_ia_pendientes lo retoma solo desde aquí sin perder
        # lo que ya se procesó.
        reclutamiento_module.crear_lote_ia_pendiente(lote_id, user["id"], titulo_lote, items_para_rellenar)
        _lanzar_relleno(lote_id, items_para_rellenar, user["id"], titulo_lote)
    return {"ok": True, "adjuntados": adjuntados, "procesando_relleno": len(items_para_rellenar), "lote_id": lote_id}


@router.get("/candidatos/adjuntar-pdf-lote/progreso/{lote_id}")
def progreso_relleno_lote_route(lote_id: str, _user: dict = Depends(require_informes_o_reclutamiento)):
    """Para que el frontend pueda sondear 'cuántos van' del relleno con IA en
    segundo plano (ver _rellenar_huecos_en_segundo_plano) -- 404 si el
    servidor se reinició desde entonces o el id no existe."""
    progreso = _progreso_lotes.get(lote_id)
    if progreso is None:
        raise HTTPException(status_code=404, detail="No hay ningún proceso en marcha con ese id")
    return progreso


@router.post("/candidatos/{candidato_id}/archivos")
async def agregar_archivo_route(candidato_id: int, file: UploadFile = File(...), _user: dict = Depends(require_modulo_candidato)):
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
def reextraer_archivo_route(candidato_id: int, archivo_id: int, _user: dict = Depends(require_modulo_candidato)):
    """Vuelve a leer un PDF que YA está adjunto a esta ficha -- útil cuando
    una mejora del extractor local deja desactualizada una ficha que se
    procesó antes del arreglo. No sobreescribe nada por su cuenta: el
    frontend rellena el formulario con el resultado para que el reclutador
    lo revise antes de guardar, igual que al subir un CV nuevo.

    Si la lectura sale bien, se marca ia_extraida_en aquí mismo (igual que
    hace el relleno en segundo plano del lote, ver
    _rellenar_huecos_en_segundo_plano) -- esta es la ÚNICA otra vía por la
    que una ficha puede llegar a tenerlo si el relleno automático del lote
    falló para ella en su momento (PDF de ese candidato dañado, recorte con
    páginas mal detectadas...) y se quedó sirviendo el PDF original en vez
    del diseño propio. Sin esto, "Re-extraer con IA" solo actualizaba el
    formulario pero nunca destrababa esa ficha."""
    contenido = _leer_archivo_pdf(candidato_id, archivo_id)
    try:
        candidatos = cv_extraction.extraer_cv(contenido)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not candidatos:
        raise HTTPException(status_code=422, detail="No se reconoció ningún candidato en este PDF")
    if len(candidatos) == 1:
        reclutamiento_module.marcar_ia_extraida(candidato_id)
        return {"ok": True, "candidato": candidatos[0], "de_lote": False}
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
    reclutamiento_module.marcar_ia_extraida(candidato_id)
    return {"ok": True, "candidato": encontrado, "de_lote": True}


@router.post("/candidatos/{candidato_id}/archivos/{archivo_id}/extraer-foto")
def extraer_foto_route(candidato_id: int, archivo_id: int, _user: dict = Depends(require_modulo_candidato)):
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


def _archivo_pdf_original(candidato: dict):
    for archivo in candidato["archivos"]:
        if archivo["nombre_original"].lower().endswith(".pdf"):
            return reclutamiento_module.get_archivo(archivo["id"])
    return None


def _cv_pdf_bytes(candidato_id: int) -> tuple[bytes, str, bool] | None:
    """Bytes del CV que se le mostraría a este candidato en /cv.pdf --
    diseño propio si ya está enriquecido, PDF original (recorte de InfoJobs/
    lote o el que sea) si no. Compartido entre cv_pdf_route (descarga
    individual) y descargar_pdfs_lote_route (fusión de varios candidatos, ver
    más abajo) para que las dos vías decidan exactamente igual cuál PDF le
    corresponde a cada uno. El tercer valor (es_generado) distingue cuál de
    los dos fue, para que cv_pdf_route pueda mantener el mismo
    Content-Disposition que tenía cada rama antes de este refactor
    (attachment para el generado, inline para el original). None si no hay
    ficha con ese id."""
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None:
        return None
    ya_enriquecido = candidato_id in reclutamiento_module.candidatos_ya_enriquecidos([candidato_id])
    original = _archivo_pdf_original(candidato) if not ya_enriquecido else None
    if original is None:
        try:
            foto_ruta = reclutamiento_module.get_foto_ruta(candidato_id)
            pdf_bytes = cv_pdf.generar_cv_pdf(candidato, empresa=candidato.get("empresa", "kk"), foto_ruta=foto_ruta)
            return pdf_bytes, _nombre_archivo_cv(candidato), True
        except Exception as exc:
            print(f"[cv.pdf] Fallo generando el CV propio del candidato {candidato_id}, se sirve el original si lo hay: {exc}")
            original = _archivo_pdf_original(candidato)
            if original is None:
                return None
    with open(original["ruta"], "rb") as f:
        return f.read(), _nombre_archivo_cv(candidato), False


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
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    resultado = _cv_pdf_bytes(candidato_id)
    if resultado is None:
        raise HTTPException(status_code=500, detail="No se pudo generar el CV")
    pdf_bytes, nombre, es_generado = resultado
    disposicion = "attachment" if es_generado else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposicion}; filename="{nombre}"'},
    )


class DescargarPdfsLoteBody(BaseModel):
    candidato_ids: list[int]


@router.post("/candidatos/descargar-pdfs-lote")
def descargar_pdfs_lote_route(body: DescargarPdfsLoteBody, user: dict = Depends(get_current_user)):
    """Un único PDF con el CV de cada candidato seleccionado (el mismo que
    saldría en /cv.pdf para cada uno -- diseño propio o recorte original,
    lo que toque) fusionado en el orden EXACTO en que se pasan los ids, que
    es el orden en que se fueron marcando en el listado -- así el PDF final
    sale ordenado igual que la selección, sin que haya que reordenar nada a
    mano después de descargarlo. Mismo criterio que exportar_excel_route:
    quien no tiene el módulo completo (un gerente con candidatos sueltos
    compartidos) se queda solo con los ids a los que de verdad tiene
    acceso, en vez de un 403 en bloque -- así puede descargar los CV de
    quien le compartieron para entrevistar."""
    from pypdf import PdfReader, PdfWriter

    candidato_ids = _candidatos_accesibles(user, body.candidato_ids)
    if not candidato_ids:
        raise HTTPException(status_code=400, detail="No se ha seleccionado ningún candidato")
    writer = PdfWriter()
    omitidos = []
    for candidato_id in candidato_ids:
        resultado = _cv_pdf_bytes(candidato_id)
        if resultado is None:
            candidato = reclutamiento_module.get_candidato(candidato_id)
            omitidos.append(candidato["nombre_completo"] if candidato else f"#{candidato_id}")
            continue
        pdf_bytes, _nombre, _es_generado = resultado
        try:
            for pagina in PdfReader(io.BytesIO(pdf_bytes)).pages:
                writer.add_page(pagina)
        except Exception as exc:
            print(f"[descargar-pdfs-lote] PDF ilegible para el candidato {candidato_id}, se omite: {exc}")
            candidato = reclutamiento_module.get_candidato(candidato_id)
            omitidos.append(candidato["nombre_completo"] if candidato else f"#{candidato_id}")
    if len(writer.pages) == 0:
        raise HTTPException(status_code=500, detail="No se pudo generar ningún CV de los seleccionados")
    salida = io.BytesIO()
    writer.write(salida)
    headers = {"Content-Disposition": 'attachment; filename="CVs seleccionados.pdf"'}
    if omitidos:
        headers["X-Omitidos"] = json.dumps(omitidos, ensure_ascii=True)
    return Response(content=salida.getvalue(), media_type="application/pdf", headers=headers)


@router.delete("/candidatos/{candidato_id}/foto")
def quitar_foto_route(candidato_id: int, _user: dict = Depends(require_modulo_candidato)):
    if reclutamiento_module.get_candidato(candidato_id) is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    reclutamiento_module.quitar_foto(candidato_id)
    return {"ok": True}


@router.get("/candidatos/{candidato_id}/archivos/{archivo_id}")
def descargar_archivo_route(candidato_id: int, archivo_id: int, _user: dict = Depends(require_modulo_candidato)):
    candidato = reclutamiento_module.get_candidato(candidato_id)
    if candidato is None or archivo_id not in {a["id"] for a in candidato["archivos"]}:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    archivo = reclutamiento_module.get_archivo(archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    nombre = archivo["nombre_original"] or "archivo"
    # Solo se renombra el PDF (el CV en sí) -- otros adjuntos (fotos, cartas...)
    # se quedan con su nombre original, que sigue siendo lo más útil para esos.
    if nombre.lower().endswith(".pdf"):
        nombre = _nombre_archivo_cv(candidato)
    media_type = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    return FileResponse(
        archivo["ruta"],
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )
