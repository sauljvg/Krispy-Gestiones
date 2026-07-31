"""Modulo DISC (Success Insights / TTI): calculo de perfil D/I/S/C a partir
de un test de 24 preguntas de ranking forzado (4 opciones por pregunta,
ordenadas de 1a a 4a preferencia), con los pesos y la transformacion TTI
ajustados por scipy en optimization_report.json (ver config_disc.py).

Aproximacion, no el algoritmo propietario de TTI Success Insights: el perfil
Dominante (top-2 letras) es fiable; los valores numericos tienen un margen
de error de aprox. +/-10 puntos incluso tras la optimizacion (ver
config_disc.py para el detalle de precision antes/despues)."""
import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import auth as auth_module
from auth_routes import get_current_user
from config_disc import FACTORES_TTI, PESOS_RANKING
from db import get_connection

LETRAS = ["D", "I", "S", "C"]

# Las 24 preguntas del formulario actual (Glosario DISC, DISC KK) -- cada una
# con sus 4 opciones (una por letra). El orden D,I,S,C aqui es solo el de
# almacenamiento; el frontend baraja el orden de presentacion para que
# ordenar no sea trivial, y manda de vuelta la letra de cada opcion en el
# orden en que la persona la clasifico (ver POST /calcular).
PREGUNTAS_DISC = [
    {"D": "Espontáneo", "I": "Contento, satisfecho", "S": "Sosegado, tranquilo", "C": "Positivo, confiado"},
    {"D": "Audaz, atrevido", "I": "Encantador, agradable", "S": "Apoya", "C": "Fácil de guiar, seguidor"},
    {"D": "Audaz, arriesgado", "I": "Expresivo", "S": "Satisfecho, contento", "C": "Diplomático, discreto"},
    {"D": "Emprendedor, pionero, explorador", "I": "Optimista", "S": "Servicial, complaciente, dispuesto a ayudar", "C": "Respetuoso, cortés"},
    {"D": "Ansioso, impaciente", "I": "Alegre, vivaz, entusiasta", "S": "Predispuesto, adaptable", "C": "Metódico"},
    {"D": "Invencible, determinado", "I": "Divertido, alegre, desenfadado", "S": "Obediente, dócil, cumplidor", "C": "Lógico"},
    {"D": "Valiente, toma riesgos", "I": "Cordial, cálido, amigable", "S": "Moderado, evita extremos", "C": "Analítico"},
    {"D": "Vigoroso, enérgico", "I": "Sociable, disfruta de la compañía de los demás", "S": "Indulgente, tolerante", "C": "Estructurado"},
    {"D": "Competitivo, busca ganar", "I": "Extrovertido, divertido, sociable", "S": "Armonioso, agradable", "C": "Considerado, bondadoso, amable"},
    {"D": "Emprendedor, retador, asume retos", "I": "Alma de la fiesta, extrovertido, divertido", "S": "Crédulo, influenciable", "C": "Precavido, receloso"},
    {"D": "Luchador", "I": "Inspirador", "S": "Comprensivo, compasivo, solidario", "C": "Tolerante"},
    {"D": "Decisivo, firme en la toma de decisión, seguro de sí", "I": "Locuaz, hablador", "S": "Convencional, tradicional", "C": "Controlado, comedido"},
    {"D": "Persistente, implacable, obstinado", "I": "Animado, gesticulador", "S": "Generoso, dispuesto", "C": "Disciplinado, autocontrol"},
    {"D": "Autónomo, independiente", "I": "Sociable, disfruta de la compañía de los demás", "S": "Paciente, constante, tolerante", "C": "Afable, reservado, de voz suave"},
    {"D": "Persuasivo, convincente", "I": "Magnético, atrae a los demás", "S": "Gentil, amable", "C": "Humilde, reservado, modesto"},
    {"D": "De carácter fuerte, dominante", "I": "Cautivador", "S": "Amable, dispuesto a dar y ayudar", "C": "Diligente, conforme, adaptable"},
    {"D": "Franco, habla libre y audazmente", "I": "Sociable, simpático", "S": "Fácil de llevar, tolerante", "C": "Comedido, reservado, controlado"},
    {"D": "Fuerza de voluntad, decidido", "I": "Divertido, alegre", "S": "Amable, servicial", "C": "Objetivo"},
    {"D": "Obstinado, terco", "I": "Atractivo, encantador, atrae a los demás", "S": "Agradable", "C": "Sistemático"},
    {"D": "Inquieto, imposible descansar o relajarse", "I": "Popular, apreciado por todos", "S": "Cercano, amigable", "C": "Ordenado, organizado"},
    {"D": "Discutidor, confrontador", "I": "Alegre, desenfadado", "S": "Despreocupado, desprendido", "C": "Pensador crítico"},
    {"D": "Valiente, atrevido, con coraje", "I": "Inspirador, motivador", "S": "Evita la confrontación", "C": "Callado, reservado"},
    {"D": "Determinado, decidido, inquebrantable, firme", "I": "Convincente, persuasivo", "S": "Bondadoso, amable", "C": "Cauteloso, precavido, cuidadoso"},
    {"D": "Atrevido, valiente, decidido", "I": "Jovial", "S": "Sereno, calmado, no se entusiasma fácilmente", "C": "Organizado"},
]


