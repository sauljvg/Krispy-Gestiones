"""Contenido de referencia FIJO/GENÉRICO para el informe DISC -- igual para
cualquier persona, solo cambia a quién se dirige (o qué casilla se resalta).
Reconstruido a partir de los 22 informes oficiales TTI Talent Insights que la
empresa ya tiene comprados (carpeta "DISC KK"), comparando el mismo texto en
varias personas distintas para confirmar que no varía -- uso 100% interno,
nunca se redistribuye ni se vende (autorizado explícitamente por el titular
de la empresa)."""
import math

BANDAS = {"bajo": (0, 39), "medio": (40, 64), "alto": (65, 1000)}


def banda(valor):
    """Convierte un score 0-100 (ya normalizado por DISCCalculator) en
    'bajo'/'medio'/'alto'. El punto neutro real es ~51, no ~25, porque el
    target TTI normaliza la suma de las 4 letras a ~205-209, no a 100 (ver
    config_disc.py FACTORES_TTI)."""
    for nombre, (lo, hi) in BANDAS.items():
        if lo <= valor <= hi:
            return nombre
    return "alto"


# ------------------------- Consejos de comunicación -------------------------
# Página "CONSEJOS DE COMUNICACIÓN" del informe TTI: confirmado idéntico
# (salvo el nombre en la frase introductoria) comparando el mismo texto en
# 3 personas distintas -- son consejos genéricos sobre CÓMO tratar a alguien
# de cada perfil, no dependen del perfil de quien lee el informe.
CONSEJOS_COMUNICACION = {
    "D": {
        "descripcion": "una persona ambiciosa, enérgica, decidida, independiente y orientada a objetivos",
        "hacer": [
            "Sea claro, específico, breve y concreto.",
            "Mantenga la conversación en el ámbito profesional.",
            "Prepárese con material de apoyo correctamente organizado.",
        ],
        "evitar": [
            "Hablar de cosas poco relevantes.",
            "Ser evasivo y poco claro.",
            "Parecer desorganizado.",
        ],
    },
    "I": {
        "descripcion": "una persona carismática, entusiasta, amigable, expresiva y política",
        "hacer": [
            "Establezca un ambiente cálido y amistoso.",
            "No entre en demasiados detalles (póngalos por escrito).",
            "Haga preguntas sobre sus \"sensaciones\" respecto a algo, para conocer sus opiniones.",
        ],
        "evitar": [
            "Evitar ser distante, frío o callado.",
            "Controlar la conversación.",
            "Pasar por alto hechos, alternativas, abstracciones.",
        ],
    },
    "S": {
        "descripcion": "una persona paciente, predecible, fiable, constante, relajada y modesta",
        "hacer": [
            "Empiece con un comentario personal que rompa el hielo.",
            "Presente su idea suavemente, sin tono amenazador.",
            "Haga preguntas tipo \"¿cómo?\" para descubrir sus opiniones.",
        ],
        "evitar": [
            "Ser impetuoso y precipitado, yendo en seguida al asunto.",
            "Ser dominante o exigente.",
            "Forzarle a responder rápidamente a los objetivos de usted.",
        ],
    },
    "C": {
        "descripcion": "una persona diplomática, ordenada, conservadora, perfeccionista, cuidadosa y obediente",
        "hacer": [
            "Prepare su tema por adelantado.",
            "Mantenga la conversación en el ámbito profesional.",
            "Sea cumplidor y realista.",
        ],
        "evitar": [
            "Ser desconcertante, dejar cosas al azar, ser informal, hablar en voz alta.",
            "Presionar demasiado o ser poco realista con los plazos.",
            "Ser desorganizado o confuso.",
        ],
    },
}


