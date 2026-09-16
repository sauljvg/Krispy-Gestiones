from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import auth as auth_module
import bajas_import as bajas_import_module
import entrevistas as entrevistas_module
import gemini as gemini_module
from auth_routes import get_current_user, require_admin
from entrevistas_pdf import generar_pdf


class SalidaIn(BaseModel):
    centro: str
    nombre: str
    fecha_baja: str
    motivo: str
    email: str | None = None


class MatchIn(BaseModel):
    respuesta_id: int
    salida_id: int


class SalidaEmailIn(BaseModel):
    email: str


class SalidaMotivoIn(BaseModel):
    motivo: str


class MotivoIn(BaseModel):
    motivo: str


class CentroIn(BaseModel):
    centro: str


class PegadoIn(BaseModel):
    texto: str


class FilaBajaIn(BaseModel):
    codigo_empleado: str | None = None
    nombre: str
    codigo_centro: str | None = None
    fecha_baja: str
    puesto: str | None = None
    motivo: str
    email: str | None = None


class ResolucionCentroIn(BaseModel):
    centro: str
    empresa: str


class ImportarBajasIn(BaseModel):
    filas: list[FilaBajaIn]
    resoluciones_centro: dict[str, ResolucionCentroIn] = {}
    resoluciones_motivo: dict[str, str] = {}


router = APIRouter()


def _modulo_para_empresa(empresa: str) -> str:
    return "saona_informes" if empresa == "saona" else "informes"


