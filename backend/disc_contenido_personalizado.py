"""Contenido PERSONALIZADO del informe DISC -- redacción propia (no copiada
de TTI Success Insights), inspirada en el tono y nivel de detalle de sus
informes "Talent Insights" (que la empresa ya tiene comprados para 22
personas), pero escrita desde cero: no tenemos el motor real de TTI que
decide qué párrafo usar para cada combinación exacta de puntuación, así que
este es NUESTRO propio banco de contenido, organizado por banda de
puntuación en cada eje D/I/S/C (ver disc_contenido_fijo.banda), para que
funcione con cualquiera que haga el test -- no solo con las 22 personas que
ya tienen un informe TTI real.

Dos niveles de detalle según lo que mejor encaja en cada sección:
  - por TIPO completo (12 combos letra primaria+secundaria, igual que
    disc_perfiles.py): Características generales, Valor que aporta.
  - por LETRA PRIMARIA (4 sets): Puntos a tener en cuenta (comunicación),
    Estilo Adaptado, Áreas de mejora.
  - por EJE x BANDA (4 letras x 3 bandas = 12 fragmentos, reutilizables):
    Estilo Natural y Adaptado, Percepciones, Influencias potenciales
    ocultas.
"""

# ==================== Características generales (por tipo) ====================
# Narrativa larga (2 párrafos), con el nombre de pila insertado -- usar
# .format(nombre=...) al leer. Mismo criterio de redacción que
# disc_perfiles.py: teoría general DISC (Marston, 1928, dominio público),
# no el texto de TTI.
CARACTERISTICAS_GENERALES = {
    "DI": (
        "{nombre} combina un fuerte impulso a la acción con una energía social que contagia al resto del "
        "equipo. Toma decisiones con rapidez y prefiere moverse antes que quedarse analizando en exceso; "
        "cuando surge un obstáculo, {nombre} busca primero una salida rápida y solo después, si hace falta, "
        "se detiene a estudiar los detalles. Le motiva ganar y que se le reconozca por ello, y no tiene "
        "problema en tomar la iniciativa cuando nadie más lo hace. Su optimismo es genuino y suele "
        "transmitirlo con facilidad, lo que le da una capacidad de arrastre notable sobre quienes le rodean.\n\n"
        "En la resolución de problemas, {nombre} prioriza la velocidad sobre la exhaustividad: prefiere "
        "probar y ajustar sobre la marcha antes que planificar cada paso de antemano. Comunica con seguridad "
        "y de forma directa, aunque puede sonar brusco cuando tiene prisa. Le cuesta más la rutina que el "
        "cambio, y se aburre con facilidad si un proyecto se estanca. Delegar el control no es su fuerte "
        "natural, aunque sabe que hace falta para escalar cualquier resultado más allá de lo que puede "
        "abarcar solo."
    ),
    "DS": (
        "{nombre} une el impulso a la acción propio de un perfil decidido con una paciencia y lealtad poco "
        "habituales en alguien tan orientado a resultados. No busca protagonismo, pero tampoco lo evita si "
        "la situación lo exige: {nombre} prefiere avanzar con paso firme y constante una vez que ha decidido "
        "el rumbo, en lugar de cambiar de dirección con cada nueva idea que aparece. Es de las personas con "
        "las que se puede contar: cumple lo que promete y defiende a su equipo con la misma firmeza con la "
        "que defendería sus propios objetivos.\n\n"
        "A la hora de tomar decisiones, {nombre} combina cierta urgencia con calma: quiere avanzar, pero no "
        "a cualquier precio, y prefiere una base sólida antes de comprometerse del todo. Comunica de forma "
        "directa pero sin la brusquedad de un perfil D puro, y valora la estabilidad del equipo casi tanto "
        "como el resultado final. Le cuesta adaptarse a cambios de rumbo bruscos una vez que ya se ha "
        "comprometido con un plan, y en ocasiones evita un conflicto que en realidad convendría afrontar."
    ),
    "DC": (
        "{nombre} es ambicioso y orientado a resultados, pero con un estándar de calidad que no está "
        "dispuesto a rebajar por ir más rápido. Decide con rapidez, como cualquier perfil dominante, pero "
        "antes de actuar quiere tener los datos que respalden esa decisión -- la combinación de urgencia y "
        "rigor técnico es precisamente lo que le distingue. {nombre} es exigente consigo mismo en primer "
        "lugar, y eso se traslada de forma natural a lo que espera de los demás.\n\n"
        "Prefiere resolver los problemas a su manera, de forma independiente, y le cuesta aceptar soluciones "
        "a medias solo por cumplir un plazo. Su comunicación es directa y basada en hechos más que en "
        "impresiones; no necesita adornar un argumento si los datos ya lo sostienen. Bajo presión, puede "
        "volverse más crítico y controlador de lo habitual, y quienes no comparten su mismo nivel de "
        "exigencia pueden percibirlo como una persona fría o excesivamente dura de convencer."
    ),
    "ID": (
        "{nombre} es sociable y persuasivo por naturaleza, capaz de generar buen ambiente sin esfuerzo "
        "aparente, pero también de tomar el control de una situación cuando hace falta sin perder esa "
        "cercanía. Le motiva más el trato con las personas que los procesos en sí, y su entusiasmo suele ser "
        "el primer paso de cualquier iniciativa en la que se involucra. {nombre} improvisa bien y confía en "
        "su capacidad de adaptarse sobre la marcha, más que en tener cada detalle planificado de antemano.\n\n"
        "A la hora de decidir, combina intuición con una cierta necesidad de mantener el control del "
        "resultado -- no le gusta quedarse esperando a que otros decidan por él. Comunica con calidez y "
        "energía, y sabe leer el estado de ánimo del grupo casi sin proponérselo. El entusiasmo inicial no "
        "siempre se sostiene igual con el paso del tiempo, y en ocasiones puede imponer su ritmo a los demás "
        "sin darse cuenta de que lo está haciendo."
    ),
    "IS": (
        "{nombre} es cálido, sociable y genuinamente interesado en las personas que le rodean, con la "
        "paciencia añadida de quien prefiere construir relaciones duraderas antes que resultados rápidos. Le "
        "gusta que el ambiente de trabajo sea agradable y colaborativo, y suele ser quien media cuando surge "
        "un desacuerdo dentro del equipo. {nombre} prioriza el consenso sobre la imposición, y su lealtad "
        "hacia las personas con las que trabaja es uno de sus rasgos más constantes.\n\n"
        "Ante un problema, prefiere buscar una solución que no incomode a nadie antes que una que sea "
        "puramente eficiente, y necesita cierto tiempo para adaptarse cuando algo cambia de forma repentina. "
        "Comunica con calidez, empezando casi siempre por lo personal antes de entrar en lo profesional. "
        "Evita la confrontación directa siempre que puede, lo que a veces le lleva a posponer una decisión "
        "difícil solo por no generar tensión."
    ),
    "IC": (
        "{nombre} es sociable y expresivo, pero con una atención al detalle que no es habitual encontrar en "
        "un perfil tan extrovertido. Le importa tanto quedar bien como hacer bien el trabajo, y esa doble "
        "exigencia -- social y técnica -- convive de forma natural en su manera de trabajar. {nombre} "
        "organiza su espontaneidad con más cuidado de lo que aparenta, y es sensible a cómo lo perciben "
        "quienes le rodean.\n\n"
        "Combina creatividad con un cierto perfeccionismo: le gusta proponer ideas nuevas, pero también "
        "cuidar que se ejecuten bien. En la comunicación, es entusiasta pero mide lo que dice, buscando "
        "muchas veces la aprobación de su entorno antes de dar algo por cerrado. Bajo presión, tiende a "
        "volverse más autocrítico de lo habitual y puede sobrecargarse por querer cuidar cada detalle de un "
        "proyecto además de mantener el buen ambiente."
    ),
    "SD": (
        "{nombre} es estable y predecible en su forma de trabajar, con una capacidad real de tomar la "
        "iniciativa cuando la situación de verdad lo exige, aunque no la busque por sistema. No necesita "
        "protagonismo, pero tampoco lo rehúye si hace falta asumir la responsabilidad. {nombre} es firme en "
        "sus principios una vez que decide algo, y suele ser un buen ejecutor de planes ya definidos más que "
        "el primero en proponerlos.\n\n"
        "Ante un problema, prefiere un marco claro antes de actuar -- le cuesta más arrancar sin ese punto "
        "de partida que sostener el esfuerzo una vez en marcha. Comunica con calma, pero puede imponerse con "
        "firmeza si la ocasión lo requiere. Necesita algo más de tiempo del habitual para reaccionar ante lo "
        "inesperado, y prefiere el terreno conocido al riesgo cuando ambas opciones parecen razonables."
    ),
    "SI": (
        "{nombre} es calmado y generoso, y disfruta de verdad del trabajo en equipo y de mantener un buen "
        "ambiente a su alrededor. Rara vez pierde la paciencia, y suele estar disponible para echar una mano "
        "incluso cuando no le corresponde directamente. {nombre} prefiere colaborar a competir, y necesita "
        "sentir que forma parte de algo, no solo cumplir tareas de forma aislada.\n\n"
        "Se adapta bien al ritmo de los demás y evita el conflicto siempre que puede, lo que a veces le lleva "
        "a posponer un límite que convendría poner antes. Comunica con cercanía, cuidando el tono tanto como "
        "el contenido. Bajo presión, tiende a preocuparse más por el ambiente del grupo que por el resultado "
        "en sí, y puede paralizarse si la tensión sube demasiado."
    ),
    "SC": (
        "{nombre} es paciente y meticuloso, y prefiere hacer las cosas bien y con calma antes que rápido y "
        "con riesgo de error. Cuida cada detalle de su trabajo con una constancia que se mantiene incluso "
        "bajo carga alta, y valora la estabilidad y la previsibilidad por encima del cambio constante. "
        "{nombre} es discreto por naturaleza -- no busca destacar, aunque su trabajo suele hablar por sí "
        "solo.\n\n"
        "Sigue procesos y normas con disciplina, y le cuesta improvisar cuando el tiempo aprieta. En la "
        "comunicación, es reservado y necesita sentirse seguro antes de bajar la guardia del todo. Bajo "
        "presión se vuelve todavía más rígido y necesita más tiempo del habitual para procesar cambios "
        "inesperados; puede callar un desacuerdo solo por evitar el conflicto que generaría expresarlo."
    ),
    "CD": (
        "{nombre} es preciso y orientado a datos, con la capacidad de tomar el control y presionar por "
        "resultados cuando la situación lo exige, algo poco habitual en un perfil tan analítico. Analiza "
        "antes de actuar, pero no se queda solo en el análisis: una vez que tiene los datos, decide y avanza. "
        "{nombre} es exigente tanto con la calidad como con los plazos, y prefiere la lógica a la emoción a "
        "la hora de decidir.\n\n"
        "Es independiente y tiene criterio propio, lo que en ocasiones puede hacer que se le perciba como "
        "distante. Comunica con datos y argumentos, no con impresiones, y espera lo mismo de quien tiene "
        "delante. Bajo presión se vuelve más controlador y crítico, y necesita información fiable para "
        "ceder algo de ese control; tiene poca paciencia con la ambigüedad o con quien no ha hecho los "
        "deberes antes de opinar."
    ),
    "CI": (
        "{nombre} es meticuloso y cuidadoso, con un lado más cálido y comunicativo que equilibra su "
        "exigencia natural. Cuida tanto la forma como el fondo de lo que hace, y disfruta genuinamente del "
        "trato con las personas, aunque eso conviva con una atención al detalle que no siempre es fácil de "
        "combinar. {nombre} prefiere hacerlo bien aunque tarde algo más, y busca de forma consciente o "
        "inconsciente la aprobación de su entorno cercano.\n\n"
        "Es sensible a la crítica, aunque no siempre lo muestre. Comunica con cercanía pero cuidando los "
        "detalles de lo que dice, y explica lo técnico de forma accesible para quien no lo domine igual. "
        "Bajo presión, tiende a volverse más autoexigente y busca validación externa antes de dar un trabajo "
        "por terminado; le cuesta separar la crítica al resultado de una crítica personal."
    ),
    "CS": (
        "{nombre} es detallista, cuidadoso y constante, y prefiere la precisión y la calma antes que la "
        "velocidad. Sigue procesos con disciplina y rara vez se apresura, incluso cuando el entorno empuja "
        "en la dirección contraria. {nombre} prefiere la certeza a la improvisación, y es de las personas "
        "que trabajan bien de forma autónoma, sin necesitar reconocimiento constante para mantener el "
        "nivel.\n\n"
        "Le cuesta tomar decisiones con información incompleta, y prefiere esperar a tener el cuadro "
        "completo antes de comprometerse. Comunica de forma reservada, y necesita sentirse seguro del "
        "terreno que pisa antes de exponer una opinión en público. Bajo presión se paraliza más de lo "
        "habitual, y necesita recuperar esa información completa para volver a avanzar con confianza."
    ),
}