class DISCCalculator:
    """Encapsula el algoritmo de calculo: puntuacion bruta por ranking ->
    transformacion TTI (Adaptado y Natural) -> tipo DISC (top-2 letras)."""

    def __init__(self, pesos_ranking=None, factores_tti=None):
        self.pesos_ranking = pesos_ranking or PESOS_RANKING
        self.factores_tti = factores_tti or FACTORES_TTI

    def calcular_puntos_brutos(self, respuestas):
        """respuestas: lista de 24 listas de 4 letras D/I/S/C, cada una en el
        orden en que la persona clasifico las opciones de esa pregunta (1a a
        4a). Devuelve {"D":.., "I":.., "S":.., "C":..} en puntos brutos."""
        puntos = {L: 0.0 for L in LETRAS}
        for orden_letras in respuestas:
            if len(orden_letras) != 4 or set(orden_letras) != set(LETRAS):
                raise ValueError(f"Cada pregunta debe traer las 4 letras D/I/S/C exactamente una vez: {orden_letras}")
            for i, letra in enumerate(orden_letras):
                puntos[letra] += self.pesos_ranking[i]
        return puntos

    def _perfil_tti(self, puntos_brutos, perfil):
        factores = self.factores_tti[perfil]
        orden = sorted(puntos_brutos.items(), key=lambda kv: -kv[1])
        (l1, v1), (l2, v2), (l3, v3), (l4, v4) = orden
        total = v1 + v2 + v3 + v4
        if total <= 0:
            return {L: 0 for L in LETRAS}
        pct1, pct2, pct3, pct4 = (v1 / total * 100, v2 / total * 100, v3 / total * 100, v4 / total * 100)
        val1, val2 = pct1 * factores["top"], pct2 * factores["top"]
        val3, val4 = pct3 * factores["bottom"], pct4 * factores["bottom"]
        total_pol = val1 + val2 + val3 + val4
        factor_norm = factores["target"] / total_pol if total_pol else 0
        return {
            l1: round(val1 * factor_norm), l2: round(val2 * factor_norm),
            l3: round(val3 * factor_norm), l4: round(val4 * factor_norm),
        }

    def aplicar_transformacion_tti(self, puntos_brutos):
        """Devuelve {"adaptado": {D,I,S,C}, "natural": {D,I,S,C}} -- los dos
        perfiles normalizados al estilo TTI (Adaptado = comportamiento
        profesional, Natural = estilo autentico/relajado)."""
        return {
            "adaptado": self._perfil_tti(puntos_brutos, "adaptado"),
            "natural": self._perfil_tti(puntos_brutos, "natural"),
        }

    def obtener_tipo_disc(self, puntos_normalizados):
        """Top-2 letras del perfil (p.ej. "DI", "SC"), en orden descendente
        -- es la parte del resultado mas fiable (ver config_disc.py)."""
        orden = sorted(puntos_normalizados.items(), key=lambda kv: -kv[1])
        return orden[0][0] + orden[1][0]


calculator = DISCCalculator()


