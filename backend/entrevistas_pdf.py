import io
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, KeepTogether, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.flowables import HRFlowable

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "la_voz_logo.png")
LOGO_PATH_SAONA = os.path.join(ASSETS_DIR, "saona_logo.png")

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


def _marca_para_empresa(empresa):
    return TOKENS["marca_saona"] if empresa == "saona" else TOKENS["marca"]


GRIS_TEXTO = colors.HexColor("#52514e")
GRIS_CLARO = colors.HexColor("#e1e0d9")

ANCHO_BARRA = 11 * cm
ANCHO_ETIQUETA = 6.3 * cm

TITULO_STYLE = ParagraphStyle("titulo", fontName=FUENTE_TITULO, fontSize=22, alignment=1, spaceAfter=10, leading=26)
SUBTITULO_STYLE = ParagraphStyle("subtitulo", fontName=FUENTE_CONTENIDO, fontSize=16, leading=20, spaceBefore=14, spaceAfter=8)
NORMAL_STYLE = ParagraphStyle("normal", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=GRIS_TEXTO)
NORMAL_CENTRADO_STYLE = ParagraphStyle("normalCentrado", parent=NORMAL_STYLE, fontSize=13, alignment=1)
PREGUNTA_STYLE = ParagraphStyle("pregunta", fontName=FUENTE_CONTENIDO, fontSize=11, textColor=colors.black, leading=13)
COMENTARIO_TITULO_STYLE = ParagraphStyle("comentarioTitulo", fontName=FUENTE_TITULO, fontSize=13, spaceBefore=10, spaceAfter=6)
COMENTARIO_STYLE = ParagraphStyle("comentario", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=GRIS_TEXTO, spaceAfter=8, leading=16)


class CajaScore(Flowable):
    """Caja redondeada con la satisfacción general (escala 1-5), igual de
    estilo que las de Clima Laboral pero con un único valor."""

    def __init__(self, width, height, color_fondo, etiqueta, valor):
        super().__init__()
        self.width = width
        self.height = height
        self.color_fondo = color_fondo
        self.etiqueta = etiqueta
        self.valor = valor

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.color_fondo)
        c.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(FUENTE_CONTENIDO, 11)
        c.drawCentredString(self.width / 2, self.height - 20, self.etiqueta)
        c.setFont(FUENTE_TITULO, 22)
        c.drawCentredString(self.width / 2, self.height / 2 - 14, self.valor)
        c.restoreState()


class BarraValor(Flowable):
    """Barra horizontal de un único valor en escala 1-5 (promedio de un
    bloque o de una pregunta) — no apilada como en Clima Laboral, porque
    aquí no hay desglose por categoría de acuerdo, solo el promedio."""

    def __init__(self, valor, color_barra, width=ANCHO_BARRA, height=16, escala_max=5):
        super().__init__()
        self.valor = valor or 0
        self.color_barra = color_barra
        self.width = width
        self.height = height
        self.escala_max = escala_max

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(GRIS_CLARO)
        c.roundRect(0, 0, self.width, self.height, 6, fill=1, stroke=0)
        ancho_lleno = self.width * min(self.valor / self.escala_max, 1.0)
        if ancho_lleno > 0:
            recorte = c.beginPath()
            recorte.roundRect(0, 0, self.width, self.height, 6)
            c.saveState()
            c.clipPath(recorte, stroke=0, fill=0)
            c.setFillColor(self.color_barra)
            c.rect(0, 0, ancho_lleno, self.height, fill=1, stroke=0)
            c.restoreState()
        c.setFillColor(colors.black if self.valor < self.escala_max * 0.55 else colors.white)
        c.setFont(FUENTE_CONTENIDO, 9)
        c.drawString(6, self.height / 2 - 3, f"{self.valor:.2f} / {self.escala_max}")
        c.restoreState()


def _tabla_preguntas(items, color_barra):
    filas = [[Paragraph(item["pregunta"], PREGUNTA_STYLE), BarraValor(item["promedio"], color_barra)] for item in items]
    tabla = Table(filas, colWidths=[ANCHO_ETIQUETA, ANCHO_BARRA])
    tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRIS_CLARO),
    ]))
    return tabla


