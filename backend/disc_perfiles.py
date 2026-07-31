"""Contenido descriptivo propio (no copiado de TTI Success Insights) para
cada uno de los 12 perfiles DISC posibles -- combinacion de letra primaria +
secundaria, en ese orden (p.ej. "DI" = Dominancia primaria, Influencia
secundaria; "ID" = Influencia primaria, Dominancia secundaria).

Se basa en la teoria general del modelo DISC (Marston, 1928 -- de dominio
publico, no exclusiva de TTI), redactado desde cero para este proyecto. NO
reproduce el texto de los informes oficiales de TTI Success Insights.

Cuando el algoritmo calcula el tipo de una persona (ver
DISCCalculator.obtener_tipo_disc), este diccionario es la fuente del
"informe" que se le muestra/exporta -- un informe por PERFIL, no
personalizado palabra por palabra por individuo."""

PERFILES_DISC = {
    "DI": {
        "nombre": "El Persuasor",
        "resumen": "Decidido y orientado a resultados, con la energía social suficiente para arrastrar a otros hacia su visión.",
        "caracteristicas": [
            "Le gusta liderar y tomar la iniciativa",
            "Comunicador seguro, convence más que impone",
            "Impaciente con los procesos lentos",
            "Busca el reto y el reconocimiento a la vez",
            "Toma decisiones rápido, a veces sin todos los datos",
        ],
        "fortalezas": ["Capacidad de arrastre y motivación de equipos", "Orientación clara a resultados", "Buen negociador", "Se adapta rápido a situaciones nuevas"],
        "areas_de_mejora": ["Puede saltarse el detalle por ir rápido", "Escucha menos de lo que habla bajo presión", "Le cuesta delegar el control"],
        "motivadores": ["Retos visibles y medibles", "Autonomía para decidir", "Reconocimiento público del logro"],
        "bajo_presion": "Se vuelve más directo y puede sonar brusco; necesita un objetivo claro para canalizar la urgencia.",
        "como_comunicarse": ["Ve directo al grano, sin rodeos", "Dale margen de decisión, no solo instrucciones", "Reconoce los logros delante de otros"],
        "entorno_ideal": "Entornos dinámicos con autonomía real y contacto frecuente con personas.",
    },
    "DS": {
        "nombre": "El Ejecutor Constante",
        "resumen": "Combina el impulso a la acción con una lealtad y paciencia poco habituales en un perfil dominante.",
        "caracteristicas": [
            "Decidido pero más calmado que un D puro",
            "Cumple lo que promete, es de fiar",
            "Prefiere avanzar paso a paso una vez decide el rumbo",
            "Defiende a su equipo con firmeza",
            "No busca protagonismo, busca resultados sólidos",
        ],
        "fortalezas": ["Estabilidad bajo carga de trabajo alta", "Buen equilibrio entre firmeza y cercanía", "Constancia para terminar lo que empieza"],
        "areas_de_mejora": ["Puede tardar en adaptarse a cambios bruscos de rumbo", "A veces evita el conflicto que sí haría falta afrontar"],
        "motivadores": ["Estabilidad del equipo", "Objetivos claros a medio plazo", "Confianza y autonomía otorgada por su responsable"],
        "bajo_presion": "Se vuelve más callado y metódico; necesita tiempo para procesar antes de actuar.",
        "como_comunicarse": ["Dale tiempo para asimilar antes de pedir una decisión", "Sé consistente, no cambies de criterio sin explicar por qué", "Valora en privado, no solo en público"],
        "entorno_ideal": "Equipos estables donde pueda construir a medio-largo plazo, con margen de autonomía.",
    },
    "DC": {
        "nombre": "El Estratega Exigente",
        "resumen": "Ambicioso y orientado a resultados, pero con un estándar de calidad alto que no está dispuesto a rebajar.",
        "caracteristicas": [
            "Decidido y analítico a la vez",
            "Exigente consigo mismo y con los demás",
            "Prefiere hacerlo bien a hacerlo rápido, aunque también quiere velocidad",
            "Le cuesta aceptar soluciones a medias",
            "Independiente, prefiere resolver a su manera",
        ],
        "fortalezas": ["Combina visión de resultado con rigor técnico", "Detecta riesgos y errores antes que la mayoría", "Alto estándar propio"],
        "areas_de_mejora": ["Puede ser percibido como frío o excesivamente crítico", "El perfeccionismo le puede frenar la velocidad", "Le cuesta delegar tareas que le importan"],
        "motivadores": ["Problemas complejos que resolver", "Autonomía técnica", "Reconocimiento a la calidad del trabajo, no solo al resultado"],
        "bajo_presion": "Se vuelve más crítico y controlador; necesita datos concretos para relajar la tensión.",
        "como_comunicarse": ["Aporta datos y argumentos, no solo opiniones", "No le pidas velocidad sin dejarle margen de calidad", "Reconoce el rigor de su trabajo, no solo el resultado final"],
        "entorno_ideal": "Roles con responsabilidad técnica real y objetivos ambiciosos pero bien definidos.",
    },
    "ID": {
        "nombre": "El Líder Carismático",
        "resumen": "Sociable y persuasivo, capaz de tomar el control de una situación cuando hace falta sin perder la cercanía.",
        "caracteristicas": [
            "Extrovertido, genera buen ambiente de forma natural",
            "Capaz de asumir el mando si nadie más lo hace",
            "Optimista, contagia entusiasmo",
            "Le motiva más la gente que los procesos",
            "Improvisa bien, no siempre planifica en detalle",
        ],
        "fortalezas": ["Gran capacidad de conexión e influencia", "Iniciativa y capacidad de decisión", "Buen gestor de la motivación del equipo"],
        "areas_de_mejora": ["Puede perder el foco en el detalle operativo", "El entusiasmo inicial no siempre se sostiene en el tiempo", "Puede imponer su ritmo sin darse cuenta"],
        "motivadores": ["Visibilidad y trato con personas", "Proyectos nuevos con impacto social", "Libertad para liderar a su manera"],
        "bajo_presion": "Se dispersa más de lo habitual; necesita estructura externa para no perder el foco.",
        "como_comunicarse": ["Dale espacio para expresarse antes de entrar en detalles", "Convierte las ideas en pasos concretos con él/ella", "Aprovecha su entusiasmo, pero ponle plazos claros"],
        "entorno_ideal": "Entornos sociales, variados, con contacto humano constante y poca rutina.",
    },
    "IS": {
        "nombre": "El Conector Cercano",
        "resumen": "Cálido, sociable y genuinamente interesado en las personas, con la paciencia de un buen colaborador.",
        "caracteristicas": [
            "Empático, se preocupa de verdad por el equipo",
            "Buen mediador en conflictos",
            "Prefiere el consenso a la imposición",
            "Leal y constante en sus relaciones de trabajo",
            "Evita la confrontación directa cuando puede",
        ],
        "fortalezas": ["Cohesión de equipo y buen ambiente", "Capacidad de escucha genuina", "Fiabilidad y calidez a partes iguales"],
        "areas_de_mejora": ["Le cuesta decir que no", "Puede posponer decisiones difíciles por no incomodar", "Necesita más tiempo para adaptarse a cambios rápidos"],
        "motivadores": ["Buen ambiente de equipo", "Sentirse apreciado y necesario", "Estabilidad en las relaciones de trabajo"],
        "bajo_presion": "Se retrae y evita el conflicto todavía más; necesita sentirse respaldado para actuar.",
        "como_comunicarse": ["Empieza por lo personal antes de lo operativo", "Dale seguridad explícita, no des el aprecio por sobreentendido", "No le fuerces a decidir en caliente delante de otros"],
        "entorno_ideal": "Equipos estables, colaborativos, con buen clima y relaciones de confianza duraderas.",
    },
    "IC": {
        "nombre": "El Comunicador Preciso",
        "resumen": "Sociable y expresivo, pero con una atención al detalle que no es habitual en un perfil tan extrovertido.",
        "caracteristicas": [
            "Comunica con entusiasmo, pero cuida lo que dice",
            "Le importa quedar bien y hacerlo bien a la vez",
            "Organizado dentro de su espontaneidad",
            "Sensible a cómo lo perciben los demás",
            "Combina creatividad con cierto perfeccionismo",
        ],
        "fortalezas": ["Comunicación cuidada y efectiva", "Creatividad con criterio", "Buena imagen ante clientes y equipo"],
        "areas_de_mejora": ["La necesidad de aprobación puede frenar decisiones", "Puede sobrecargarse por querer cuidar cada detalle", "Le cuesta dar feedback negativo directo"],
        "motivadores": ["Reconocimiento social a un trabajo bien hecho", "Proyectos donde pueda combinar creatividad y calidad", "Relaciones de confianza con su equipo"],
        "bajo_presion": "Se vuelve más autocrítico y busca validación externa antes de avanzar.",
        "como_comunicarse": ["Da feedback concreto, no solo general", "Reconoce tanto el resultado como el cuidado puesto en él", "Sé claro si algo no está bien, sin rodeos pero con tacto"],
        "entorno_ideal": "Roles con visibilidad, trato con personas y espacio para cuidar el detalle de su trabajo.",
    },
    "SD": {
        "nombre": "El Apoyo Firme",
        "resumen": "Paciente y confiable, con capacidad real de tomar la iniciativa cuando la situación lo exige de verdad.",
        "caracteristicas": [
            "Estable y predecible en su forma de trabajar",
            "No busca protagonismo, pero no lo rehúye si hace falta",
            "Firme en sus principios una vez decide algo",
            "Buen ejecutor de planes ya definidos",
            "Le cuesta arrancar sin un marco claro",
        ],
        "fortalezas": ["Fiabilidad y constancia", "Capacidad de asumir responsabilidad cuando se le pide", "Buen equilibrio entre calma y determinación"],
        "areas_de_mejora": ["Puede tardar en reaccionar ante lo inesperado", "Le cuesta imponerse en un primer momento", "Prefiere el terreno conocido al riesgo"],
        "motivadores": ["Estabilidad y previsibilidad", "Confianza explícita de su responsable", "Objetivos claros y alcanzables"],
        "bajo_presion": "Se vuelve más rígido y necesita más tiempo del habitual para decidir.",
        "como_comunicarse": ["Dale tiempo antes de pedir una respuesta inmediata", "Sé concreto con lo que esperas de él/ella", "Reconoce su fiabilidad, no solo los resultados puntuales"],
        "entorno_ideal": "Estructuras estables con procesos claros, donde la constancia se valore tanto como el resultado.",
    },
    "SI": {
        "nombre": "El Colaborador Amigable",
        "resumen": "Calmado y generoso, disfruta genuinamente del trabajo en equipo y de mantener un buen ambiente.",
        "caracteristicas": [
            "Paciente, rara vez pierde la calma",
            "Disponible y servicial con el equipo",
            "Prefiere colaborar a competir",
            "Necesita sentirse parte de algo, no solo cumplir tareas",
            "Se adapta bien al ritmo de los demás",
        ],
        "fortalezas": ["Gran capacidad de trabajo en equipo", "Ambiente de confianza allá donde está", "Buena disposición ante los cambios si se explican bien"],
        "areas_de_mejora": ["Puede evitar el conflicto necesario", "Le cuesta poner límites", "Necesita más guía en tareas muy ambiguas"],
        "motivadores": ["Pertenencia y buen ambiente de equipo", "Reconocimiento genuino, no solo formal", "Trabajo con propósito compartido"],
        "bajo_presion": "Se preocupa por el ambiente antes que por el resultado; puede paralizarse ante el conflicto.",
        "como_comunicarse": ["Cuida el tono, no solo el contenido", "Dale certezas sobre su lugar en el equipo", "Involúcralo en la decisión, no solo informarle del resultado"],
        "entorno_ideal": "Equipos cálidos y colaborativos, con relaciones de confianza y poca confrontación.",
    },
    "SC": {
        "nombre": "El Guardián Metódico",
        "resumen": "Paciente y meticuloso, prefiere hacer las cosas bien y con calma antes que rápido y con riesgo.",
        "caracteristicas": [
            "Constante, cuida cada detalle de su trabajo",
            "Prefiere la estabilidad al cambio constante",
            "Discreto, no busca destacar",
            "Sigue procesos y normas con disciplina",
            "Le cuesta improvisar bajo presión de tiempo",
        ],
        "fortalezas": ["Precisión y fiabilidad sostenidas en el tiempo", "Buen cumplimiento de procesos y estándares", "Calma que transmite seguridad al equipo"],
        "areas_de_mejora": ["El ritmo puede resultar lento para entornos muy dinámicos", "Le cuesta adaptarse a cambios de última hora", "Puede callar desacuerdos por evitar el conflicto"],
        "motivadores": ["Procesos claros y tiempo suficiente para hacerlo bien", "Estabilidad y previsibilidad", "Reconocimiento a la calidad, no solo a la velocidad"],
        "bajo_presion": "Se vuelve más rígido y necesita aún más tiempo para procesar cambios inesperados.",
        "como_comunicarse": ["Avisa con antelación de los cambios", "No le exijas velocidad y precisión a la vez sin margen", "Reconoce su meticulosidad de forma explícita"],
        "entorno_ideal": "Procesos bien definidos, ritmo estable y tiempo suficiente para hacer el trabajo con calidad.",
    },
    "CD": {
        "nombre": "El Analista Decidido",
        "resumen": "Preciso y orientado a datos, con la capacidad de tomar el control y presionar por resultados cuando hace falta.",
        "caracteristicas": [
            "Analítico antes de actuar, pero no se queda solo en el análisis",
            "Exigente con la calidad y con los plazos",
            "Prefiere la lógica a la emoción en la toma de decisiones",
            "Independiente y con criterio propio",
            "Puede ser percibido como distante",
        ],
        "fortalezas": ["Rigor técnico combinado con capacidad de decisión", "Buen gestor de riesgos", "Alto estándar de calidad sin perder de vista el resultado"],
        "areas_de_mejora": ["La exigencia puede generar tensión en el equipo", "Le cuesta delegar sin supervisar de cerca", "Poca paciencia con la ambigüedad"],
        "motivadores": ["Problemas técnicos complejos", "Autonomía y criterio propio", "Objetivos medibles con estándar de calidad alto"],
        "bajo_presion": "Se vuelve más controlador y crítico; necesita datos fiables para ceder el control.",
        "como_comunicarse": ["Argumenta con datos, no con impresiones", "Respeta su criterio técnico antes de cuestionarlo", "Sé directo, no necesita rodeos"],
        "entorno_ideal": "Roles técnicos con autonomía real y objetivos exigentes pero bien definidos.",
    },
    "CI": {
        "nombre": "El Perfeccionista Sociable",
        "resumen": "Meticuloso y cuidadoso, con un lado más cálido y comunicativo que equilibra su exigencia.",
        "caracteristicas": [
            "Detallista, pero también disfruta del trato con personas",
            "Cuida tanto la forma como el fondo de su trabajo",
            "Sensible a la crítica, aunque no lo muestre",
            "Prefiere hacerlo bien aunque tarde un poco más",
            "Busca la aprobación de su entorno cercano",
        ],
        "fortalezas": ["Calidad de trabajo con buena relación con el equipo", "Capacidad de explicar lo técnico de forma cercana", "Cuidado genuino del detalle"],
        "areas_de_mejora": ["El perfeccionismo puede ralentizar la entrega", "Le cuesta separar la crítica al trabajo de la crítica personal", "Puede evitar conflictos por mantener la buena relación"],
        "motivadores": ["Reconocimiento tanto a la calidad como a la persona", "Ambiente de trabajo cordial", "Proyectos donde el detalle importe de verdad"],
        "bajo_presion": "Se vuelve más autoexigente y busca aprobación antes de dar algo por terminado.",
        "como_comunicarse": ["Da feedback con cuidado, separando lo profesional de lo personal", "Reconoce el esfuerzo además del resultado", "Dale plazos realistas para mantener su nivel de calidad"],
        "entorno_ideal": "Equipos con buen trato personal, donde el trabajo bien hecho se valore sin prisas excesivas.",
    },
    "CS": {
        "nombre": "El Especialista Paciente",
        "resumen": "Detallista, cuidadoso y constante; prefiere la precisión y la calma antes que la velocidad.",
        "caracteristicas": [
            "Metódico, sigue procesos con disciplina",
            "Paciente, rara vez se apresura",
            "Prefiere la certeza a la improvisación",
            "Discreto, trabaja bien sin necesitar reconocimiento constante",
            "Le cuesta tomar decisiones con información incompleta",
        ],
        "fortalezas": ["Precisión sostenida en el tiempo", "Gran capacidad de trabajo autónomo y concentrado", "Fiabilidad total en tareas de largo recorrido"],
        "areas_de_mejora": ["Ritmo lento para entornos de alta presión", "Le cuesta adaptarse a cambios de criterio frecuentes", "Puede evitar exponer su opinión en público"],
        "motivadores": ["Tiempo suficiente para hacerlo bien", "Procesos claros y estables", "Trabajo con sentido técnico o de especialización"],
        "bajo_presion": "Se paraliza más de lo habitual; necesita información completa para volver a avanzar con seguridad.",
        "como_comunicarse": ["No le pidas respuestas inmediatas sobre temas complejos", "Sé consistente en los criterios que le das", "Reconoce su trabajo en privado, no necesita el foco público"],
        "entorno_ideal": "Trabajo especializado, con procesos estables y tiempo suficiente para la precisión.",
    },
}


def obtener_perfil(tipo_disc):
    return PERFILES_DISC.get(tipo_disc)
