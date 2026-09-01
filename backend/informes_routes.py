import mimetypes
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth as auth_module
import informes as informes_module
import reclutamiento as reclutamiento_module
from auth_routes import get_current_user
from db import get_connection

router = APIRouter()


def _modulos_informes_empresa(empresa: str | None) -> tuple[str, ...]:
    """Igual que require_tipo_acceso resuelve la empresa desde el tipo, pero
    reutilizable para candidatos/respuestas sueltos -- el módulo de KK no
    debe dar acceso a compartir/descargar/reasignar nada de Saona, y
    viceversa. Se acepta también el módulo de Reclutamiento de esa misma
    empresa porque estas rutas las reutiliza compartidos.js."""
    if empresa == "saona":
        return ("saona_informes", "saona_reclutamiento")
    return ("informes", "reclutamiento")


def _exigir_modulo_informes_empresa(empresa: str | None, user: dict) -> None:
    if empresa is not None and not any(auth_module.tiene_modulo(user, m) for m in _modulos_informes_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Informes/Reclutamiento de esa empresa")


def _exigir_dueno_del_compartido(compartido_por: str | None, user: dict) -> None:
    """Solo quien compartió originalmente (o un admin) puede quitarlo o
    reasignarlo a otra persona -- si no, cualquiera con acceso al módulo
    podría robarle a otro compañero un candidato que compartió con un
    tercero."""
    if compartido_por is not None and compartido_por != user["username"] and user.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo quien lo compartió (o un admin) puede hacer este cambio")


def require_informes(user: dict = Depends(get_current_user)) -> dict:
    """Puerta genérica para acciones que no son de un tipo concreto (listar
    usuarios para compartir, compartir, CV) — basta con tener acceso a
    Informes de CUALQUIERA de las dos empresas. La restricción precisa por
    tipo/empresa la hace require_tipo_acceso en las rutas que sí tienen
    tipo_clave."""
    if not (auth_module.tiene_modulo(user, "informes") or auth_module.tiene_modulo(user, "saona_informes")):
        raise HTTPException(status_code=403, detail="No tienes acceso a Informes")
    return user


def require_informes_o_reclutamiento(user: dict = Depends(get_current_user)) -> dict:
    """Como require_informes, pero deja pasar también a quien solo tiene el
    módulo Reclutamiento (sin el resto de Informes) -- para las rutas que
    usa la propia página de Reclutamiento (compartidos.js), que vive en
    reclutamiento_routes.py pero reutiliza estos dos endpoints."""
    modulos = ("informes", "saona_informes", "reclutamiento", "saona_reclutamiento")
    if not any(auth_module.tiene_modulo(user, m) for m in modulos):
        raise HTTPException(status_code=403, detail="No tienes acceso a Informes o Reclutamiento")
    return user


def require_tipo_acceso(tipo_clave: str, user: dict = Depends(get_current_user)) -> dict:
    """La empresa se resuelve del propio tipo (no hace falta que el
    frontend la repita en la URL): un tipo 'kk' exige el módulo "informes",
    uno 'saona' exige "saona_informes". Además valida el tipo concreto — un
    usuario puede tener Informes pero solo para ciertos tipos (p.ej. solo
    Tiendas, no Oficina)."""
    tipo = informes_module.get_tipo(tipo_clave)
    if tipo is None:
        raise HTTPException(status_code=404, detail=f"Tipo de informe desconocido: {tipo_clave}")
    modulo = "saona_informes" if tipo.get("empresa") == "saona" else "informes"
    if not auth_module.tiene_modulo(user, modulo):
        raise HTTPException(status_code=403, detail="No tienes acceso a este módulo de Informes")
    permitidos = informes_module.get_tipos_permitidos(user["id"])
    if permitidos and tipo_clave not in permitidos:
        raise HTTPException(status_code=403, detail="No tienes acceso a este tipo de informe")
    return user


class NewTipoBody(BaseModel):
    clave: str
    nombre: str
    empresa: str = "kk"


class ArchivarTipoBody(BaseModel):
    archivado: bool = True


class CompartirBody(BaseModel):
    respuesta_ids: list[int]
    usuario_id: int


class CambiarDestinatarioItem(BaseModel):
    tipo: str  # "directo" | "informe"
    candidato_id: int | None = None
    respuesta_id: int | None = None
    usuario_id_actual: int


class CambiarDestinatarioBody(BaseModel):
    items: list[CambiarDestinatarioItem]
    nuevo_usuario_id: int


class HojaOcultaBody(BaseModel):
    hoja: str
    oculta: bool


class HojaNombreBody(BaseModel):
    hoja: str


@router.get("/tipos")
def list_tipos_route(empresa: str | None = None, incluir_archivados: bool = False, user: dict = Depends(require_informes)):
    # empresa=None (p.ej. desde la pantalla de Usuarios, para armar el
    # checklist de permisos) devuelve los tipos de las dos empresas juntos —
    # require_informes ya exige tener acceso a alguna. Si se pide una empresa
    # concreta, hace falta el módulo de ESA empresa en concreto (si no, un
    # usuario con solo saona_informes podría listar los tipos de KK, aunque
    # no pudiera leer sus respuestas).
    if empresa:
        modulo = "saona_informes" if empresa == "saona" else "informes"
        if not auth_module.tiene_modulo(user, modulo):
            raise HTTPException(status_code=403, detail="No tienes acceso a ese módulo de Informes")
    tipos = informes_module.list_tipos(empresa=empresa, incluir_archivados=incluir_archivados)
    permitidos = informes_module.get_tipos_permitidos(user["id"])
    if permitidos:
        tipos = [t for t in tipos if t["clave"] in permitidos]
    return tipos


@router.post("/tipos")
def create_tipo_route(body: NewTipoBody, user: dict = Depends(require_informes)):
    modulo = "saona_informes" if body.empresa == "saona" else "informes"
    if not auth_module.tiene_modulo(user, modulo):
        raise HTTPException(status_code=403, detail="No tienes acceso a ese módulo de Informes")
    try:
        tipo_id = informes_module.create_tipo(body.clave, body.nombre, body.empresa)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo crear el tipo (¿clave duplicada?): {exc}")
    return {"ok": True, "id": tipo_id}


@router.post("/tipos/{tipo_clave}/archivar")
def archivar_tipo_route(tipo_clave: str, body: ArchivarTipoBody, _user: dict = Depends(require_tipo_acceso)):
    try:
        informes_module.archivar_tipo(tipo_clave, body.archivado)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.delete("/tipos/{tipo_clave}")
def eliminar_tipo_route(tipo_clave: str, _user: dict = Depends(require_tipo_acceso)):
    try:
        informes_module.eliminar_tipo(tipo_clave)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.get("/usuarios-para-compartir")
def usuarios_para_compartir_route(_user: dict = Depends(get_current_user)):
    # Cualquiera logueado puede pedir esta lista (nombre/usuario/rol, nada
    # sensible) -- hace falta también para un gerente sin módulo que
    # comparte un candidato de su vacante con otro gerente (ver
    # compartir_candidatos_route en reclutamiento_routes.py, que sí filtra
    # de verdad qué candidatos puede compartir).
    conn = get_connection()
    rows = conn.execute("SELECT id, username, nombre, rol FROM usuarios ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/compartidos")
def get_compartidos_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    return informes_module.get_compartidos_con(user["id"], empresa=empresa)


@router.get("/compartidos-por-mi")
def get_compartidos_por_mi_route(empresa: str | None = None, user: dict = Depends(get_current_user)):
    return informes_module.get_compartidos_por(user["username"], empresa=empresa)


@router.get("/{tipo_clave}/hojas")
def list_hojas_route(tipo_clave: str, _user: dict = Depends(require_tipo_acceso)):
    try:
        return informes_module.list_hojas(tipo_clave)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{tipo_clave}/hojas/ocultar")
def set_hoja_oculta_route(tipo_clave: str, body: HojaOcultaBody, _user: dict = Depends(require_tipo_acceso)):
    try:
        informes_module.set_hoja_oculta(tipo_clave, body.hoja, body.oculta)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{tipo_clave}/hojas/principal")
def set_hoja_conteo_route(tipo_clave: str, body: HojaNombreBody, _user: dict = Depends(require_tipo_acceso)):
    try:
        informes_module.set_hoja_conteo(tipo_clave, body.hoja)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{tipo_clave}/hojas/eliminar")
def eliminar_hoja_route(tipo_clave: str, body: HojaNombreBody, _user: dict = Depends(require_tipo_acceso)):
    try:
        informes_module.eliminar_hoja(tipo_clave, body.hoja)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/{tipo_clave}/importar")
async def importar_route(tipo_clave: str, file: UploadFile = File(...), user: dict = Depends(require_tipo_acceso)):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = informes_module.import_excel(tipo_clave, content, file.filename, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/{tipo_clave}/respuestas")
def respuestas_route(
    tipo_clave: str,
    hoja: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=1000),
    q: str | None = None,
    orden: str | None = None,
    orden_dir: str = "asc",
    fecha_col: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    filtro_aptos: str = "todos",
    _user: dict = Depends(require_tipo_acceso),
):
    try:
        return informes_module.get_respuestas(
            tipo_clave, hoja=hoja, page=page, page_size=page_size, q=q,
            orden=orden, orden_dir=orden_dir,
            fecha_col=fecha_col, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
            filtro_aptos=filtro_aptos,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/respuestas/{respuesta_id}/cv")
async def subir_cv_route(respuesta_id: int, file: UploadFile = File(...), _user: dict = Depends(require_informes)):
    content = await file.read()
    try:
        informes_module.guardar_cv(respuesta_id, file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.get("/respuestas/{respuesta_id}/cv")
def descargar_cv_route(respuesta_id: int, user: dict = Depends(get_current_user)):
    tiene_acceso = auth_module.tiene_modulo(user, "informes") or informes_module.usuario_tiene_acceso_respuesta(
        user["id"], respuesta_id
    )
    if not tiene_acceso:
        raise HTTPException(status_code=403, detail="No tienes acceso a este CV")
    respuesta = informes_module.get_respuesta(respuesta_id)
    if respuesta is None or not respuesta["cv_ruta"] or not os.path.exists(respuesta["cv_ruta"]):
        raise HTTPException(status_code=404, detail="Este candidato no tiene CV subido")
    nombre = respuesta["cv_nombre_original"] or "cv"
    # inline (no attachment) + el media_type real para que el navegador lo
    # ABRA en la pestaña (los PDF se ven, no se descargan de golpe) y sea el
    # usuario quien decida guardarlo. Los .doc/.docx el navegador no los sabe
    # renderizar y los descargará igualmente, que es lo esperado ahí.
    media_type = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    return FileResponse(
        respuesta["cv_ruta"],
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


@router.post("/compartir")
def compartir_route(body: CompartirBody, user: dict = Depends(require_informes)):
    for rid in body.respuesta_ids:
        empresa = informes_module.get_empresa_respuesta(rid)
        if empresa is None:
            raise HTTPException(status_code=404, detail=f"Respuesta no encontrada: {rid}")
        _exigir_modulo_informes_empresa(empresa, user)
    informes_module.compartir_respuestas(body.respuesta_ids, body.usuario_id, user["username"])
    return {"ok": True}


@router.delete("/compartir/{respuesta_id}/{usuario_id}")
def dejar_de_compartir_route(respuesta_id: int, usuario_id: int, user: dict = Depends(require_informes)):
    _exigir_modulo_informes_empresa(informes_module.get_empresa_respuesta(respuesta_id), user)
    _exigir_dueno_del_compartido(informes_module.get_informe_compartido_por(respuesta_id, usuario_id), user)
    informes_module.dejar_de_compartir(respuesta_id, usuario_id)
    return {"ok": True}


@router.put("/compartidos-por-mi/destinatario")
def cambiar_destinatario_route(body: CambiarDestinatarioBody, user: dict = Depends(require_informes_o_reclutamiento)):
    items = [it.model_dump() for it in body.items]
    for it in items:
        if it["tipo"] == "directo":
            _exigir_modulo_informes_empresa(reclutamiento_module.get_empresa_candidato(it["candidato_id"]), user)
            _exigir_dueno_del_compartido(
                reclutamiento_module.get_candidato_compartido_por(it["candidato_id"], it["usuario_id_actual"]), user
            )
        else:
            _exigir_modulo_informes_empresa(informes_module.get_empresa_respuesta(it["respuesta_id"]), user)
            _exigir_dueno_del_compartido(
                informes_module.get_informe_compartido_por(it["respuesta_id"], it["usuario_id_actual"]), user
            )
    informes_module.cambiar_destinatario_compartidos(items, body.nuevo_usuario_id)
    return {"ok": True}
