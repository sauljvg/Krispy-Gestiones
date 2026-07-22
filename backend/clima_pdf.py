import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "la_voz_logo.png")

VERDE = colors.HexColor("#006838")
AMARILLO = colors.HexColor("#eda100")
NEUTRAL = colors.HexColor("#8f8f89")
NARANJA = colors.HexColor("#e8622c")
ROJO = colors.HexColor("#a83232")
VERDE_OSCURO = colors.HexColor("#006838")
GRIS_TEXTO = colors.HexColor("#52514e")

COLOR_POR_CATEGORIA = {
    "Totalmente de acuerdo": VERDE,
    "De acuerdo": AMARILLO,
    "Neutral": NEUTRAL,
    "En desacuerdo": NARANJA,
    "Totalmente en desacuerdo": ROJO,
}

ANCHO_BARRA = 11 * cm

TITULO_STYLE = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=16, textColor=VERDE_OSCURO, spaceAfter=4)
SUBTITULO_STYLE = ParagraphStyle("subtitulo", fontName="Helvetica-Bold", fontSize=12, textColor=VERDE_OSCURO, spaceBefore=10, spaceAfter=6)
PREGUNTA_STYLE = ParagraphStyle("pregunta", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.black)
NORMAL_STYLE = ParagraphStyle("normal", fontName="Helvetica", fontSize=9, textColor=GRIS_TEXTO)
COMENTARIO_STYLE = ParagraphStyle("comentario", fontName="Helvetica", fontSize=8, textColor=GRIS_TEXTO, spaceAfter=4)


def _barra_apilada(porcentajes):
    segmentos = [(cat, pct) for cat, pct in porcentajes.items() if pct > 0]
    if not segmentos:
        segmentos = [("Neutral", 100.0)]
    total = sum(pct for _, pct in segmentos)
    anchos = [max(ANCHO_BARRA * pct / total, 2) for _, pct in segmentos]
    celdas = [[f"{pct:.1f}%" if pct >= 6 else "" for _, pct in segmentos]]
    tabla = Table([celdas[0]], colWidths=anchos, rowHeights=[16])
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for i, (cat, _) in enumerate(segmentos):
        estilo.append(("BACKGROUND", (i, 0), (i, 0), COLOR_POR_CATEGORIA.get(cat, colors.grey)))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _seccion_preguntas(story, items):
    filas = []
    for item in items:
        filas.append([Paragraph(item["pregunta"], PREGUNTA_STYLE), _barra_apilada(item["porcentajes"])])
    tabla = Table(filas, colWidths=[6.5 * cm, ANCHO_BARRA])
    tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e1e0d9")),
    ]))
    story.append(tabla)


def _nube_texto(entradas):
    if not entradas:
        return Paragraph("(sin comentarios)", NORMAL_STYLE)
    max_veces = max(e["veces"] for e in entradas) or 1
    partes = []
    for e in entradas:
        tam = 7 + round((e["veces"] / max_veces) * 11)
        partes.append(f'<font size="{tam}">{e["palabra"]}</font>')
    return Paragraph("&nbsp;&nbsp;".join(partes), ParagraphStyle("nube", fontName="Helvetica", textColor=VERDE_OSCURO, leading=20))


def generar_pdf(reporte):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    story = []

    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=4.5 * cm, height=4.5 * cm * 177 / 500)
        story.append(logo)
        story.append(Spacer(1, 6))

    titulo_centro = reporte["centro"] or "Todos los centros"
    story.append(Paragraph(f"Clima Laboral Krispy Kreme — {titulo_centro}", TITULO_STYLE))

    empleados_txt = reporte["empleados"] if reporte["empleados"] is not None else "—"
    participacion_txt = f'{reporte["participacion"]}%' if reporte["participacion"] is not None else "—"
    story.append(Paragraph(
        f'N = {reporte["n"]}&nbsp;&nbsp;&nbsp; Empleados = {empleados_txt}&nbsp;&nbsp;&nbsp; '
        f'Participación = {participacion_txt}',
        NORMAL_STYLE,
    ))

    story.append(Paragraph("Puntuación Global de Engagement", SUBTITULO_STYLE))
    presente_txt = f'{reporte["engagement_presente"]}%' if reporte["engagement_presente"] is not None else "—"
    anterior_txt = f'{reporte["engagement_anterior"]}%' if reporte["engagement_anterior"] is not None else "—"
    tabla_score = Table([[f"Presente\n{presente_txt}", f"Anterior\n{anterior_txt}"]], colWidths=[5 * cm, 5 * cm], rowHeights=[1.4 * cm])
    tabla_score.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), VERDE_OSCURO),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#8a8a86")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 13),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tabla_score)

    story.append(Paragraph("Resultados de Engagement", SUBTITULO_STYLE))
    _seccion_preguntas(story, reporte["resultados_engagement"])

    story.append(Paragraph("Impulsores de Engagement", SUBTITULO_STYLE))
    _seccion_preguntas(story, reporte["impulsores_engagement"])

    story.append(Paragraph("Fortalezas / Oportunidades", SUBTITULO_STYLE))
    fort_txt = "<br/>".join(f'+ {i["pregunta"]} ({i["top2box"]}%)' for i in reporte["fortalezas"])
    opor_txt = "<br/>".join(f'- {i["pregunta"]} ({i["top2box"]}%)' for i in reporte["oportunidades"])
    tabla_fo = Table(
        [[Paragraph(fort_txt, NORMAL_STYLE), Paragraph(opor_txt, NORMAL_STYLE)]],
        colWidths=[8.7 * cm, 8.7 * cm],
    )
    tabla_fo.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(tabla_fo)

    abiertas_headers = list(reporte["nube_palabras"].keys())
    if abiertas_headers:
        story.append(Paragraph("Comentarios abiertos", SUBTITULO_STYLE))
        for header in abiertas_headers:
            story.append(Paragraph(header, PREGUNTA_STYLE))
            story.append(Spacer(1, 4))
            story.append(_nube_texto(reporte["nube_palabras"][header]))
            story.append(Spacer(1, 8))
            textos = reporte["abiertas"].get(header, [])
            if textos:
                lista_txt = "<br/>".join(f"• {t}" for t in textos)
                story.append(Paragraph(lista_txt, COMENTARIO_STYLE))
            story.append(Spacer(1, 12))

    doc.build(story)
    return buffer.getvalue()
