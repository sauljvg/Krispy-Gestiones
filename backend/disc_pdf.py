import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
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

# Colores estandar DISC (los mismos del script Office/ExcelScript original).
COLOR_LETRA = {
    "D": colors.HexColor("#f15b4e"),
    "I": colors.HexColor("#f2d351"),
    "S": colors.HexColor("#80ba5b"),
    "C": colors.HexColor("#5090ad"),
}
GRIS_TEXTO = colors.HexColor("#52514e")
GRIS_CLARO = colors.HexColor("#e1e0d9")

TITULO_STYLE = ParagraphStyle("titulo", fontName=FUENTE_TITULO, fontSize=22, alignment=1, spaceAfter=6, leading=26)
SUBTITULO_STYLE = ParagraphStyle("subtitulo", fontName=FUENTE_CONTENIDO, fontSize=13, alignment=1, textColor=GRIS_TEXTO, spaceAfter=16)
SECCION_STYLE = ParagraphStyle("seccion", fontName=FUENTE_TITULO, fontSize=15, spaceBefore=14, spaceAfter=8)
NOTA_STYLE = ParagraphStyle("nota", fontName=FUENTE_CONTENIDO, fontSize=9, textColor=GRIS_TEXTO, leading=13)
TIPO_STYLE = ParagraphStyle("tipo", fontName=FUENTE_TITULO, fontSize=28, alignment=1, textColor=colors.black, spaceBefore=4, spaceAfter=4)
NOMBRE_PERFIL_STYLE = ParagraphStyle("nombrePerfil", fontName=FUENTE_TITULO, fontSize=17, alignment=1, spaceAfter=4)
RESUMEN_PERFIL_STYLE = ParagraphStyle("resumenPerfil", fontName=FUENTE_CONTENIDO, fontSize=12, alignment=1, textColor=GRIS_TEXTO, spaceAfter=14, leading=16)
SUBSECCION_STYLE = ParagraphStyle("subseccion", fontName=FUENTE_TITULO, fontSize=12, spaceBefore=10, spaceAfter=4)
LISTA_STYLE = ParagraphStyle("lista", fontName=FUENTE_CONTENIDO, fontSize=11, textColor=colors.black, leading=15)

ANCHO_BARRA = 11 * cm


class BarraDisc(Flowable):
    """Barra horizontal 0-100 para un valor D/I/S/C, con el color estandar
    de esa letra."""

    def __init__(self, letra, valor, width=ANCHO_BARRA, height=16, escala_max=100):
        super().__init__()
        self.letra = letra
        self.valor = valor or 0
        self.width = width
        self.height = height
        self.escala_max = escala_max

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(GRIS_CLARO)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=0)
        ancho_lleno = max(2, min(self.width, self.width * (self.valor / self.escala_max)))
        c.setFillColor(COLOR_LETRA.get(self.letra, colors.grey))
        c.roundRect(0, 0, ancho_lleno, self.height, 4, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(FUENTE_CONTENIDO, 10)
        c.drawString(self.width + 8, 3, str(round(self.valor)))
        c.restoreState()


def _tabla_perfil(perfil):
    filas = [["", ""]]
    data = []
    for letra in ("D", "I", "S", "C"):
        data.append([
            Paragraph(f"<b>{letra}</b>", ParagraphStyle("letra", fontName=FUENTE_TITULO, fontSize=12)),
            BarraDisc(letra, perfil.get(letra, 0)),
        ])
    t = Table(data, colWidths=[1.2 * cm, ANCHO_BARRA + 1.5 * cm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _lista(items):
    return Paragraph("<br/>".join(f"•&nbsp;&nbsp;{item}" for item in items), LISTA_STYLE)


def _secciones_perfil(perfil_info):
    """Bloque narrativo del informe por perfil (ver disc_perfiles.py) --
    contenido propio, no el de TTI Success Insights."""
    if not perfil_info:
        return []
    return [
        Spacer(1, 6),
        Paragraph(perfil_info["nombre"], NOMBRE_PERFIL_STYLE),
        Paragraph(perfil_info["resumen"], RESUMEN_PERFIL_STYLE),
        Paragraph("Características generales", SUBSECCION_STYLE),
        _lista(perfil_info["caracteristicas"]),
        Paragraph("Fortalezas", SUBSECCION_STYLE),
        _lista(perfil_info["fortalezas"]),
        Paragraph("Posibles áreas de mejora", SUBSECCION_STYLE),
        _lista(perfil_info["areas_de_mejora"]),
        Paragraph("Qué le motiva", SUBSECCION_STYLE),
        _lista(perfil_info["motivadores"]),
        Paragraph("Bajo presión", SUBSECCION_STYLE),
        Paragraph(perfil_info["bajo_presion"], LISTA_STYLE),
        Paragraph("Cómo comunicarse con esta persona", SUBSECCION_STYLE),
        _lista(perfil_info["como_comunicarse"]),
        Paragraph("Entorno ideal", SUBSECCION_STYLE),
        Paragraph(perfil_info["entorno_ideal"], LISTA_STYLE),
    ]


def generar_pdf(resultado):
    """resultado: dict como el que devuelve disc_module._row_to_dict (nombre,
    fecha_test, puntos_brutos, tipo_disc, perfil_adaptado, perfil_natural)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )

    story = [
        Paragraph("Perfil DISC", TITULO_STYLE),
        Paragraph(f"{resultado['nombre']} · {str(resultado['fecha_test'])[:16]}", SUBTITULO_STYLE),
        Paragraph("Aproximación al método TTI Success Insights", NOTA_STYLE),
        Spacer(1, 10),
        Paragraph("Perfil dominante", SECCION_STYLE),
        Paragraph(resultado["tipo_disc"], TIPO_STYLE),
        Spacer(1, 14),
        Paragraph("Estilo Adaptado (contexto profesional)", SECCION_STYLE),
        _tabla_perfil(resultado["perfil_adaptado"]),
        Spacer(1, 10),
        Paragraph("Estilo Natural (auténtico / relajado)", SECCION_STYLE),
        _tabla_perfil(resultado["perfil_natural"]),
    ]

    story += _secciones_perfil(resultado.get("perfil_info"))

    story += [
        Spacer(1, 20),
        Paragraph(
            "NOTAS IMPORTANTES: el perfil dominante (top-2 letras) es la parte más fiable de este "
            "resultado. Los valores numéricos son una aproximación calibrada con datos propios, con "
            "un margen de error de aproximadamente ±10 puntos incluso tras la optimización. El texto "
            "descriptivo de este informe es contenido propio (no de TTI Success Insights) — no "
            "sustituye un informe TTI Success Insights oficial.",
            NOTA_STYLE,
        ),
    ]

    doc.build(story)
    return buffer.getvalue()
