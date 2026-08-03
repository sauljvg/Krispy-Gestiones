import io
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from disc_contenido_fijo import CONSEJOS_COMUNICACION, DESCRIPTORES, descriptores_resaltados

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

# Fuente única de verdad de colores, compartida con la web (disc_form.js) --
# antes vivían hardcodeados aquí por separado (ver design-tokens.json).
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "design-tokens.json")
with open(TOKENS_PATH, encoding="utf-8") as _f:
    _TOKENS = json.load(_f)

COLOR_LETRA = {letra: colors.HexColor(hexval) for letra, hexval in _TOKENS["disc"].items() if not letra.startswith("_")}
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


NOMBRE_LETRA = {"D": "Dominancia", "I": "Influencia", "S": "Estabilidad", "C": "Conformidad"}

ETIQUETA_EVITAR_STYLE = ParagraphStyle(
    "etiquetaEvitar", fontName=FUENTE_TITULO, fontSize=10, spaceBefore=6, spaceAfter=2, textColor=GRIS_TEXTO,
)


def _seccion_consejos_comunicacion():
    """Página 'Consejos de comunicación' -- contenido de referencia fijo
    (ver disc_contenido_fijo.py), igual para cualquier persona: cómo tratar
    a alguien de cada perfil D/I/S/C."""
    bloques = [
        Spacer(1, 6),
        Paragraph("Consejos de comunicación", SECCION_STYLE),
        Paragraph(
            "Sugerencias para comunicarse mejor con cada tipo de persona, según cuál sea su estilo de "
            "comportamiento predominante.",
            NOTA_STYLE,
        ),
    ]
    for letra in ("D", "I", "S", "C"):
        info = CONSEJOS_COMUNICACION[letra]
        bloques += [
            Spacer(1, 6),
            Paragraph(f"{NOMBRE_LETRA[letra]} — cuando se comunique con {info['descripcion']}:", SUBSECCION_STYLE),
            _lista(info["hacer"]),
            Paragraph("Evite:", ETIQUETA_EVITAR_STYLE),
            _lista(info["evitar"]),
        ]
    return bloques


def _seccion_descriptores(perfil_adaptado):
    """Página 'Descriptores' -- banco fijo de 64 palabras (8 'alto' + 8
    'bajo' por letra); se resalta en el color de cada letra el bloque que
    corresponde a la banda de esa persona (ver descriptores_resaltados)."""
    resaltados = descriptores_resaltados(perfil_adaptado)
    letras = ("D", "I", "S", "C")
    estilos_normal = {l: ParagraphStyle(f"desc_{l}_n", fontName=FUENTE_CONTENIDO, fontSize=9, textColor=colors.black) for l in letras}
    estilos_resaltado = {l: ParagraphStyle(f"desc_{l}_r", fontName=FUENTE_TITULO, fontSize=9, textColor=COLOR_LETRA[l]) for l in letras}

    def _tabla(bloque):
        encabezado = [Paragraph(f"<b>{NOMBRE_LETRA[l]}</b>", ParagraphStyle(f"descHead_{l}", fontName=FUENTE_TITULO, fontSize=10, alignment=1)) for l in letras]
        filas = [encabezado]
        for i in range(8):
            fila = []
            for letra in letras:
                palabra = DESCRIPTORES[letra][bloque][i]
                marcado = resaltados.get(letra) == bloque
                estilo = estilos_resaltado[letra] if marcado else estilos_normal[letra]
                fila.append(Paragraph(palabra, estilo))
            filas.append(fila)
        ancho_col = (ANCHO_BARRA + 1.5 * cm) / 4
        t = Table(filas, colWidths=[ancho_col] * 4)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, GRIS_CLARO),
        ]))
        return t

    return [
        Spacer(1, 6),
        Paragraph("Descriptores", SECCION_STYLE),
        Paragraph(
            "Palabras que describen el estilo de comportamiento de esta persona -- cómo resuelve problemas y "
            "enfrenta retos, influye en los demás, responde al ritmo del entorno y ante las reglas y "
            "procedimientos. Se resalta el bloque que corresponde a su perfil en cada factor.",
            NOTA_STYLE,
        ),
        Spacer(1, 8),
        _tabla("alto"),
        Spacer(1, 10),
        _tabla("bajo"),
    ]


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

    story += [PageBreak()]
    story += _seccion_consejos_comunicacion()
    story += [PageBreak()]
    story += _seccion_descriptores(resultado["perfil_adaptado"])

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