# ------------------------------- Descriptores --------------------------------
# Página "DESCRIPTORES": banco fijo de 8 palabras "si este factor está
# elevado" + 8 palabras "si este factor está disminuido" por cada letra (64
# palabras en total) -- confirmado byte-a-byte idéntico entre 3 personas
# distintas. En el informe real se resalta un subconjunto por persona; el
# criterio exacto no se puede recuperar de un PDF de texto plano (haría
# falta inspeccionar el grosor de fuente carácter a carácter), así que se
# aproxima resaltando el bloque "alto" o "bajo" completo según la banda de
# esa persona en cada letra (ver descriptores_resaltados más abajo).
DESCRIPTORES = {
    "D": {
        "alto": ["Impulsor", "Ambicioso", "Pionero", "Voluntarioso", "Decidido", "Competitivo", "Determinado", "Atrevido"],
        "bajo": ["Calculador", "Cooperador", "Indeciso", "Cauteloso", "Agradable", "Modesto", "Pacífico", "Recatado"],
    },
    "I": {
        "alto": ["Inspirador", "Carismático", "Entusiasta", "Persuasivo", "Convincente", "Equilibrado", "Optimista", "Confiado"],
        "bajo": ["Reflexivo", "Electivo", "Calculador", "Escéptico", "Lógico", "Suspicaz", "Práctico", "Incisivo"],
    },
    "S": {
        "alto": ["Relajado", "Pasivo", "Paciente", "Posesivo", "Predecible", "Consistente", "Equilibrado", "Estable"],
        "bajo": ["Movible", "Activo", "Inquieto", "Impaciente", "Orientado a la presión", "Ansioso", "Flexible", "Impulsivo"],
    },
    "C": {
        "alto": ["Cauteloso", "Cuidadoso", "Riguroso", "Sistemático", "Exacto", "Abierto", "Objetivo", "Diplomático"],
        "bajo": ["Firme", "Independiente", "Voluntarioso", "Obstinado", "No sistemático", "Desinhibido", "Arbitrario", "Inflexible"],
    },
}


def descriptores_resaltados(perfil):
    """perfil: {'D':.., 'I':.., 'S':.., 'C':..} (normalmente el Adaptado).
    Devuelve {'D': 'alto'|'bajo'|None, ...} -- qué bloque de 8 palabras
    resaltar por letra (None si está en banda 'medio', no se resalta
    ninguno de los dos extremos)."""
    resultado = {}
    for letra, valor in perfil.items():
        b = banda(valor)
        resultado[letra] = "alto" if b == "alto" else ("bajo" if b == "bajo" else None)
    return resultado


# --------------------------- Jerarquía Conductual ----------------------------
# Página "JERARQUÍA CONDUCTUAL": lista fija de 12 factores con su definición
# de una línea -- confirmado que el CONJUNTO de 12 es el mismo para
# cualquier persona; lo que cambia por persona es el ORDEN (ranking) y los
# valores numéricos de cada uno (ver disc_jerarquia.py para esa parte, aún
# no implementada -- Fase C del plan).
FACTORES_JERARQUIA = [
    {"clave": "entorno_organizado", "nombre": "Entorno de Trabajo Organizado", "definicion": "Mantiene orden específico en sus actividades diarias"},
    {"clave": "analisis_datos", "nombre": "Análisis de Datos", "definicion": "Compila, confirma y organiza la información con precisión"},
    {"clave": "consistencia", "nombre": "Consistencia", "definicion": "Realiza su trabajo de manera constante en situaciones repetitivas"},
    {"clave": "cumplimiento_normas", "nombre": "Cumplimiento de Normas", "definicion": "Cumple estrictamente reglas, normas o métodos establecidos"},
    {"clave": "persistencia", "nombre": "Persistencia", "definicion": "Finaliza tareas pese a desafíos o resistencia"},
    {"clave": "orientado_personas", "nombre": "Orientado a las Personas", "definicion": "Genera afinidad con una amplia variedad de personas"},
    {"clave": "orientacion_cliente", "nombre": "Orientación al Cliente", "definicion": "Identifica y satisface las expectativas del cliente"},
    {"clave": "competitividad", "nombre": "Competitividad", "definicion": "Muestra tenacidad y deseo de ganar"},
    {"clave": "urgencia", "nombre": "Urgencia", "definicion": "Decisión, respuesta y acción rápida"},
    {"clave": "versatilidad", "nombre": "Versatilidad", "definicion": "Se adapta con facilidad a diversas situaciones"},
    {"clave": "interaccion", "nombre": "Interacción", "definicion": "Se comunica con frecuencia y mantiene trato cordial"},
    {"clave": "cambio_frecuente", "nombre": "Cambio Frecuente", "definicion": "Cambia rápidamente de una tarea a otra"},
]