# ==================== Valor que aporta a la organización (por tipo) ====================
VALOR_ORGANIZACION = {
    "DI": ["Genera movimiento y energía en cualquier equipo en el que participa.", "Toma decisiones rápido cuando hace falta avanzar.", "Convence más que impone, buen negociador.", "Se adapta con facilidad a situaciones nuevas.", "Asume el liderazgo cuando nadie más lo hace.", "Orientado a resultados visibles y medibles.", "Buen comunicador ante grupos grandes.", "Contagia optimismo incluso en momentos difíciles."],
    "DS": ["Combina impulso a la acción con fiabilidad poco habitual.", "Cumple lo que promete, es de fiar.", "Defiende a su equipo con firmeza.", "Aporta estabilidad bajo carga de trabajo alta.", "Termina lo que empieza sin necesitar supervisión constante.", "Decide con rapidez sin perder de vista al equipo.", "Buen equilibrio entre firmeza y cercanía.", "No busca protagonismo, busca resultados sólidos."],
    "DC": ["Combina visión de resultado con rigor técnico.", "Detecta riesgos y errores antes que la mayoría.", "Alto estándar propio que eleva el nivel del equipo.", "Toma decisiones basadas en datos, no en impresiones.", "Independiente, no necesita supervisión constante.", "Exigente con la calidad sin perder de vista los plazos.", "Buen gestor de proyectos técnicos complejos.", "Aporta rigor a decisiones que otros tomarían a la ligera."],
    "ID": ["Gran capacidad de conexión e influencia sobre el equipo.", "Toma la iniciativa y asume el mando si hace falta.", "Buen gestor de la motivación de otros.", "Se adapta rápido a situaciones cambiantes.", "Genera buen ambiente de forma natural.", "Convence con entusiasmo genuino, no solo con datos.", "Capacidad de improvisar soluciones sobre la marcha.", "Buen puente entre distintos perfiles dentro de un equipo."],
    "IS": ["Cohesión de equipo y buen ambiente allá donde está.", "Capacidad de escucha genuina, no solo aparente.", "Fiabilidad y calidez a partes iguales.", "Buen mediador quando surge un conflicto interno.", "Leal y constante en sus relaciones de trabajo.", "Se adapta bien a los cambios si se explican con calma.", "Aporta estabilidad emocional al equipo en momentos de tensión.", "Buena disposición a ayudar más allá de su rol."],
    "IC": ["Comunicación cuidada y efectiva con clientes y equipo.", "Creatividad con criterio, no solo ideas sueltas.", "Buena imagen y trato ante quien representa a la empresa.", "Cuida tanto el resultado como la relación con quien lo recibe.", "Detecta detalles que otros perfiles más rápidos pasan por alto.", "Combina entusiasmo con una ejecución cuidada.", "Buen comunicador de temas técnicos ante no expertos.", "Se preocupa genuinamente por la percepción del equipo y del cliente."],
    "SD": ["Fiabilidad y constancia poco habituales.", "Capacidad de asumir responsabilidad cuando se le pide.", "Buen ejecutor de planes ya definidos.", "Firme en sus principios una vez decide algo.", "Aporta calma a equipos bajo presión.", "Buen equilibrio entre determinación y paciencia.", "No necesita reconocimiento constante para mantener el nivel.", "Estabilidad que sirve de ancla al resto del equipo."],
    "SI": ["Gran capacidad de trabajo en equipo genuino.", "Ambiente de confianza allá donde está.", "Buena disposición ante los cambios si se explican bien.", "Paciencia poco habitual, rara vez pierde la calma.", "Aporta cohesión y sentido de pertenencia al grupo.", "Colabora sin necesidad de protagonismo.", "Buen apoyo emocional para el resto del equipo.", "Constancia y disponibilidad incluso fuera de su rol directo."],
    "SC": ["Precisión y fiabilidad sostenidas en el tiempo.", "Buen cumplimiento de procesos y estándares.", "Calma que transmite seguridad al resto del equipo.", "Constante incluso en tareas repetitivas o largas.", "Cuida cada detalle sin necesitar que se lo recuerden.", "Aporta previsibilidad a proyectos que la necesitan.", "Buen trabajo autónomo, requiere poca supervisión.", "Prioriza la calidad incluso bajo presión de plazos."],
    "CD": ["Rigor técnico combinado con capacidad real de decisión.", "Buen gestor de riesgos antes de que se conviertan en problemas.", "Alto estándar de calidad sin perder de vista el resultado.", "Objetivo y realista en su análisis de cada situación.", "Presenta los hechos sin dejarse llevar por factores emocionales.", "Independiente, cualificado en su especialidad técnica.", "Detecta huecos e inconsistencias que otros pasan por alto.", "Define, clarifica y prueba antes de dar algo por bueno."],
    "CI": ["Calidad de trabajo combinada con buena relación con el equipo.", "Capacidad de explicar lo técnico de forma cercana.", "Cuidado genuino del detalle en cada entrega.", "Buen equilibrio entre exigencia técnica y trato humano.", "Detecta matices que un perfil más directo pasaría por alto.", "Aporta calidez a entornos muy orientados al resultado.", "Cuida tanto la forma como el fondo de su trabajo.", "Buen puente entre el equipo técnico y el resto de la organización."],
    "CS": ["No confía en decisiones basadas en ideas poco sólidas.", "Puede tomar decisiones sin dejarse llevar por la emoción.", "Bien preparado y cualificado en su especialidad.", "Objetivo y realista en su forma de valorar cada situación.", "Cumplidor e intuitivo con lo que hace falta hacer.", "Siempre preocupado por la buena calidad del trabajo final.", "Define, clarifica, obtiene información, contrasta y prueba.", "Presenta los hechos sin dejarse llevar por factores emocionales."],
}