def ensure_disc_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS empleados_disc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            fecha_test DATETIME NOT NULL DEFAULT (datetime('now')),
            respuestas JSON NOT NULL,
            puntos_brutos JSON NOT NULL,
            tipo_disc TEXT NOT NULL,
            score_d FLOAT NOT NULL,
            score_i FLOAT NOT NULL,
            score_s FLOAT NOT NULL,
            score_c FLOAT NOT NULL,
            perfil_adaptado JSON NOT NULL,
            perfil_natural JSON NOT NULL
        )
    """)
    conn.commit()
    conn.close()


ensure_disc_tables()


class CalcularBody(BaseModel):
    nombre: str
    respuestas: list[list[str]]


def require_disc(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.tiene_modulo(user, "disc"):
        raise HTTPException(status_code=403, detail="No tienes acceso al módulo DISC")
    return user


router = APIRouter()


@router.get("/preguntas")
def preguntas_route(_user: dict = Depends(require_disc)):
    return PREGUNTAS_DISC


@router.get("/config")
def config_route(_user: dict = Depends(require_disc)):
    """Pesos/factores del algoritmo -- se exponen para que el frontend pueda
    calcular la vista previa en tiempo real (radar chart) sin duplicar a
    mano los mismos numeros que ya viven en config_disc.py."""
    return {"pesos_ranking": calculator.pesos_ranking, "factores_tti": calculator.factores_tti}


@router.post("/calcular")
def calcular_route(body: CalcularBody, _user: dict = Depends(require_disc)):
    if not body.nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if len(body.respuestas) != len(PREGUNTAS_DISC):
        raise HTTPException(status_code=400, detail=f"Se esperan {len(PREGUNTAS_DISC)} respuestas, llegaron {len(body.respuestas)}")

    try:
        puntos_brutos = calculator.calcular_puntos_brutos(body.respuestas)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    perfiles = calculator.aplicar_transformacion_tti(puntos_brutos)
    tipo_disc = calculator.obtener_tipo_disc(perfiles["adaptado"])

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO empleados_disc
           (nombre, respuestas, puntos_brutos, tipo_disc, score_d, score_i, score_s, score_c,
            perfil_adaptado, perfil_natural)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            body.nombre.strip(),
            json.dumps(body.respuestas, ensure_ascii=False),
            json.dumps(puntos_brutos, ensure_ascii=False),
            tipo_disc,
            puntos_brutos["D"], puntos_brutos["I"], puntos_brutos["S"], puntos_brutos["C"],
            json.dumps(perfiles["adaptado"], ensure_ascii=False),
            json.dumps(perfiles["natural"], ensure_ascii=False),
        ),
    )
    conn.commit()
    nuevo_id = cur.lastrowid
    conn.close()

    return {
        "id": nuevo_id,
        "nombre": body.nombre.strip(),
        "puntos_brutos": puntos_brutos,
        "tipo_disc": tipo_disc,
        "perfil_adaptado": perfiles["adaptado"],
        "perfil_natural": perfiles["natural"],
    }


def _row_to_dict(row):
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "fecha_test": row["fecha_test"],
        "puntos_brutos": json.loads(row["puntos_brutos"]),
        "tipo_disc": row["tipo_disc"],
        "perfil_adaptado": json.loads(row["perfil_adaptado"]),
        "perfil_natural": json.loads(row["perfil_natural"]),
    }


@router.get("/historico")
def historico_route(_user: dict = Depends(require_disc)):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM empleados_disc ORDER BY fecha_test DESC").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@router.get("/empleado/{nombre}")
def empleado_historico_route(nombre: str, _user: dict = Depends(require_disc)):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM empleados_disc WHERE nombre = ? ORDER BY fecha_test DESC", (nombre,)
    ).fetchall()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="Sin tests registrados para ese nombre")
    return [_row_to_dict(r) for r in rows]


@router.delete("/resultado/{resultado_id}")
def borrar_resultado_route(resultado_id: int, _user: dict = Depends(require_disc)):
    conn = get_connection()
    conn.execute("DELETE FROM empleados_disc WHERE id = ?", (resultado_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/resultado/{resultado_id}/pdf")
def resultado_pdf_route(resultado_id: int, _user: dict = Depends(require_disc)):
    from disc_pdf import generar_pdf

    conn = get_connection()
    row = conn.execute("SELECT * FROM empleados_disc WHERE id = ?", (resultado_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")

    pdf_bytes = generar_pdf(_row_to_dict(row))
    nombre_archivo = f"disc_{row['nombre']}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )
