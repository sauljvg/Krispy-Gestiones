import io
import json
import math
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

# Fuente única de verdad de colores/radios, compartida con la web (la lee
# clima.js vía fetch). Cambiar un color aquí lo cambia en la web y el PDF a
# la vez, en vez de tener que tocar dos constantes por separado.
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "design-tokens.json")
with open(TOKENS_PATH, encoding="utf-8") as _f:
    TOKENS = json.load(_f)

# Las mismas fuentes de marca que usa la web (H1 Gelica, H2/contenido Brandon
# Grotesque, H3 Brandon Printed). Gelica y Brandon Grotesque vienen como OTF
# con contornos PostScript (CFF), que reportlab no sabe cargar directamente
# — por eso se registran las variantes .ttf (convertidas una vez a contornos
# TrueType) que viven junto al logo en este mismo directorio de assets.
FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
FUENTE_TITULO = "Helvetica-Bold"
FUENTE_CONTENIDO = "Helvetica"
FUENTE_BLOQUES = "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("Gelica", os.path.join(FONT_DIR, "Gelica-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont("BrandonGrotesque", os.path.join(FONT_DIR, "BrandonGrotesque-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("BrandonPrinted", os.path.join(FONT_DIR, "BrandonPrinted-One.ttf")))
    FUENTE_TITULO = "Gelica"
    FUENTE_CONTENIDO = "BrandonGrotesque"
    FUENTE_BLOQUES = "BrandonPrinted"
except Exception:
    pass  # si faltan los .ttf, se sigue viendo bien con las fuentes base de reportlab

VERDE = colors.HexColor(TOKENS["marca"]["verde_kk"])
VERDE_OSCURO = VERDE
GRIS_TEXTO = colors.HexColor("#52514e")
GRIS_ANTERIOR = colors.HexColor(TOKENS["marca"]["gris_anterior"])
CHIP_VERDE = colors.HexColor(TOKENS["chips"]["fortaleza"])
CHIP_NARANJA = colors.HexColor(TOKENS["chips"]["oportunidad"])
RADIO_CHIP = TOKENS["radio"]["chip"]
RADIO_CAJA = TOKENS["radio"]["caja_score"]
RADIO_BARRA = TOKENS["radio"]["barra"]

COLOR_POR_CATEGORIA = {
    "Totalmente de acuerdo": colors.HexColor(TOKENS["likert"]["totalmente_de_acuerdo"]),
    "De acuerdo": colors.HexColor(TOKENS["likert"]["de_acuerdo"]),
    "Neutral": colors.HexColor(TOKENS["likert"]["neutral"]),
    "En desacuerdo": colors.HexColor(TOKENS["likert"]["en_desacuerdo"]),
    "Totalmente en desacuerdo": colors.HexColor(TOKENS["likert"]["totalmente_en_desacuerdo"]),
}
LIKERT_ORDEN = list(COLOR_POR_CATEGORIA.keys())

ANCHO_BARRA = 11 * cm
ANCHO_ETIQUETA_PREGUNTA = 6.3 * cm

# Umbral mínimo de % para imprimir su etiqueta dentro del segmento de barra.
# Se probó en 0 (mostrar todas) con datos reales y los segmentos muy angostos
# (2-5%) quedaban con el texto de dos etiquetas vecinas solapado/ilegible.
# Por eso se deja en 6: basta con bajarlo a 0 para volver a mostrarlas todas.
MIN_PCT_ETIQUETA = 6

TITULO_STYLE = ParagraphStyle("titulo", fontName=FUENTE_TITULO, fontSize=22, textColor=VERDE_OSCURO, alignment=1, spaceAfter=10, leading=26)
SUBTITULO_STYLE = ParagraphStyle("subtitulo", fontName=FUENTE_CONTENIDO, fontSize=18, textColor=VERDE_OSCURO, leading=24, spaceBefore=16, spaceAfter=10)
SUBTITULO_CENTRADO_STYLE = ParagraphStyle("subtituloCentrado", parent=SUBTITULO_STYLE, fontSize=19, alignment=1, spaceBefore=18, spaceAfter=8)
SUBTITULO_COLUMNA_STYLE = ParagraphStyle("subtituloColumna", fontName=FUENTE_CONTENIDO, fontSize=16, textColor=VERDE_OSCURO, alignment=1, spaceBefore=14, spaceAfter=8)
COLUMNA_TITULO_FORTALEZA = ParagraphStyle("colTituloFortaleza", fontName=FUENTE_BLOQUES, fontSize=13, textColor=VERDE, alignment=1, spaceAfter=8)
COLUMNA_TITULO_OPORTUNIDAD = ParagraphStyle("colTituloOportunidad", fontName=FUENTE_BLOQUES, fontSize=13, textColor=CHIP_NARANJA, alignment=1, spaceAfter=8)
PREGUNTA_STYLE = ParagraphStyle("pregunta", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=colors.black, leading=13.5)
NORMAL_STYLE = ParagraphStyle("normal", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=GRIS_TEXTO)
NORMAL_CENTRADO_STYLE = ParagraphStyle("normalCentrado", parent=NORMAL_STYLE, fontSize=13, alignment=1)
COMENTARIO_TITULO_STYLE = ParagraphStyle("comentarioTitulo", fontName=FUENTE_BLOQUES, fontSize=13, textColor=VERDE_OSCURO, spaceBefore=10, spaceAfter=6)
COMENTARIO_STYLE = ParagraphStyle("comentario", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=GRIS_TEXTO, spaceAfter=8, leading=16)
CHIP_STYLE_FORTALEZA = ParagraphStyle("chipFortaleza", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=colors.white, leading=16)
CHIP_STYLE_OPORTUNIDAD = ParagraphStyle("chipOportunidad", fontName=FUENTE_CONTENIDO, fontSize=12, textColor=colors.white, leading=16)
LEYENDA_STYLE = ParagraphStyle("leyenda", fontName=FUENTE_CONTENIDO, fontSize=9.5, textColor=GRIS_TEXTO, leading=12)
EJE_STYLE = ParagraphStyle("eje", fontName=FUENTE_CONTENIDO, fontSize=8, textColor=GRIS_TEXTO)


def _dibujar_estrella(c, cx, cy, r, color):
    """Ninguna de las fuentes de marca trae el glifo ★ (ni ●) — en vez de
    depender de un carácter que no existe en la fuente, se dibuja la
    estrella como un polígono vectorial."""
    c.saveState()
    c.setFillColor(color)
    path = c.beginPath()
    puntos = []
    for i in range(10):
        angulo = math.pi / 2 + i * math.pi / 5
        radio = r if i % 2 == 0 else r * 0.42
        puntos.append((cx + radio * math.cos(angulo), cy + radio * math.sin(angulo)))
    path.moveTo(*puntos[0])
    for x, y in puntos[1:]:
        path.lineTo(x, y)
    path.close()
    c.drawPath(path, fill=1, stroke=0)
    c.restoreState()


class CajaRedondeada(Flowable):
    """Caja con esquinas redondeadas (Presente/Anterior), igual que en la
    web — reportlab no tiene "border-radius" para celdas de Table, así que
    se dibuja a mano sobre el canvas."""

    def __init__(self, width, height, color_fondo, etiqueta, valor, radius=RADIO_CAJA, estrella=False):
        super().__init__()
        self.width = width
        self.height = height
        self.color_fondo = color_fondo
        self.etiqueta = etiqueta
        self.valor = valor
        self.radius = radius
        self.estrella = estrella

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.color_fondo)
        c.roundRect(0, 0, self.width, self.height, self.radius, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(FUENTE_CONTENIDO, 11)
        c.drawCentredString(self.width / 2, self.height - 20, self.etiqueta)

        valor_y = self.height / 2 - 12
        c.setFont(FUENTE_TITULO, 18)
        if self.estrella and self.valor != "—":
            ancho_valor = c.stringWidth(self.valor, FUENTE_TITULO, 18)
            centro_x = self.width / 2
            c.drawString(centro_x - ancho_valor / 2 - 3, valor_y, self.valor)
            _dibujar_estrella(c, centro_x + ancho_valor / 2 + 11, valor_y + 6.5, 7, colors.white)
        else:
            c.drawCentredString(self.width / 2, valor_y, self.valor)
        c.restoreState()


class BarraApilada(Flowable):
    """Barra apilada con esquinas redondeadas en los extremos, igual que en
    el gráfico web (Chart.js) — mucho más "de marca" que una fila de celdas
    de tabla con esquinas rectas."""

    def __init__(self, porcentajes, width=ANCHO_BARRA, height=16, radius=RADIO_BARRA):
        super().__init__()
        self.porcentajes = porcentajes
        self.width = width
        self.height = height
        self.radius = radius

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        segmentos = [(cat, pct) for cat, pct in self.porcentajes.items() if pct > 0]
        if not segmentos:
            segmentos = [("Neutral", 100.0)]
        total = sum(pct for _, pct in segmentos)

        c.saveState()
        recorte = c.beginPath()
        recorte.roundRect(0, 0, self.width, self.height, self.radius)
        c.clipPath(recorte, stroke=0, fill=0)

        x = 0.0
        for cat, pct in segmentos:
            ancho = self.width * pct / total
            c.setFillColor(COLOR_POR_CATEGORIA.get(cat, colors.grey))
            c.rect(x, 0, ancho, self.height, fill=1, stroke=0)
            if pct > MIN_PCT_ETIQUETA:
                c.setFillColor(colors.white)
                c.setFont(f"{FUENTE_CONTENIDO}-Bold" if FUENTE_CONTENIDO == "Helvetica" else FUENTE_CONTENIDO, 8)
                c.drawCentredString(x + ancho / 2, self.height / 2 - 3, f"{pct:.1f}%")
            x += ancho
        c.restoreState()


class CirculoLeyenda(Flowable):
    """Punto de color redondo (no un cuadrado ni un glifo de fuente) para la
    leyenda — un círculo se distingue mejor de un vistazo y a tamaño pequeño
    se ve más nítido que un cuadrado. Se dibuja a mano sobre el canvas."""

    def __init__(self, color, diametro=7):
        super().__init__()
        self.color = color
        self.diametro = diametro
        self.width = diametro
        self.height = diametro

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        r = self.diametro / 2
        c.saveState()
        c.setFillColor(self.color)
        c.setStrokeColor(colors.HexColor("#555555"))
        c.setLineWidth(0.4)
        c.circle(r, r, r, fill=1, stroke=1)
        c.restoreState()


def _swatch_leyenda(color, tam=7):
    """Punto redondo de color de tamaño exacto (ver CirculoLeyenda) — así la
    categoría se identifica por color Y por forma, no solo "a ojo" por el tono."""
    return CirculoLeyenda(color, diametro=tam)


def _leyenda_categorias():
    """Leyenda de las 5 categorías en una sola fila/línea — cada swatch es un
    cuadrado propio (no depende del ancho del texto), así que todo el bloque
    cabe en una línea siempre que la fuente sea razonablemente compacta. Cada
    columna de texto se dimensiona a su propio ancho natural (medido con
    stringWidth) — mezclar anchos fijos con None en la misma Table no
    reparte el espacio como cabría esperar y podía dejar anchos negativos."""
    fila = []
    anchos = []
    ancho_swatch = 11  # 7pt de círculo + ~4pt de aire antes del texto
    for cat in LIKERT_ORDEN:
        fila.append(_swatch_leyenda(COLOR_POR_CATEGORIA[cat]))
        anchos.append(ancho_swatch)
        fila.append(Paragraph(cat, LEYENDA_STYLE))
        anchos.append(pdfmetrics.stringWidth(cat, FUENTE_CONTENIDO, LEYENDA_STYLE.fontSize) + 14)
    tabla = Table([fila], colWidths=anchos)
    tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tabla


def _titulo_seccion(texto):
    """Título de sección (Resultados/Impulsores de Engagement, Preguntas
    abiertas) con una línea de acento debajo para que se note claramente que
    es un subtítulo, ya que las fuentes de marca no traen variante bold."""
    return [
        Paragraph(texto, SUBTITULO_STYLE),
        HRFlowable(width="100%", thickness=2, color=VERDE_OSCURO, spaceBefore=0, spaceAfter=10),
    ]


def _eje_porcentaje():
    marcas = Table([["0%", "25%", "50%", "75%", "100%"]], colWidths=[ANCHO_BARRA / 5] * 5, rowHeights=[12])
    marcas.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, -1), FUENTE_CONTENIDO),
        ("TEXTCOLOR", (0, 0), (-1, -1), GRIS_TEXTO),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
        ("ALIGN", (1, 0), (-2, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    fila = Table([["", marcas]], colWidths=[ANCHO_ETIQUETA_PREGUNTA, ANCHO_BARRA])
    fila.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return fila


def _seccion_preguntas(story, items, leyenda_despues=False):
    filas = []
    for item in items:
        filas.append([Paragraph(item["pregunta"], PREGUNTA_STYLE), BarraApilada(item["porcentajes"])])
    tabla = Table(filas, colWidths=[ANCHO_ETIQUETA_PREGUNTA, ANCHO_BARRA])
    tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e1e0d9")),
    ]))
    story.append(tabla)
    story.append(_eje_porcentaje())

    if leyenda_despues:
        # La leyenda va una sola vez, al terminar Resultados de Engagement,
        # y sirve para ese gráfico Y para Impulsores de Engagement que viene
        # justo después (mismas 5 categorías/colores en ambos).
        story.append(Spacer(1, 8))
        story.append(_leyenda_categorias())