# ==================== Puntos a tener en cuenta -- comunicación (por letra primaria) ====================
COMUNICACION_SI = {
    "D": ["Ir directo al grano, sin rodeos innecesarios.", "Darle margen de decisión, no solo instrucciones.", "Reconocer sus logros, mejor en público que en privado.", "Presentar retos claros y medibles.", "Respetar su tiempo -- reuniones cortas y con un objetivo claro."],
    "I": ["Empezar por lo personal antes de entrar en lo operativo.", "Dejarle espacio para expresarse antes de pedirle conclusiones.", "Reconocer su aportación delante de otros, no solo en privado.", "Convertir las ideas en pasos concretos junto con él/ella.", "Mantener un tono cercano y positivo, incluso al corregir algo."],
    "S": ["Dar tiempo antes de pedir una respuesta inmediata.", "Ser consistente, no cambiar de criterio sin explicar por qué.", "Empezar con calma, sin ir directo a exigir una decisión.", "Reconocer su trabajo en privado, no solo formalmente.", "Explicar el porqué de un cambio antes de pedir que se adapte."],
    "C": ["Aportar datos y argumentos, no solo opiniones.", "Dar los detalles por escrito, no solo de palabra.", "Avisar con antelación de cualquier cambio de plan.", "Respetar su necesidad de tiempo para analizar antes de decidir.", "Reconocer explícitamente el rigor de su trabajo, no solo el resultado."],
}
COMUNICACION_NO = {
    "D": ["Divagar o dar demasiados rodeos antes de llegar al punto.", "Controlar cada paso sin dejarle margen de decisión.", "Presionar sin dar motivos ni contexto.", "Ser indeciso o cambiar de criterio sin explicación.", "Hacerle perder el tiempo con detalles que no aportan."],
    "I": ["Ser frío, distante o excesivamente formal.", "Entrar en demasiado detalle técnico sin contexto humano.", "Ignorar su aportación o no reconocerla en absoluto.", "Cortar su entusiasmo de forma brusca.", "Forzarle a tomar una decisión en frío, sin margen para hablarlo."],
    "S": ["Exigir una respuesta inmediata sobre algo importante.", "Cambiar de plan de forma brusca y sin explicación.", "Ser agresivo o confrontacional en el tono.", "Ignorar cómo le afecta un cambio al resto del equipo.", "Presionarle en público delante de otros."],
    "C": ["Pedir una opinión sin darle tiempo para analizarla antes.", "Ser impreciso sobre lo que se espera de su trabajo.", "Improvisar sin avisar, dejando cosas al azar.", "Cuestionar su criterio técnico sin aportar datos propios.", "Presionar con plazos poco realistas sin margen de calidad."],
}