def require_entrevistas(empresa: str = "kk", user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Entrevistas de Salida")
    return user


def require_entrevistas_cualquiera(user: dict = Depends(get_current_user)) -> dict:
    """Para las rutas de import masivo de bajas -- de entrada no se sabe
    todavía a qué empresa(s) pertenecen las filas (eso se resuelve DESPUÉS
    de parsear, contra centro_codigos), así que aquí solo se exige tener
    Entrevistas de salida de AL MENOS una marca; el permiso fino por
    empresa se comprueba en importar_bajas_route, una vez resueltos los
    centros de cada fila."""
    if not (auth_module.tiene_modulo(user, "informes") or auth_module.tiene_modulo(user, "saona_informes")):
        raise HTTPException(status_code=403, detail="No tienes acceso a Entrevistas de Salida")
    return user


def require_entrevistas_oleada(oleada_id: int, user: dict = Depends(get_current_user)) -> dict:
    empresa = entrevistas_module.get_oleada_empresa(oleada_id) or "kk"
    if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
        raise HTTPException(status_code=403, detail="No tienes acceso a Entrevistas de Salida")
    return user


def _exigir_misma_oleada(oleada_id: int, salida_id: int | None = None, respuesta_id: int | None = None) -> None:
    """El permiso de arriba (require_entrevistas_oleada) solo valida la
    oleada que viene en la URL -- esto comprueba que la salida/respuesta
    concreta que se va a editar o borrar sea REALMENTE de esa oleada, para
    que no se pueda tocar un registro de otra oleada (y por tanto de otra
    empresa) pasando su id aunque la URL diga una oleada permitida."""
    if salida_id is not None:
        real = entrevistas_module.get_oleada_de_salida(salida_id)
        if real is not None and real != oleada_id:
            raise HTTPException(status_code=403, detail="Esta salida no pertenece a esta oleada")
    if respuesta_id is not None:
        real = entrevistas_module.get_oleada_de_respuesta(respuesta_id)
        if real is not None and real != oleada_id:
            raise HTTPException(status_code=403, detail="Esta respuesta no pertenece a esta oleada")


@router.get("/oleadas")
def list_oleadas_route(empresa: str = "kk", _user: dict = Depends(require_entrevistas)):
    return entrevistas_module.list_oleadas(empresa)


@router.get("/centros-conocidos")
def list_centros_conocidos_route(empresa: str = "kk", _user: dict = Depends(require_entrevistas)):
    return entrevistas_module.list_centros_conocidos(empresa)


# --- Import masivo de bajas (pegado desde Excel o captura de pantalla) ---
# Rutas ESTÁTICAS ("/bajas/...") declaradas antes de "/{oleada_id}/..." a
# propósito -- aunque aquí no debería colisionar (oleada_id es int, "bajas"
# no lo es), es el mismo cuidado que ya se sigue en otras rutas de la app
# con un patrón parecido.

@router.get("/bajas/codigos-centro")
def listar_codigos_centro_route(_user: dict = Depends(require_entrevistas_cualquiera)):
    return entrevistas_module.listar_codigos_centro()


@router.delete("/bajas/codigos-centro/{codigo}")
def eliminar_codigo_centro_route(codigo: str, _user: dict = Depends(require_admin)):
    entrevistas_module.eliminar_codigo_centro(codigo)
    return {"ok": True}


@router.get("/bajas/codigos-motivo")
def listar_codigos_motivo_route(_user: dict = Depends(require_entrevistas_cualquiera)):
    return entrevistas_module.listar_codigos_motivo()


@router.delete("/bajas/codigos-motivo/{codigo}")
def eliminar_codigo_motivo_route(codigo: str, _user: dict = Depends(require_admin)):
    entrevistas_module.eliminar_codigo_motivo(codigo)
    return {"ok": True}


@router.post("/bajas/parsear-texto")
def parsear_bajas_texto_route(body: PegadoIn, _user: dict = Depends(require_entrevistas_cualquiera)):
    filas = bajas_import_module.parsear_pegado_excel(body.texto)
    if not filas:
        raise HTTPException(status_code=400, detail="No se reconoció ninguna fila -- revisa que hayas pegado la tabla completa, con su fila de cabecera")
    return {"filas": filas}


@router.post("/bajas/parsear-imagen")
async def parsear_bajas_imagen_route(file: UploadFile = File(...), _user: dict = Depends(require_entrevistas_cualquiera)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Sube una imagen (captura de pantalla)")
    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="La imagen es demasiado grande (máximo 10 MB)")
    try:
        filas = bajas_import_module.extraer_bajas_de_imagen(contenido, file.content_type)
    except gemini_module.GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not filas:
        raise HTTPException(status_code=400, detail="No se reconoció ninguna fila en la imagen")
    return {"filas": filas}


@router.post("/bajas/importar")
def importar_bajas_route(body: ImportarBajasIn, user: dict = Depends(require_entrevistas_cualquiera)):
    # 1) Resolver centro Y motivo de cada fila -- ya conocidos
    # (centro_codigos/motivo_codigos, este último sembrado con BV/BVPP) o
    # recién indicados por el usuario en esta misma llamada
    # (resoluciones_centro/resoluciones_motivo, que además se guardan para
    # la próxima vez). Se juntan los dos tipos de pendientes en una sola
    # respuesta -- mejor que el usuario los resuelva todos de una vez que
    # descubrirlos uno a uno en varias vueltas.
    pendientes_centro = set()
    pendientes_motivo = set()
    filas_resueltas = []
    for fila in body.filas:
        codigo_centro = (fila.codigo_centro or "").strip()
        resuelto_centro = entrevistas_module.resolver_codigo_centro(codigo_centro) if codigo_centro else None
        if not resuelto_centro and codigo_centro in body.resoluciones_centro:
            resolucion = body.resoluciones_centro[codigo_centro]
            entrevistas_module.guardar_codigo_centro(codigo_centro, resolucion.centro, resolucion.empresa, user["username"])
            resuelto_centro = {"centro": resolucion.centro, "empresa": resolucion.empresa}
        if not resuelto_centro and codigo_centro:
            pendientes_centro.add(codigo_centro)

        codigo_motivo = (fila.motivo or "").strip()
        motivo_resuelto = entrevistas_module.resolver_codigo_motivo(codigo_motivo) if codigo_motivo else None
        if not motivo_resuelto and codigo_motivo in body.resoluciones_motivo:
            motivo_resuelto = body.resoluciones_motivo[codigo_motivo].strip()
            entrevistas_module.guardar_codigo_motivo(codigo_motivo, motivo_resuelto, user["username"])
        if not motivo_resuelto and codigo_motivo:
            pendientes_motivo.add(codigo_motivo)

        if not resuelto_centro or not motivo_resuelto:
            continue
        filas_resueltas.append({
            **fila.model_dump(), "centro": resuelto_centro["centro"], "empresa": resuelto_centro["empresa"],
            "motivo": motivo_resuelto,
        })

    if pendientes_centro or pendientes_motivo:
        return {"ok": False, "pendientes_centro": sorted(pendientes_centro), "pendientes_motivo": sorted(pendientes_motivo)}

    # 2) Con todo resuelto, comprobar que el usuario tiene Entrevistas de
    # salida de CADA empresa involucrada (una importación puede mezclar
    # filas de KK y de Saona, como en el caso real que motivó esto).
    empresas = {f["empresa"] for f in filas_resueltas}
    for empresa in empresas:
        if not auth_module.tiene_modulo(user, _modulo_para_empresa(empresa)):
            raise HTTPException(status_code=403, detail=f"No tienes acceso a Entrevistas de salida de {empresa}")

    resultado = entrevistas_module.agregar_bajas_masivo(filas_resueltas)
    return {"ok": True, **resultado}


@router.get("/{oleada_id}/centros")
def list_centros_route(oleada_id: int, _user: dict = Depends(require_entrevistas_oleada)):
    return entrevistas_module.list_centros(oleada_id)


@router.post("/importar")
async def importar_route(
    file: UploadFile = File(...),
    nueva_oleada: bool = Form(default=False),
    empresa: str = Form(default="kk"),
    user: dict = Depends(require_admin),
):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo Excel (.xlsx)")
    content = await file.read()
    try:
        resultado = entrevistas_module.import_excel(content, file.filename, user["username"], nueva_oleada, empresa=empresa)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **resultado}


