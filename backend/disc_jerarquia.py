"""Jerarquía Conductual: deriva un valor 0-100 para cada uno de los 12
factores fijos (ver disc_contenido_fijo.FACTORES_JERARQUIA) a partir de las
4 puntuaciones D/I/S/C ya calculadas -- no existe una fórmula TTI conocida
para esto (solo tenemos el resultado final impreso en los PDFs, no el
algoritmo), así que es una aproximación propia razonada por el significado
de cada factor, en el mismo espíritu que el margen de error ya documentado
en config_disc.py. Cada factor es una combinación ponderada de D/I/S/C (o
de "100 menos" una letra, cuando el factor va en sentido contrario a esa
letra, p.ej. Cambio Frecuente sube cuando Estabilidad baja)."""

from disc_contenido_fijo import FACTORES_JERARQUIA

# peso: (letra, factor) -- si factor es negativo, se usa (100 - score) de esa
# letra en vez del score directo. Los pesos absolutos de cada fila suman 1.0.
PESOS_FACTORES = {
    "entorno_organizado": [("C", 0.6), ("S", 0.4)],
    "analisis_datos": [("C", 0.75), ("S", 0.25)],
    "consistencia": [("S", 0.7), ("C", 0.3)],
    "cumplimiento_normas": [("C", 0.8), ("S", 0.2)],
    "persistencia": [("C", 0.4), ("S", 0.3), ("D", 0.3)],
    "orientado_personas": [("I", 0.7), ("S", 0.3)],
    "orientacion_cliente": [("I", 0.5), ("S", 0.5)],
    "competitividad": [("D", 0.8), ("I", 0.2)],
    "urgencia": [("D", 0.8), ("I", 0.2)],
    "versatilidad": [("I", 0.6), ("D", 0.4)],
    "interaccion": [("I", 0.8), ("D", 0.2)],
    "cambio_frecuente": [("D", 0.5), ("I", 0.3), ("S", -0.2)],
}


def _valor_factor(clave, perfil):
    total = 0.0
    for letra, peso in PESOS_FACTORES[clave]:
        score = perfil.get(letra, 0)
        total += (100 - score) * abs(peso) if peso < 0 else score * peso
    return max(0, min(100, round(total)))


def _percentil_aproximado(valor):
    """No tenemos normas de población reales -- se aproxima con una
    compresión suave hacia el centro (50), como suele pasar al convertir
    una puntuación bruta a percentil poblacional real."""
    return max(1, min(99, round(50 + (valor - 50) * 0.85)))


def calcular_jerarquia(perfil):
    """perfil: {'D':.., 'I':.., 'S':.., 'C':..}. Devuelve la lista de 12
    factores con su valor, ORDENADA de mayor a menor (el ranking es lo que
    varía persona a persona, junto con los valores)."""
    filas = []
    for factor in FACTORES_JERARQUIA:
        valor = _valor_factor(factor["clave"], perfil)
        filas.append({
            "clave": factor["clave"],
            "nombre": factor["nombre"],
            "definicion": factor["definicion"],
            "valor": valor,
            "percentil": _percentil_aproximado(valor),
        })
    filas.sort(key=lambda f: -f["valor"])
    return filas


def combinar_jerarquias(perfil_natural, perfil_adaptado):
    """Combina Natural y Adaptado en una sola lista ordenada por Adaptado
    (que es como TTI presenta la página -- un ranking, con ambas barras por
    factor), con los 4 valores (valor/percentil de cada perfil) por fila."""
    natural = {f["clave"]: f for f in calcular_jerarquia(perfil_natural)}
    adaptado = calcular_jerarquia(perfil_adaptado)
    filas = []
    for f in adaptado:
        n = natural[f["clave"]]
        filas.append({
            "nombre": f["nombre"],
            "definicion": f["definicion"],
            "valor_natural": n["valor"],
            "percentil_natural": n["percentil"],
            "valor_adaptado": f["valor"],
            "percentil_adaptado": f["percentil"],
        })
    return filas