# ==================== Estilo Adaptado -- lista (por letra primaria) ====================
ESTILO_ADAPTADO_LISTA = {
    "D": ["Tomar decisiones rápido cuando la situación lo pide.", "Asumir el control cuando nadie más lo hace.", "Enfrentar los problemas de forma directa.", "Fijar objetivos claros y medibles para el equipo.", "Delegar tareas rutinarias para centrarse en lo prioritario.", "Aceptar el riesgo calculado cuando la recompensa lo justifica.", "Comunicar expectativas de forma clara y sin ambigüedad.", "Adaptar el ritmo de trabajo a las prioridades del momento."],
    "I": ["Generar entusiasmo en torno a una idea nueva.", "Construir relaciones de confianza con rapidez.", "Adaptar el discurso según quién tiene delante.", "Motivar al equipo en momentos de bajón.", "Mediar en desacuerdos apelando a lo que une, no a lo que separa.", "Improvisar soluciones cuando el plan original no funciona.", "Dar visibilidad al trabajo del equipo ante otros.", "Mantener el optimismo incluso en situaciones difíciles."],
    "S": ["Mantener la calma cuando el entorno se tensiona.", "Ser constante en tareas largas o repetitivas.", "Escuchar antes de opinar o decidir.", "Adaptarse al ritmo de los demás sin perder el propio.", "Ofrecer apoyo práctico, no solo palabras de ánimo.", "Sostener el ánimo del equipo en momentos de incertidumbre.", "Cumplir compromisos incluso cuando cuesta más de lo previsto.", "Mediar entre posturas distintas buscando el punto en común."],
    "C": ["Seguir procesos establecidos con disciplina.", "Verificar la información antes de darla por buena.", "Detectar errores o inconsistencias antes de que se conviertan en problema.", "Documentar decisiones para que queden claras a futuro.", "Analizar los datos antes de emitir una opinión.", "Mantener estándares de calidad incluso bajo presión de plazos.", "Anticipar riesgos antes de que se materialicen.", "Aportar objetividad en decisiones con carga emocional."],
}

