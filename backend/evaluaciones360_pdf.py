"""Informe en PDF de los resultados de UNA persona evaluada en UNA campaña
de Evaluaciones 360° -- mismo patrón que disc_pdf.py/entrevistas_pdf.py
(reportlab + design-tokens.json), el único de los tres módulos de
evaluación de personas que no tenía exportación hasta ahora."""
import io
import json
import os
from xml.sax.saxutils import escape as _esc_str

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _esc(valor):
    return _esc_str(str(valor)) if valor is not None else ""


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

# Mismo criterio de robustez que cv_pdf.py: si falta o esta corrupto este
# archivo, un color por defecto en vez de tumbar el import del modulo entero.
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "design-tokens.json")
try:
    with open(TOKENS_PATH, encoding="utf-8") as _f:
        TOKENS = json.load(_f)
except Exception as _exc:
    print(f"[evaluaciones360_pdf] No se pudo cargar {TOKENS_PATH} ({_exc}), usando un color por defecto.")
    TOKENS = {"marca": {"verde_kk": "#2f5233"}, "marca_saona": {"verde_kk": "#2f5233"}}

GRIS_TEXTO = colors.HexColor("#52514e")
GRIS_CLARO = colors.HexColor("#e1e0d9")
BLANCO = colors.white

RELACION_LABEL = {
    "autoevaluacion": "Autoevaluación",
    "superior": "Superior",
    "par": "Par",
    "reporte": "Reporte",
    "manual": "Añadido a mano",
}


def _marca_para_empresa(empresa):
    return TOKENS["marca_saona"] if empresa == "saona" else TOKENS["marca"]


def _estilos(color_marca):
    return {
        "titulo": ParagraphStyle("titulo", fontName=FUENTE_TITULO, fontSize=22, alignment=1, spaceAfter=4, leading=26),
        "subtitulo": ParagraphStyle("subtitulo", fontName=FUENTE_CONTENIDO, fontSize=12, alignment=1, textColor=GRIS_TEXTO, spaceAfter=18),
        "seccion": ParagraphStyle(
            "seccion", fontName=FUENTE_TITULO, fontSize=14, spaceBefore=14, spaceAfter=8,
            textColor=BLANCO, backColor=color_marca, borderPadding=(6, 9, 6, 9), leading=17,
        ),
        "promedio_general": ParagraphStyle("promedioGeneral", fontName=FUENTE_TITULO, fontSize=30, alignment=1, textColor=color_marca, spaceAfter=2),
        "promedio_general_sub": ParagraphStyle("promedioGeneralSub", fontName=FUENTE_CONTENIDO, fontSize=10, alignment=1, textColor=GRIS_TEXTO, spaceAfter=14),
        "texto": ParagraphStyle("texto", fontName=FUENTE_CONTENIDO, fontSize=10.5, textColor=colors.black, leading=15),
        "vacio": ParagraphStyle("vacio", fontName=FUENTE_CONTENIDO, fontSize=10, textColor=GRIS_CLARO, leading=14),
        "comentario_meta": ParagraphStyle("comentarioMeta", fontName=FUENTE_TITULO, fontSize=9.5, textColor=color_marca, leading=13, spaceBefore=8),
        "comentario_pregunta": ParagraphStyle("comentarioPregunta", fontName=FUENTE_CONTENIDO, fontSize=9, textColor=GRIS_TEXTO, leading=12),
        "comentario_texto": ParagraphStyle("comentarioTexto", fontName=FUENTE_CONTENIDO, fontSize=10, textColor=colors.black, leading=14, spaceAfter=2),
    }


def _tabla_promedios(pares, estilos):
    filas = [[Paragraph(_esc(etiqueta), estilos["texto"]), Paragraph(f"{valor} / 5", estilos["texto"])] for etiqueta, valor in pares]
    tabla = Table(filas, colWidths=[10 * cm, 3 * cm])
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRIS_CLARO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tabla


def generar_resultados_pdf(persona: dict, campana: dict, resultados: dict, empresa: str = "kk") -> bytes:
    marca = _marca_para_empresa(empresa)
    color_marca = colors.HexColor(marca["verde_kk"])
    estilos = _estilos(color_marca)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    story = []

    story.append(Paragraph(_esc(persona.get("nombre_completo") or "Evaluación 360°"), estilos["titulo"]))
    periodo = ""
    if campana.get("periodo_desde") or campana.get("periodo_hasta"):
        periodo = f" · {_esc(campana.get('periodo_desde') or '')} — {_esc(campana.get('periodo_hasta') or '')}"
    story.append(Paragraph(f"{_esc(campana.get('nombre') or '')}{periodo}", estilos["subtitulo"]))

    promedio_general = resultados.get("promedio_general")
    story.append(Paragraph(f"{promedio_general if promedio_general is not None else '—'} / 5", estilos["promedio_general"]))
    story.append(Paragraph("Promedio general", estilos["promedio_general_sub"]))

    story.append(Paragraph("Por competencia", estilos["seccion"]))
    por_grupo = resultados.get("promedio_por_grupo") or {}
    if por_grupo:
        story.append(_tabla_promedios(sorted(por_grupo.items()), estilos))
    else:
        story.append(Paragraph("Sin respuestas todavía.", estilos["vacio"]))

    story.append(Paragraph("Por tipo de evaluador", estilos["seccion"]))
    por_relacion = resultados.get("promedio_por_relacion") or {}
    if por_relacion:
        pares = [(RELACION_LABEL.get(rel, rel), valor) for rel, valor in por_relacion.items()]
        story.append(_tabla_promedios(pares, estilos))
    else:
        story.append(Paragraph("Sin respuestas todavía.", estilos["vacio"]))

    story.append(Paragraph("Comentarios abiertos", estilos["seccion"]))
    comentarios = resultados.get("comentarios_abiertos") or []
    if comentarios:
        for c in comentarios:
            relacion = RELACION_LABEL.get(c.get("relacion"), c.get("relacion") or "")
            story.append(Paragraph(f"{_esc(c.get('evaluador_nombre'))} · {_esc(relacion)}", estilos["comentario_meta"]))
            story.append(Paragraph(_esc(c.get("pregunta_texto")), estilos["comentario_pregunta"]))
            story.append(Paragraph(_esc(c.get("comentario")), estilos["comentario_texto"]))
    else:
        story.append(Paragraph("Sin comentarios todavía.", estilos["vacio"]))

    doc.build(story)
    return buffer.getvalue()