def generar_pdf(reporte, empresa="kk"):
    color_marca = colors.HexColor(_marca_para_empresa(empresa)["verde_kk"])
    TITULO_STYLE.textColor = color_marca
    SUBTITULO_STYLE.textColor = color_marca
    COMENTARIO_TITULO_STYLE.textColor = color_marca

    logo_path = LOGO_PATH_SAONA if empresa == "saona" else LOGO_PATH
    logo_ratio_alto_ancho = 409 / 1024 if empresa == "saona" else 177 / 500
    nombre_empresa = "Saona" if empresa == "saona" else "Krispy Kreme"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    story = []

    if os.path.exists(logo_path):
        ancho_logo = 7.5 * cm
        logo = Image(logo_path, width=ancho_logo, height=ancho_logo * logo_ratio_alto_ancho)
        logo.hAlign = "CENTER"
        story.append(logo)
        story.append(Spacer(1, 8))

    titulo_centro = reporte["centro"] or "Todos los centros"
    story.append(Paragraph(f"Entrevista de Salida {nombre_empresa} — {titulo_centro}", TITULO_STYLE))
    story.append(Paragraph(f"N = {reporte['n']}", NORMAL_CENTRADO_STYLE))
    story.append(Spacer(1, 6))

    satisfaccion_txt = f"{reporte['satisfaccion_general']:.2f} / 5" if reporte["satisfaccion_general"] is not None else "—"
    caja = Table([[CajaScore(4.5 * cm, 1.7 * cm, color_marca, "Satisfacción general", satisfaccion_txt)]], colWidths=[18 * cm])
    caja.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(caja)

    for bloque in reporte["bloques"]:
        story.append(Paragraph(bloque["nombre"], SUBTITULO_STYLE))
        story.append(HRFlowable(width="100%", thickness=1.5, color=color_marca, spaceBefore=0, spaceAfter=8))
        if bloque["promedio"] is not None:
            resumen = Table(
                [[Paragraph(f"Promedio del bloque", PREGUNTA_STYLE), BarraValor(bloque["promedio"], color_marca)]],
                colWidths=[ANCHO_ETIQUETA, ANCHO_BARRA],
            )
            resumen.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story.append(resumen)
        if bloque["preguntas"]:
            story.append(_tabla_preguntas(bloque["preguntas"], color_marca))
        story.append(Spacer(1, 10))

    if reporte["motivos"]:
        story.append(Paragraph("Motivos de salida", SUBTITULO_STYLE))
        story.append(HRFlowable(width="100%", thickness=1.5, color=color_marca, spaceBefore=0, spaceAfter=8))
        filas_motivos = [["Motivo", "Cantidad", "%"]] + [
            [m["motivo"], str(m["cantidad"]), f'{m["porcentaje"]}%'] for m in reporte["motivos"]
        ]
        tabla_motivos = Table(filas_motivos, colWidths=[11 * cm, 3 * cm, 3 * cm])
        tabla_motivos.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FUENTE_CONTENIDO),
            ("FONTNAME", (0, 0), (-1, 0), FUENTE_TITULO),
            ("BACKGROUND", (0, 0), (-1, 0), color_marca),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRIS_CLARO),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tabla_motivos)
        story.append(Spacer(1, 10))

    abiertas_headers = list(reporte["abiertas"].keys())
    if abiertas_headers:
        story.append(Paragraph("Comentarios abiertos", SUBTITULO_STYLE))
        story.append(HRFlowable(width="100%", thickness=1.5, color=color_marca, spaceBefore=0, spaceAfter=8))
        for header in abiertas_headers:
            story.append(Paragraph(header, COMENTARIO_TITULO_STYLE))
            textos = reporte["abiertas"].get(header, [])
            if textos:
                lista_txt = "<br/>".join(f"• {t}" for t in textos)
                story.append(Paragraph(lista_txt, COMENTARIO_STYLE))
            else:
                story.append(Paragraph("(sin comentarios)", NORMAL_STYLE))
            story.append(Spacer(1, 8))

    doc.build(story)
    return buffer.getvalue()