@router.get("/{oleada_id}/reporte")
def reporte_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    try:
        return entrevistas_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{oleada_id}/evolucion")
def evolucion_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    try:
        return entrevistas_module.compute_evolucion(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{oleada_id}/salidas")
def list_salidas_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    return entrevistas_module.list_salidas(oleada_id, centro)


@router.post("/{oleada_id}/salidas")
def crear_salida_route(oleada_id: int, body: SalidaIn, _user: dict = Depends(require_entrevistas_oleada)):
    if not body.centro.strip() or not body.nombre.strip() or not body.fecha_baja.strip() or not body.motivo.strip():
        raise HTTPException(status_code=400, detail="Centro, nombre, fecha de baja y motivo son obligatorios")
    try:
        entrevistas_module.add_salida(
            oleada_id, body.centro.strip(), body.nombre.strip(), body.fecha_baja.strip(), body.motivo.strip(), body.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.delete("/{oleada_id}/salidas/{salida_id}")
def borrar_salida_route(oleada_id: int, salida_id: int, _user: dict = Depends(require_admin)):
    _exigir_misma_oleada(oleada_id, salida_id=salida_id)
    entrevistas_module.delete_salida(salida_id)
    return {"ok": True}


@router.patch("/{oleada_id}/salidas/{salida_id}/email")
def actualizar_salida_email_route(oleada_id: int, salida_id: int, body: SalidaEmailIn, _user: dict = Depends(require_entrevistas_oleada)):
    _exigir_misma_oleada(oleada_id, salida_id=salida_id)
    try:
        entrevistas_module.update_salida_email(salida_id, body.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.patch("/{oleada_id}/salidas/{salida_id}/motivo")
def actualizar_salida_motivo_route(oleada_id: int, salida_id: int, body: SalidaMotivoIn, _user: dict = Depends(require_entrevistas_oleada)):
    _exigir_misma_oleada(oleada_id, salida_id=salida_id)
    try:
        entrevistas_module.update_salida_motivo(salida_id, body.motivo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/{oleada_id}/matches")
def crear_match_route(oleada_id: int, body: MatchIn, _user: dict = Depends(require_entrevistas_oleada)):
    _exigir_misma_oleada(oleada_id, salida_id=body.salida_id, respuesta_id=body.respuesta_id)
    entrevistas_module.set_match_manual(body.respuesta_id, body.salida_id)
    return {"ok": True}


@router.delete("/{oleada_id}/matches/{respuesta_id}")
def borrar_match_route(oleada_id: int, respuesta_id: int, _user: dict = Depends(require_admin)):
    _exigir_misma_oleada(oleada_id, respuesta_id=respuesta_id)
    entrevistas_module.quitar_match_manual(respuesta_id)
    return {"ok": True}


@router.delete("/{oleada_id}/respuestas/{respuesta_id}")
def borrar_respuesta_route(oleada_id: int, respuesta_id: int, _user: dict = Depends(require_admin)):
    _exigir_misma_oleada(oleada_id, respuesta_id=respuesta_id)
    entrevistas_module.borrar_respuesta(respuesta_id)
    return {"ok": True}


@router.post("/{oleada_id}/respuestas/sincronizar-motivos")
def sincronizar_motivos_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    actualizadas = entrevistas_module.sincronizar_motivos_autoreportados(oleada_id, centro)
    return {"ok": True, "actualizadas": actualizadas}


@router.get("/{oleada_id}/respuestas")
def list_respuestas_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    return entrevistas_module.list_respuestas_con_motivo(oleada_id, centro)


@router.patch("/{oleada_id}/respuestas/{respuesta_id}/motivo")
def update_motivo_route(oleada_id: int, respuesta_id: int, body: MotivoIn, _user: dict = Depends(require_entrevistas_oleada)):
    _exigir_misma_oleada(oleada_id, respuesta_id=respuesta_id)
    if not body.motivo.strip():
        raise HTTPException(status_code=400, detail="El motivo no puede estar vacío")
    try:
        entrevistas_module.update_motivo(respuesta_id, body.motivo.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.patch("/{oleada_id}/respuestas/{respuesta_id}/centro")
def update_centro_route(oleada_id: int, respuesta_id: int, body: CentroIn, _user: dict = Depends(require_entrevistas_oleada)):
    _exigir_misma_oleada(oleada_id, respuesta_id=respuesta_id)
    if not body.centro.strip():
        raise HTTPException(status_code=400, detail="El centro no puede estar vacío")
    try:
        entrevistas_module.update_centro(respuesta_id, body.centro)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.get("/{oleada_id}/reporte.pdf")
def reporte_pdf_route(oleada_id: int, centro: str | None = None, _user: dict = Depends(require_entrevistas_oleada)):
    try:
        reporte = entrevistas_module.compute_reporte(oleada_id, centro)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    empresa = entrevistas_module.get_oleada_empresa(oleada_id) or "kk"
    pdf_bytes = generar_pdf(reporte, empresa=empresa)
    nombre = f"entrevista_salida_{centro or 'global'}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