# ------------------------ Rueda de Perfiles Profesionales ---------------------
# Página "RUEDA DE PERFILES PROFESIONALES": fondo fijo (8 sectores + letras
# de eje), confirmado idéntico (mismas coordenadas) en las 3 personas
# comparadas.
#
# TTI subdivide además cada uno de estos 8 sectores en un anillo de 60
# posiciones con nombres combinados (p.ej. "COORDINADOR ANALÍTICO"). Se
# intentó reconstruir esa numeración exacta y NO se pudo validar: probada
# contra los datos reales de una persona (Saúl Vásquez, cuya posición TTI
# real -- (21) COORDINADOR ANALÍTICO en Natural, (22) ANALIZADOR COORDINADOR
# en Adaptado -- ya conocíamos), la fórmula de ángulo more abajo sitúa
# correctamente a esa persona muy cerca del sector COORDINADOR (que es
# donde TTI también la sitúa), pero el NÚMERO exacto de posición (21/22)
# no coincide con lo que da una división uniforme en 60 partes -- es
# evidente que la numeración real de TTI no es una simple división angular
# uniforme, y con solo 1-2 puntos de referencia no hay forma fiable de
# reconstruir su fórmula exacta. Por eso aquí SOLO se usan los 8 sectores
# principales (bien validados: reproducen exactamente las 8 esquinas
# conocidas) y se ubica a cada persona por el sector más cercano, sin
# fingir una posición numerada de 1 a 60 que no se puede verificar.
SECTORES_RUEDA = [
    {"nombre": "IMPLEMENTADOR", "angulo": 90},
    {"nombre": "CONDUCTOR", "angulo": 47},
    {"nombre": "PERSUASOR", "angulo": 3},
    {"nombre": "PROMOTOR", "angulo": -43},
    {"nombre": "RELACIONADOR", "angulo": -91},
    {"nombre": "COLABORADOR", "angulo": -138},
    {"nombre": "COORDINADOR", "angulo": 177},
    {"nombre": "ANALIZADOR", "angulo": 133},
]
EJES_RUEDA = {"C": "top-left", "D": "top-right", "I": "bottom-right", "S": "bottom-left"}


def _angulo_perfil(perfil):
    """Ángulo (grados, -180 a 180) de esta persona en la Rueda -- validado:
    reproduce exactamente los 8 sectores de SECTORES_RUEDA cuando se le pasa
    un perfil "puro" de una sola letra o de una pareja de letras adyacente."""
    x = (perfil.get("D", 0) + perfil.get("I", 0)) - (perfil.get("S", 0) + perfil.get("C", 0))
    y = (perfil.get("D", 0) + perfil.get("C", 0)) - (perfil.get("I", 0) + perfil.get("S", 0))
    return math.degrees(math.atan2(y, x))


def sector_mas_cercano(perfil):
    """Devuelve (angulo, sector_principal, sector_secundario) -- el sector
    de SECTORES_RUEDA más cercano al ángulo de esta persona, y el segundo
    más cercano (para dar una idea de hacia qué otro sector se inclina)."""
    angulo = _angulo_perfil(perfil)

    def distancia_angular(a, b):
        d = abs(a - b) % 360
        return min(d, 360 - d)

    ordenados = sorted(SECTORES_RUEDA, key=lambda s: distancia_angular(angulo, s["angulo"]))
    return angulo, ordenados[0]["nombre"], ordenados[1]["nombre"]


# --------------------------- Gráfico Contínuo Conductual -----------------------
# Página "GRÁFICO CONTÍNUO CONDUCTUAL": 4 barras horizontales, cada una con
# sus dos etiquetas de extremo fijas (confirmado terminología estándar TTI,
# consistente con el resto del informe) -- solo los marcadores numéricos
# cambian por persona (Fase D).
CONTINUUM_EJES = {
    "D": {"titulo": "Problemas y Retos", "izquierda": "Reflexivo", "derecha": "Directo"},
    "I": {"titulo": "Personas y Relaciones", "izquierda": "Reservado", "derecha": "Influyente"},
    "S": {"titulo": "Paso y Ritmo", "izquierda": "Dinámico", "derecha": "Estable"},
    "C": {"titulo": "Procedimientos y Reglas", "izquierda": "Pionero", "derecha": "Cumplidor"},
}