ANCHO_CHIP = 8.5 * cm
GUTTER_CHIP = 0.5 * cm


CHIP_PAD_H = 12
CHIP_PAD_V = 9


def _altura_texto_chip(texto, estilo):
    """Alto natural que ocupará el texto dentro del chip, para poder igualar
    la altura de los dos chips (fortaleza/oportunidad) de una misma fila."""
    ancho_disponible = ANCHO_CHIP - 2 * CHIP_PAD_H
    _, alto = Paragraph(texto, estilo).wrap(ancho_disponible, 10000)
    return alto + 2 * CHIP_PAD_V


def _chip(texto, tipo, alto=None):
    color = CHIP_VERDE if tipo == "fortaleza" else CHIP_NARANJA
    estilo_texto = CHIP_STYLE_FORTALEZA if tipo == "fortaleza" else CHIP_STYLE_OPORTUNIDAD
    filas = [[Paragraph(texto, estilo_texto)]]
    tabla = Table(filas, colWidths=[ANCHO_CHIP], rowHeights=[alto] if alto else None)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), CHIP_PAD_H),
        ("RIGHTPADDING", (0, 0), (-1, -1), CHIP_PAD_H),
        ("TOPPADDING", (0, 0), (-1, -1), CHIP_PAD_V),
        ("BOTTOMPADDING", (0, 0), (-1, -1), CHIP_PAD_V),
        ("ROUNDEDCORNERS", [RADIO_CHIP] * 4),
    ]))
    return tabla


