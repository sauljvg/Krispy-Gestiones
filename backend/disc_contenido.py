"""Ensambla el informe DISC completo (contenido fijo + personalizado) a
partir del resultado ya calculado por DISCCalculator -- se calcula al vuelo
cada vez que se pide (no se guarda en la base de datos), así una mejora de
redacción futura se aplica automáticamente a todo el histórico sin tener
que volver a hacer el test. Lo usan tanto disc_module.py (para exponerlo en
las rutas) como disc_pdf.py (para el PDF)."""

from disc_contenido_fijo import banda
from disc_contenido_personalizado import (
    AREAS_MEJORA,
    CARACTERISTICAS_GENERALES,
    COMUNICACION_NO,
    COMUNICACION_SI,
    ESTILO_ADAPTADO_LISTA,
    ESTILO_NATURAL_ADAPTADO,
    INFLUENCIAS_OCULTAS,
    PERCEPCIONES,
    POTENCIADORES_PRODUCTIVIDAD,
    VALOR_ORGANIZACION,
)

EJES = ("D", "I", "S", "C")


def _eje_mas_bajo(perfil):
    return min(EJES, key=lambda letra: perfil.get(letra, 0))


def _estilo_por_perfil(perfil):
    """Los 4 sub-bloques (Problemas y Retos / Personas y Contactos / Ritmo y
    Constancia / Procedimientos y Normas), uno por eje, con el fragmento
    que corresponde a la banda de ESTE perfil concreto (se llama una vez
    con el Natural y otra con el Adaptado)."""
    bloques = []
    for letra in EJES:
        info = ESTILO_NATURAL_ADAPTADO[letra]
        b = banda(perfil.get(letra, 0))
        bloques.append({"titulo": info["titulo"], "texto": info[b]})
    return bloques


def _percepciones(perfil_adaptado):
    filas = {}
    for letra in EJES:
        b = banda(perfil_adaptado.get(letra, 0))
        filas[letra] = PERCEPCIONES[letra][b]
    return {
        "auto_percepcion": [frase for letra in EJES for frase in filas[letra]["auto"]],
        "presion_moderada": [frase for letra in EJES for frase in filas[letra]["presion_moderada"]],
        "presion_extrema": [frase for letra in EJES for frase in filas[letra]["presion_extrema"]],
    }


def construir_informe_completo(nombre, tipo_disc, perfil_adaptado, perfil_natural):
    """nombre: nombre completo (se usa solo el primer nombre de pila en el
    texto). tipo_disc: 2 letras (p.ej. 'SC'). perfil_adaptado/perfil_natural:
    {'D':.., 'I':.., 'S':.., 'C':..}."""
    primer_nombre = nombre.strip().split(" ")[0] if nombre.strip() else nombre
    letra_primaria = tipo_disc[0]
    eje_bajo_adaptado = _eje_mas_bajo(perfil_adaptado)

    return {
        "caracteristicas_generales": CARACTERISTICAS_GENERALES.get(tipo_disc, "").format(nombre=primer_nombre),
        "valor_organizacion": VALOR_ORGANIZACION.get(tipo_disc, []),
        "comunicacion_si": COMUNICACION_SI.get(letra_primaria, []),
        "comunicacion_no": COMUNICACION_NO.get(letra_primaria, []),
        "estilo_adaptado_lista": ESTILO_ADAPTADO_LISTA.get(letra_primaria, []),
        "areas_mejora": AREAS_MEJORA.get(letra_primaria, []),
        "potenciadores_productividad": POTENCIADORES_PRODUCTIVIDAD.get(letra_primaria, []),
        "estilo_natural": _estilo_por_perfil(perfil_natural),
        "estilo_adaptado": _estilo_por_perfil(perfil_adaptado),
        "percepciones": _percepciones(perfil_adaptado),
        "influencias_ocultas": {
            "eje": eje_bajo_adaptado,
            "bullets": INFLUENCIAS_OCULTAS.get(eje_bajo_adaptado, []),
        },
    }
