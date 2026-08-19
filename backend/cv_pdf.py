"""Genera un CV en PDF con diseño propio a partir de los datos YA extraídos
de un candidato (formacion_json/experiencia_json/extra_fields) -- mismo
patrón que clima_pdf.py/entrevistas_pdf.py/disc_pdf.py (reportlab +
design-tokens.json), para que se vea igual de cuidado que el resto de
informes del portal en vez de un volcado plano de campos."""
import io
import json
import os
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.flowables import HRFlowable

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

TOKENS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "design-tokens.json")
with open(TOKENS_PATH, encoding="utf-8") as _f:
    TOKENS = json.load(_f)

FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
FUENTE_TITULO = "Helvetica-Bold"
FUENTE_CONTENIDO = "Helvetica"
try:
    pdfmetrics.registerFont(TTFont("Gelica", os.path.join(FONT_DIR, "Gelica-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont("BrandonGrotesque", os.path.join(FONT_DIR, "BrandonGrotesque-Regular.ttf")))
    FUENTE_TITULO = "Gelica"
    FUENTE_CONTENIDO = "BrandonGrotesque"
except Exception:
    pass

GRIS_TEXTO = colors.HexColor("#52514e")
GRIS_CLARO = colors.HexColor("#e1e0d9")
BLANCO = colors.white

ANCHO_PAGINA_UTIL = 18 * cm
ANCHO_SIDEBAR = 6 * cm
ANCHO_PRINCIPAL = ANCHO_PAGINA_UTIL - ANCHO_SIDEBAR


def _marca_para_empresa(empresa):
    return TOKENS["marca_saona"] if empresa == "saona" else TOKENS["marca"]


def _estilos(color_marca):
    return {
        "nombre": ParagraphStyle("nombre", fontName=FUENTE_TITULO, fontSize=24, textColor=BLANCO, leading=28),
        "puesto": ParagraphStyle("puesto", fontName=FUENTE_CONTENIDO, fontSize=14, textColor=BLANCO, leading=18, spaceBefore=2),
        "contacto_header": ParagraphStyle("contactoHeader", fontName=FUENTE_CONTENIDO, fontSize=10.5, textColor=BLANCO, leading=15, spaceBefore=8),
        "sidebar_titulo": ParagraphStyle("sidebarTitulo", fontName=FUENTE_TITULO, fontSize=12, textColor=color_marca, spaceBefore=14, spaceAfter=4),
        "sidebar_texto": ParagraphStyle("sidebarTexto", fontName=FUENTE_CONTENIDO, fontSize=10, textColor=GRIS_TEXTO, leading=14),
        "seccion_titulo": ParagraphStyle("seccionTitulo", fontName=FUENTE_TITULO, fontSize=14, textColor=color_marca, spaceBefore=4, spaceAfter=8),
        "entrada_titulo": ParagraphStyle("entradaTitulo", fontName=FUENTE_TITULO, fontSize=11.5, textColor=colors.black, leading=14),
        "entrada_fechas": ParagraphStyle("entradaFechas", fontName=FUENTE_CONTENIDO, fontSize=9.5, textColor=GRIS_TEXTO, leading=13),
        "entrada_desc": ParagraphStyle("entradaDesc", fontName=FUENTE_CONTENIDO, fontSize=10, textColor=GRIS_TEXTO, leading=14, spaceBefore=2),
        "vacio": ParagraphStyle("vacio", fontName=FUENTE_CONTENIDO, fontSize=10, textColor=GRIS_CLARO, leading=14),
    }


class FotoCandidato(Flowable):
    """Foto recortada en círculo -- mismo espíritu que CajaScore/BarraValor
    en entrevistas_pdf.py (un Flowable a medida en vez de forzar reportlab a
    hacer algo para lo que no está pensado de serie)."""

    def __init__(self, ruta, diametro):
        super().__init__()
        self.ruta = ruta
        self.diametro = diametro

    def wrap(self, availWidth, availHeight):
        return (self.diametro, self.diametro)

    def draw(self):
        c = self.canv
        c.saveState()
        recorte = c.beginPath()
        recorte.circle(self.diametro / 2, self.diametro / 2, self.diametro / 2)
        c.clipPath(recorte, stroke=0, fill=0)
        c.drawImage(self.ruta, 0, 0, width=self.diametro, height=self.diametro, preserveAspectRatio=True, anchor="c")
        c.restoreState()


class BandaCabecera(Flowable):
    """Banda de color a todo el ancho de página (incluidos los márgenes)
    detrás de nombre/puesto/contacto, para que el CV no arranque igual que
    un formulario -- imita la cabecera de color de una plantilla de CV
    normal en vez de solo texto sobre blanco."""

    def __init__(self, width, height, color_fondo):
        super().__init__()
        self.width = width
        self.height = height
        self.color_fondo = color_fondo

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.color_fondo)
        c.rect(-2 * cm, 0, self.width + 4 * cm, self.height, fill=1, stroke=0)
        c.restoreState()


def _linea_fechas(fecha_inicio, fecha_fin):
    inicio = (fecha_inicio or "").strip()
    fin = (fecha_fin or "").strip()
    if inicio and fin:
        return f"{inicio} — {fin}"
    return inicio or fin or ""


def _bloque_experiencia(experiencia, estilos):
    if not experiencia:
        return [Paragraph("Sin experiencia laboral registrada.", estilos["vacio"])]
    flow = []
    for i, exp in enumerate(experiencia):
        titulo = exp.get("puesto") or "(puesto sin especificar)"
        if exp.get("empresa"):
            titulo += f" · {exp['empresa']}"
        flow.append(Paragraph(_esc(titulo), estilos["entrada_titulo"]))
        fechas = _linea_fechas(exp.get("fecha_inicio"), exp.get("fecha_fin"))
        if fechas:
            flow.append(Paragraph(_esc(fechas), estilos["entrada_fechas"]))
        if exp.get("descripcion"):
            flow.append(Paragraph(_esc(exp["descripcion"]), estilos["entrada_desc"]))
        if i < len(experiencia) - 1:
            flow.append(Spacer(1, 8))
    return flow


def _bloque_formacion(formacion, estilos):
    if not formacion:
        return [Paragraph("Sin formación reglada registrada.", estilos["vacio"])]
    flow = []
    for i, est in enumerate(formacion):
        titulo = est.get("titulo") or "(título sin especificar)"
        if est.get("centro"):
            titulo += f" · {est['centro']}"
        flow.append(Paragraph(_esc(titulo), estilos["entrada_titulo"]))
        fechas = _linea_fechas(est.get("fecha_inicio"), est.get("fecha_fin"))
        if fechas:
            flow.append(Paragraph(_esc(fechas), estilos["entrada_fechas"]))
        if i < len(formacion) - 1:
            flow.append(Spacer(1, 8))
    return flow


def _sidebar(candidato, estilos):
    # Etiquetas de texto en vez de emoji -- las fuentes de marca (Gelica/
    # BrandonGrotesque) no traen esos glifos y se veían como cuadros vacíos.
    flow = []
    contacto = [
        f"Tel: {_esc(candidato['telefono'])}" if candidato.get("telefono") else None,
        f"Email: {_esc(candidato['email'])}" if candidato.get("email") else None,
        f"Dirección: {_esc(candidato['direccion'])}" if candidato.get("direccion") else None,
        f"Nacimiento: {_esc(candidato['fecha_nacimiento'])}" if candidato.get("fecha_nacimiento") else None,
        f"DNI/NIE: {_esc(candidato['dni'])}" if candidato.get("dni") else None,
    ]
    contacto = [c for c in contacto if c]
    if contacto:
        flow.append(Paragraph("Contacto", estilos["sidebar_titulo"]))
        flow.append(Paragraph("<br/>".join(contacto), estilos["sidebar_texto"]))
    if candidato.get("disponibilidad"):
        flow.append(Paragraph("Disponibilidad", estilos["sidebar_titulo"]))
        flow.append(Paragraph(_esc(candidato["disponibilidad"]), estilos["sidebar_texto"]))
    # extra_fields: cualquier otro dato suelto que sacó la IA del CV
    # (Idiomas, Conocimientos, Carnet de conducir, Situación laboral...) --
    # se muestra tal cual, en el mismo orden en que se guardó.
    for clave, valor in (candidato.get("extra_fields") or {}).items():
        if not valor:
            continue
        flow.append(Paragraph(_esc(clave), estilos["sidebar_titulo"]))
        flow.append(Paragraph(_esc(str(valor)), estilos["sidebar_texto"]))
    if not flow:
        flow.append(Paragraph("Sin datos adicionales.", estilos["vacio"]))
    return flow


def generar_cv_pdf(candidato: dict, empresa="kk", foto_ruta=None) -> bytes:
    marca = _marca_para_empresa(empresa)
    color_marca = colors.HexColor(marca["verde_kk"])
    estilos = _estilos(color_marca)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=0, bottomMargin=1.5 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    story = []

    nombre = candidato.get("nombre_completo") or "(sin nombre)"
    puesto = candidato.get("puesto_solicitado") or ""
    if candidato.get("vacante_puesto"):
        puesto = candidato["vacante_puesto"]
        if candidato.get("vacante_centro"):
            puesto += f" · {candidato['vacante_centro']}"
    contacto_header = " &nbsp;·&nbsp; ".join(
        _esc(v) for v in [candidato.get("telefono"), candidato.get("email")] if v
    )

    cabecera_textos = [Paragraph(_esc(nombre), estilos["nombre"])]
    if puesto:
        cabecera_textos.append(Paragraph(_esc(puesto), estilos["puesto"]))
    if contacto_header:
        cabecera_textos.append(Paragraph(contacto_header, estilos["contacto_header"]))

    if foto_ruta and os.path.exists(foto_ruta):
        foto = FotoCandidato(foto_ruta, 2.6 * cm)
        fila_cabecera = Table([[cabecera_textos, foto]], colWidths=[ANCHO_PAGINA_UTIL - 2.6 * cm, 2.6 * cm])
        fila_cabecera.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ]))
        contenido_cabecera = fila_cabecera
    else:
        contenido_cabecera = cabecera_textos

    banda = Table([[contenido_cabecera]], colWidths=[ANCHO_PAGINA_UTIL])
    banda.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color_marca),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * cm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * cm),
    ]))
    story.append(banda)
    story.append(Spacer(1, 16))

    sidebar_flow = _sidebar(candidato, estilos)
    principal_flow = [
        Paragraph("Experiencia", estilos["seccion_titulo"]),
        HRFlowable(width="100%", thickness=1.2, color=color_marca, spaceBefore=0, spaceAfter=8),
        *_bloque_experiencia(candidato.get("experiencia_json") or [], estilos),
        Spacer(1, 14),
        Paragraph("Formación", estilos["seccion_titulo"]),
        HRFlowable(width="100%", thickness=1.2, color=color_marca, spaceBefore=0, spaceAfter=8),
        *_bloque_formacion(candidato.get("formacion_json") or [], estilos),
    ]

    cuerpo = Table([[sidebar_flow, principal_flow]], colWidths=[ANCHO_SIDEBAR, ANCHO_PRINCIPAL])
    cuerpo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f4f2ec")),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (0, 0), (0, 0), 14),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("LEFTPADDING", (1, 0), (1, 0), 18),
        ("TOPPADDING", (1, 0), (1, 0), 4),
    ]))
    story.append(cuerpo)

    doc.build(story)
    return buffer.getvalue()