# ==================== Áreas de mejora (por letra primaria) ====================
AREAS_MEJORA = {
    "D": ["Puede saltarse el detalle por ir demasiado rápido.", "Escucha menos de lo que habla, especialmente bajo presión.", "Le cuesta delegar el control una vez que empieza algo.", "Puede sonar brusco sin darse cuenta del efecto que causa.", "Impaciencia con procesos que no puede acelerar.", "Puede tomar decisiones sin consultar a quien debería."],
    "I": ["El entusiasmo inicial no siempre se sostiene en el tiempo.", "Puede perder el foco en el detalle operativo.", "Le cuesta decir que no o poner límites claros.", "Puede sobreestimar lo comprometidos que están los demás.", "Organización personal por debajo de su capacidad real.", "Evita conversaciones difíciles por no romper el buen ambiente."],
    "S": ["Le cuesta decir que no cuando debería.", "Puede posponer decisiones difíciles por no incomodar.", "Necesita más tiempo del habitual para adaptarse a cambios rápidos.", "Evita el conflicto incluso cuando haría falta afrontarlo.", "Puede acumular carga de trabajo por no delegar ni pedir ayuda.", "Le cuesta imponerse cuando la situación lo requiere."],
    "C": ["El perfeccionismo puede ralentizar la entrega.", "Le cuesta decidir con información incompleta.", "Puede resultar excesivamente crítico con el trabajo de otros.", "Evita exponer su opinión en público sin estar del todo seguro.", "Ritmo lento para entornos de alta presión o cambio constante.", "Puede priorizar la forma sobre el fondo en exceso."],
}

