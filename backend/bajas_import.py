"""Parseo de la hoja de bajas de personal que RRHH pega o sube como captura
de pantalla (ver entrevistas_routes.py) -- dos entradas distintas
(_parsear_pegado_excel / extraer_bajas_de_imagen), mismo formato de salida:
una lista de dicts con las claves codigo_empleado/nombre/codigo_centro/
fecha_baja/puesto/motivo/email (codigo_centro sin resolver todavía -- eso
lo hace entrevistas_routes.py contra centro_codigos).

Pedido explícito del usuario 16/09: poder subir esta información "tal cual"
(copy-paste desde Excel, o una captura de pantalla) sin tener que
reformatearla a mano primero.
"""
import base64
import datetime
import json
import re
import unicodedata

import gemini as gemini_module

# Cabeceras conocidas (normalizadas) -> campo interno. Varias variantes por
# campo porque el usuario confirmó que el texto exacto cambia entre tablas
# (p.ej. "Puesto" en la de Krispy Kreme, "POSICIÓN" en la de Saona, mismo
# significado).
CAMPOS_ESPERADOS = {
    "id": "codigo_empleado",
    "nombre y apellidos": "nombre",
    "nombre": "nombre",
    "centro": "codigo_centro",
    "fecha baja": "fecha_baja",
    "puesto": "puesto",
    "posicion": "puesto",
    "motivo baja": "motivo",
    "motivo": "motivo",
    "mail": "email",
    "email": "email",
    "correo": "email",
}

FECHA_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")


def _normalizar_texto(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().lower()


def _normalizar_fecha(valor: str | None) -> str | None:
    """DD/MM/AAAA (o con - o . como separador, año de 2 o 4 dígitos) ->
    AAAA-MM-DD, que es el formato que usa el resto de la app. Devuelve el
    valor tal cual si no reconoce el patrón, en vez de perderlo -- mejor
    que quien revise la importación vea el dato crudo y lo corrija a mano
    que no verlo en absoluto."""
    valor = (valor or "").strip()
    if not valor:
        return None
    m = FECHA_RE.match(valor)
    if not m:
        return valor
    dia, mes, anio = m.groups()
    if len(anio) == 2:
        anio = "20" + anio
    try:
        return datetime.date(int(anio), int(mes), int(dia)).isoformat()
    except ValueError:
        return valor


def parsear_pegado_excel(texto: str) -> list[dict]:
    """Un pegado directo desde una selección de celdas de Excel: filas
    separadas por salto de línea, columnas por tabulador (así es como el
    portapapeles de Windows/Excel guarda una selección). Tolera varias
    tablas seguidas en el mismo pegado (p.ej. una por empresa, cada una con
    su propia fila de cabecera) -- cualquier línea cuyas celdas casen con
    al menos 3 cabeceras conocidas se trata como el INICIO de una tabla
    nueva, no como datos."""
    lineas = [l for l in texto.split("\n") if l.strip()]
    filas = []
    mapa_actual = None
    for linea in lineas:
        celdas = [c.strip() for c in linea.split("\t")]
        normalizadas = [_normalizar_texto(c) for c in celdas]
        columnas_reconocidas = sum(1 for c in normalizadas if c in CAMPOS_ESPERADOS)
        if columnas_reconocidas >= 3:
            mapa_actual = {i: CAMPOS_ESPERADOS[c] for i, c in enumerate(normalizadas) if c in CAMPOS_ESPERADOS}
            continue
        if mapa_actual is None:
            continue
        fila = {}
        for i, campo in mapa_actual.items():
            if i < len(celdas) and celdas[i]:
                fila[campo] = celdas[i]
        if not fila.get("nombre"):
            continue
        if fila.get("fecha_baja"):
            fila["fecha_baja"] = _normalizar_fecha(fila["fecha_baja"])
        filas.append(fila)
    return filas


_PROMPT_IMAGEN = (
    "La imagen es una captura de pantalla de una tabla de Excel con bajas de "
    "personal (empleados que se han ido de la empresa). Cada fila tiene estas "
    "columnas, aunque el texto exacto de la cabecera puede variar un poco: "
    "ID (código de empleado), Nombre y Apellidos, Centro (código corto de la "
    "tienda u oficina, p.ej. \"TLGV\" o \"MADM\"), Fecha Baja (día/mes/año), "
    "Puesto o Posición, Motivo Baja (puede ser un código corto como \"BV\" o "
    "\"BVPP\"), Mail.\n\n"
    "Puede haber más de una tabla en la misma imagen (p.ej. una para cada "
    "empresa/marca) -- inclúyelas todas en el mismo array, en el mismo orden "
    "en que aparecen.\n\n"
    "Devuelve SOLO un array JSON (sin markdown, sin explicación) con un "
    "objeto por fila:\n"
    '[{"codigo_empleado": "...", "nombre": "...", "codigo_centro": "...", '
    '"fecha_baja": "DD/MM/AAAA", "puesto": "...", "motivo": "...", "email": "..."}]\n\n'
    "Si algún dato no aparece en una fila, usa null en ese campo. No inventes "
    "datos que no estén en la imagen."
)


def extraer_bajas_de_imagen(imagen_bytes: bytes, mime_type: str) -> list[dict]:
    """Lee la tabla de una captura de pantalla vía Gemini (visión) -- mismo
    cliente/patrón de parseo de respuesta que personal.py (JSON, tolerante
    a que venga envuelto en \\`\\`\\`json). Sube GeminiError tal cual si
    falla (la ruta la traduce a un 400/502 legible)."""
    imagen_b64 = base64.b64encode(imagen_bytes).decode("ascii")
    contents = [{
        "role": "user",
        "parts": [
            {"text": _PROMPT_IMAGEN},
            {"inlineData": {"mimeType": mime_type, "data": imagen_b64}},
        ],
    }]
    data = gemini_module.generar(contents, temperature=0.1, max_output_tokens=4096)
    candidatos = data.get("candidates") or []
    if not candidatos:
        raise gemini_module.GeminiError("Gemini no devolvió ninguna respuesta")
    texto = "".join(p.get("text", "") for p in candidatos[0].get("content", {}).get("parts", [])).strip()
    texto = texto.strip("`")
    if texto.lower().startswith("json"):
        texto = texto[4:].strip()
    try:
        filas_crudas = json.loads(texto)
    except (ValueError, TypeError):
        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if not match:
            raise gemini_module.GeminiError("No se pudo leer la tabla de la imagen")
        filas_crudas = json.loads(match.group(0))

    filas = []
    for f in filas_crudas:
        if not isinstance(f, dict) or not (f.get("nombre") or "").strip():
            continue
        filas.append({
            "codigo_empleado": (f.get("codigo_empleado") or "").strip() or None,
            "nombre": f.get("nombre", "").strip(),
            "codigo_centro": (f.get("codigo_centro") or "").strip() or None,
            "fecha_baja": _normalizar_fecha(f.get("fecha_baja")),
            "puesto": (f.get("puesto") or "").strip() or None,
            "motivo": (f.get("motivo") or "").strip() or None,
            "email": (f.get("email") or "").strip() or None,
        })
    return filas