def generar_pdf(reporte):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    story = []

    if os.path.exists(LOGO_PATH):
        ancho_logo = 7.5 * cm
        logo = Image(LOGO_PATH, width=ancho_logo, height=ancho_logo * 177 / 500)
        logo.hAlign = "CENTER"
        story.append(logo)
        story.append(Spacer(1, 8))

    titulo_centro = reporte["centro"] or "Todos los centros"
    story.append(Paragraph(f"Clima Laboral Krispy Kreme — {titulo_centro}", TITULO_STYLE))

    empleados_txt = reporte["empleados"] if reporte["empleados"] is not None else "—"
    participacion_txt = f'{reporte["participacion"]}%' if reporte["participacion"] is not None else "—"
    story.append(Paragraph(
        f'N = {reporte["n"]}&nbsp;&nbsp;&nbsp;&nbsp; Empleados = {empleados_txt}&nbsp;&nbsp;&nbsp;&nbsp; '
        f'Participación = {participacion_txt}',
        NORMAL_CENTRADO_STYLE,
    ))
    story.append(Spacer(1, 6))

    def _cajas_score(presente_txt, anterior_txt, estrella=False):
        return Table(
            [[
                CajaRedondeada(4.3 * cm, 1.7 * cm, VERDE_OSCURO, "Presente", presente_txt, estrella=estrella),
                CajaRedondeada(4.3 * cm, 1.7 * cm, GRIS_ANTERIOR, "Anterior", anterior_txt, estrella=estrella),
            ]],
            colWidths=[4.5 * cm, 4.5 * cm],
        )

    presente_txt = f'{reporte["engagement_presente"]}%' if reporte["engagement_presente"] is not None else "—"
    anterior_txt = f'{reporte["engagement_anterior"]}%' if reporte["engagement_anterior"] is not None else "—"

    if reporte.get("tiene_satisfaccion"):
        sat_presente = f'{reporte["satisfaccion_presente"]:.1f}' if reporte["satisfaccion_presente"] is not None else "—"
        sat_anterior = f'{reporte["satisfaccion_anterior"]:.1f}' if reporte["satisfaccion_anterior"] is not None else "—"
        fila = [
            [Paragraph("Puntuación Global de Engagement", SUBTITULO_COLUMNA_STYLE), _cajas_score(presente_txt, anterior_txt)],
            [Paragraph("Satisfacción del cliente", SUBTITULO_COLUMNA_STYLE), _cajas_score(sat_presente, sat_anterior, estrella=True)],
        ]
        tabla_doble = Table([[fila[0], fila[1]]], colWidths=[9 * cm, 9 * cm])
        tabla_doble.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(tabla_doble)
    else:
        story.append(Paragraph("Puntuación Global de Engagement", SUBTITULO_COLUMNA_STYLE))
        tabla_centrada = Table([[_cajas_score(presente_txt, anterior_txt)]], colWidths=[18 * cm])
        tabla_centrada.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(tabla_centrada)

    story.extend(_titulo_seccion("Resultados de Engagement"))
    _seccion_preguntas(story, reporte["resultados_engagement"], leyenda_despues=True)

    story.extend(_titulo_seccion("Impulsores de Engagement"))
    _seccion_preguntas(story, reporte["impulsores_engagement"])

    filas_fo = max(len(reporte["fortalezas"]), len(reporte["oportunidades"]))
    filas_tabla = [[
        Paragraph("¡CELÉBRALO CON EL EQUIPO!", COLUMNA_TITULO_FORTALEZA),
        "",
        Paragraph("PLAN DE ACCIÓN", COLUMNA_TITULO_OPORTUNIDAD),
    ]]
    for idx in range(filas_fo):
        texto_izq = None
        texto_der = None
        if idx < len(reporte["fortalezas"]):
            i = reporte["fortalezas"][idx]
            texto_izq = f'{i["pregunta"]} — {i["top2box"]}% de acuerdo'
        if idx < len(reporte["oportunidades"]):
            i = reporte["oportunidades"][idx]
            texto_der = f'{i["pregunta"]} — {i["top2box"]}% de acuerdo'

        # Cada chip es su propia mini-tabla con fondo de color — sin forzar
        # la misma altura explícita en los dos, el par de una fila quedaba
        # con cuadros de distinto tamaño (el más corto no estiraba su color
        # de fondo hasta la altura de la fila, aunque la fila sí se igualaba).
        alto_izq = _altura_texto_chip(texto_izq, CHIP_STYLE_FORTALEZA) if texto_izq else 0
        alto_der = _altura_texto_chip(texto_der, CHIP_STYLE_OPORTUNIDAD) if texto_der else 0
        alto_fila = max(alto_izq, alto_der)

        celda_izq = _chip(texto_izq, "fortaleza", alto_fila) if texto_izq else ""
        celda_der = _chip(texto_der, "oportunidad", alto_fila) if texto_der else ""
        filas_tabla.append([celda_izq, "", celda_der])
    # Columna intermedia vacía (gutter) para separar visualmente los chips
    # verde/rojo — sin esto quedaban pegados borde con borde. El padding
    # vertical de la tabla también se sube para separar las filas entre sí.
    tabla_fo = Table(filas_tabla, colWidths=[ANCHO_CHIP, GUTTER_CHIP, ANCHO_CHIP])
    tabla_fo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    # Todo el bloque de Fortalezas/Oportunidades va junto: si no cabe entero
    # en lo que queda de página, se empuja completo a la siguiente en vez de
    # partirse a la mitad (como pasaba antes con datos reales).
    story.append(KeepTogether([
        Paragraph("Fortalezas / Oportunidades", SUBTITULO_CENTRADO_STYLE),
        tabla_fo,
    ]))

    abiertas_headers = list(reporte["abiertas"].keys())
    if abiertas_headers:
        story.extend(_titulo_seccion("Preguntas abiertas"))
        for header in abiertas_headers:
            story.append(Paragraph(header.upper(), COMENTARIO_TITULO_STYLE))
            textos = reporte["abiertas"].get(header, [])
            if textos:
                lista_txt = "<br/>".join(f"• {t}" for t in textos)
                story.append(Paragraph(lista_txt, COMENTARIO_STYLE))
            else:
                story.append(Paragraph("(sin comentarios)", NORMAL_STYLE))
            story.append(Spacer(1, 12))

    doc.build(story)
    return buffer.getvalue()