# ==================== Estilo Natural y Adaptado (por eje x banda) ====================
# Cuatro sub-bloques del informe TTI (Problemas y Retos ~ D, Personas y
# Contactos ~ I, Ritmo y Constancia ~ S, Procedimientos y Normas ~ C). Cada
# uno se rellena con el fragmento que corresponde a la banda de esa persona
# en el eje correspondiente -- el mismo banco de 12 fragmentos se usa dos
# veces por persona (una con su perfil Natural, otra con el Adaptado).
ESTILO_NATURAL_ADAPTADO = {
    "D": {
        "titulo": "Problemas y Retos",
        "bajo": "Prefiere evitar la confrontación directa ante un problema y avanza con cautela, buscando "
                "el consenso antes que imponer una solución propia. Necesita sentirse seguro del terreno "
                "antes de tomar una decisión importante, y prefiere que el riesgo esté acotado de antemano.",
        "medio": "Afronta los problemas con un equilibrio entre iniciativa y prudencia: no espera a que "
                 "otros decidan, pero tampoco se lanza sin sopesar antes las consecuencias. Sabe cuándo "
                 "actuar rápido y cuándo conviene frenar y pedir más información.",
        "alto": "Se lanza a resolver los problemas de frente, sin esperar a tener todos los datos sobre la "
                "mesa. Prefiere actuar y ajustar sobre la marcha antes que quedarse paralizado analizando; "
                "asume el riesgo con naturalidad cuando cree que la recompensa lo justifica.",
    },
    "I": {
        "titulo": "Personas y Contactos",
        "bajo": "Prefiere el trato en profundidad con pocas personas antes que la interacción constante con "
                "muchas. Necesita tiempo a solas para procesar y recargar energía, y no busca ser el centro "
                "de atención en un grupo.",
        "medio": "Se mueve con soltura tanto en el trato individual como en grupo, adaptando su nivel de "
                 "sociabilidad según lo que pide cada situación, sin necesitar constantemente estar "
                 "rodeado de gente ni tampoco evitarlo.",
        "alto": "Disfruta genuinamente del contacto con otras personas y genera vínculos con facilidad, casi "
                "sin proponérselo. Se energiza en el trato social y prefiere trabajar acompañado antes que "
                "en solitario, incluso cuando la tarea no lo requiere estrictamente.",
    },
    "S": {
        "titulo": "Ritmo y Constancia",
        "bajo": "Se adapta con rapidez a los cambios de prioridad y prefiere la variedad a la rutina fija. "
                "Le cuesta mantener el mismo ritmo en tareas muy repetitivas, y funciona mejor cuando puede "
                "alternar entre varios frentes distintos.",
        "medio": "Combina cierta flexibilidad ante el cambio con la capacidad de sostener un ritmo estable "
                 "cuando la tarea lo requiere. No necesita rutina fija, pero tampoco se desestabiliza "
                 "fácilmente si el entorno cambia.",
        "alto": "Prefiere un ritmo de trabajo estable y predecible, y necesita tiempo para adaptarse cuando "
                "algo cambia de forma repentina. Es constante incluso en tareas largas o repetitivas, y "
                "aporta una base de estabilidad muy valiosa para el resto del equipo.",
    },
    "C": {
        "titulo": "Procedimientos y Normas",
        "bajo": "Prefiere la flexibilidad a seguir un procedimiento rígido, y no le incomoda improvisar "
                "cuando la situación lo pide. Puede pasar por alto un detalle formal si eso le permite "
                "avanzar más rápido hacia el resultado.",
        "medio": "Sigue los procedimientos establecidos sin necesitar que se le recuerden, pero también sabe "
                 "cuándo una norma no aporta valor y puede saltársela de forma razonada.",
        "alto": "Sigue reglas, normas y procedimientos con disciplina, y prefiere la certeza de un método "
                "probado antes que la improvisación. Le cuesta avanzar sin un marco claro, y cuida los "
                "detalles formales incluso cuando nadie se lo pide.",
    },
}

# ==================== Percepciones (por eje x banda) ====================
# Página "PERCEPCIONES": tres filas (auto-percepción, bajo presión moderada,
# bajo presión extrema) -- frases cortas, no párrafos.
PERCEPCIONES = {
    "D": {
        "bajo": {"auto": ["Prudente", "Colaborador"], "presion_moderada": ["Indeciso", "Dependiente"], "presion_extrema": ["Sumiso", "Evasivo"]},
        "medio": {"auto": ["Equilibrado", "Realista"], "presion_moderada": ["Cauteloso", "Dubitativo"], "presion_extrema": ["Inseguro", "Vacilante"]},
        "alto": {"auto": ["Decidido", "Seguro de sí mismo"], "presion_moderada": ["Exigente", "Impaciente"], "presion_extrema": ["Autoritario", "Despiadado"]},
    },
    "I": {
        "bajo": {"auto": ["Reflexivo", "Reservado"], "presion_moderada": ["Distante", "Poco expresivo"], "presion_extrema": ["Frío", "Insensible"]},
        "medio": {"auto": ["Sociable", "Moderado"], "presion_moderada": ["Impreciso", "Disperso"], "presion_extrema": ["Superficial", "Voluble"]},
        "alto": {"auto": ["Entusiasta", "Inspirador"], "presion_moderada": ["Excesivamente confiado", "Hablador"], "presion_extrema": ["Vanidoso", "Poco realista"]},
    },
    "S": {
        "bajo": {"auto": ["Dinámico", "Activo"], "presion_moderada": ["Inquieto", "Impaciente"], "presion_extrema": ["Impulsivo", "Errático"]},
        "medio": {"auto": ["Adaptable", "Flexible"], "presion_moderada": ["Cambiante", "Disperso"], "presion_extrema": ["Voluble", "Inconstante"]},
        "alto": {"auto": ["Cumplidor", "Diplomático"], "presion_moderada": ["Reservado", "Pasivo"], "presion_extrema": ["Posesivo", "Testarudo"]},
    },
    "C": {
        "bajo": {"auto": ["Práctico", "Independiente"], "presion_moderada": ["Descuidado", "Poco riguroso"], "presion_extrema": ["Desorganizado", "Arbitrario"]},
        "medio": {"auto": ["Concienzudo", "Erudito"], "presion_moderada": ["Meticuloso", "Quisquilloso"], "presion_extrema": ["Perfeccionista", "Riguroso"]},
        "alto": {"auto": ["Cuidadoso", "Preciso"], "presion_moderada": ["Difícil de complacer", "Defensivo"], "presion_extrema": ["Rígido", "Inflexible"]},
    },
}

# ==================== Potenciadores de la Productividad (por letra primaria) ====================
# Página "POTENCIADORES DE LA PRODUCTIVIDAD" (versión Liderazgo): 2 temas
# por letra primaria, cada uno con su "enfoque preferido" (por qué le cuesta
# a este perfil concretamente) y 3 consejos prácticos para mejorarlo.
POTENCIADORES_PRODUCTIVIDAD = {
    "D": [
        {
            "titulo": "Delegar Tareas Rutinarias",
            "enfoque": "Prefiere mantener el control del resultado, así que le cuesta soltar tareas aunque no aporten valor a su tiempo.",
            "consejos": [
                "Identificar qué tareas repetitivas ocupan tiempo que podría dedicar a decisiones de más impacto.",
                "Delegar el resultado, no cada paso -- confiar en que otros pueden llegar a la misma meta por su propio camino.",
                "Revisar en puntos de control acordados, no supervisando cada detalle sobre la marcha.",
            ],
        },
        {
            "titulo": "Tomar Decisiones Basadas en Datos",
            "enfoque": "Su instinto suele ser bueno, pero decidir solo por intuición aumenta el riesgo de error en decisiones grandes.",
            "consejos": [
                "Reservar unos minutos para contrastar la decisión con al menos un dato objetivo antes de cerrarla.",
                "Pedir una segunda opinión rápida en decisiones de alto impacto, sin que eso frene el ritmo.",
                "Documentar brevemente el porqué de una decisión importante, para poder revisarla después.",
            ],
        },
    ],
    "I": [
        {
            "titulo": "Establecer Plazos y Cumplirlos",
            "enfoque": "El entusiasmo inicial no siempre se traduce en seguimiento hasta el final, y los plazos pueden diluirse.",
            "consejos": [
                "Fijar fechas intermedias, no solo la fecha final, para mantener el ritmo visible.",
                "Anotar los compromisos en el momento en que se adquieren, no confiar solo en la memoria.",
                "Pedir a alguien del equipo que ayude a hacer seguimiento de los plazos comprometidos.",
            ],
        },
        {
            "titulo": "Ser Más Organizado con los Detalles",
            "enfoque": "Prioriza la conversación y el avance general sobre el orden de la información de apoyo.",
            "consejos": [
                "Dedicar un momento fijo del día a ordenar lo pendiente, en vez de dejarlo para 'cuando haya tiempo'.",
                "Usar una lista simple de tareas en vez de confiar en recordarlo todo.",
                "Poner por escrito los acuerdos importantes justo después de cerrarlos.",
            ],
        },
    ],
    "S": [
        {
            "titulo": "Adaptarse a Cambios de Última Hora",
            "enfoque": "Necesita tiempo para asimilar un cambio de plan, y eso puede ralentizar la respuesta cuando urge.",
            "consejos": [
                "Pedir que le avisen con la mayor antelación posible, aunque sea de forma informal.",
                "Preguntar por el motivo del cambio -- entenderlo ayuda a adaptarse más rápido.",
                "Aceptar que no hace falta tener el plan perfecto desde el primer minuto tras el cambio.",
            ],
        },
        {
            "titulo": "Tomar la Iniciativa sin Esperar Instrucciones",
            "enfoque": "Prefiere que le pidan las cosas antes que proponerlas, lo que puede ralentizar el avance de un proyecto.",
            "consejos": [
                "Identificar de antemano en qué situaciones concretas puede decidir sin consultar.",
                "Proponer una opción propia, aunque sea provisional, en vez de esperar a que se la den.",
                "Recordar que pedir perdón después suele costar menos que pedir permiso antes.",
            ],
        },
    ],
    "C": [
        {
            "titulo": "Aceptar la Imperfección cuando el Plazo Aprieta",
            "enfoque": "Su estándar de calidad es alto, y eso puede chocar con plazos que no dan margen para la perfección.",
            "consejos": [
                "Definir de antemano qué nivel de calidad es 'suficiente' para cada entrega, no solo el ideal.",
                "Separar lo que es un error real de lo que es simplemente mejorable.",
                "Marcar un límite de tiempo para revisar un trabajo, en vez de revisarlo hasta que 'se sienta listo'.",
            ],
        },
        {
            "titulo": "Delegar sin Supervisar Cada Detalle",
            "enfoque": "Confía más en su propio criterio que en el ajeno, lo que dificulta soltar el control de una tarea.",
            "consejos": [
                "Explicar el criterio de calidad esperado por adelantado, en vez de corregir después cada detalle.",
                "Aceptar que un resultado distinto al propio no es necesariamente un resultado peor.",
                "Reservar la revisión exhaustiva solo para lo que realmente lo justifica.",
            ],
        },
    ],
}

# ==================== Influencias potenciales ocultas (por eje, siempre el más bajo) ====================
INFLUENCIAS_OCULTAS = {
    "D": [
        "Puede evitar tomar la iniciativa incluso cuando la situación la necesita.",
        "Tiende a posponer decisiones importantes esperando que otro las tome primero.",
        "Puede confundir la prudencia con la pasividad, dejando pasar oportunidades.",
    ],
    "I": [
        "Puede resultar más distante de lo que pretende en el trato con el equipo.",
        "Tiende a compartir menos información de la que sería útil para los demás.",
        "Puede pasar desapercibido en entornos donde la visibilidad importa para avanzar.",
    ],
    "S": [
        "Puede confundir la quietud con la falta de compromiso, sin serlo en realidad.",
        "Tiende a cambiar de prioridad con más frecuencia de la que el equipo puede seguir.",
        "Puede generar sensación de imprevisibilidad si no comunica los cambios de plan.",
    ],
    "C": [
        "Puede avanzar sin verificar del todo la información, generando errores evitables.",
        "Tiende a restar importancia a los detalles formales que otros sí valoran.",
        "Puede parecer despreocupado ante normas o procedimientos que el equipo espera que respete.",
    ],
}
