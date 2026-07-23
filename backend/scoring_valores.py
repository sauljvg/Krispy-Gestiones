"""Motor de cálculo de "Valores y Competencias" — puerto fiel a Python del
Office Script "SCORING KRISPY KREME - GOLD MASTER (V21 - UNIVERSAL)".

Antes, el flujo era: exportar de Forms -> correr el script en Excel a mano
-> subir el resultado (hojas Scoring/Dashboard) a la web. Esto calcula lo
mismo directamente a partir de la hoja "Respuestas" cruda, para que solo
haga falta subir el Excel tal cual sale de Forms — vale igual para Krispy
Kreme que para Saona u otro negocio, porque detecta el cuestionario por sus
preguntas conocidas, no por nombre de tienda/empresa.
"""
import re
import unicodedata

LIKERT_THRESHOLD_FOR_LIE = 75
W_VAL = 0.5
W_COMP = 0.5

LIST_VALUES = ["Integridad", "Positividad", "Generosidad", "Determinación"]
LIST_COMPS = [
    "Atención al detalle", "Capacidad de análisis", "Comunicación", "Liderazgo",
    "Orientación al cliente", "Responsabilidad", "Trabajo bajo presión",
    "Trabajo en equipo", "Adaptabilidad", "Resolución de problemas",
]

# --- Mapeos Likert (idénticos al Office Script) ---
MAP_LIKERT_VALUES = [
    {"txt": "hagolascosas", "dir": 1, "cat": "Integridad"},
    {"txt": "reconozcomis", "dir": 1, "cat": "Integridad"},
    {"txt": "cumplolasreglas", "dir": 1, "cat": "Integridad"},
    {"txt": "evitobeneficiarme", "dir": 1, "cat": "Integridad"},
    {"txt": "digolaverdad", "dir": 1, "cat": "Integridad"},
    {"txt": "prefierodecirlo", "dir": 1, "cat": "Integridad"},
    {"txt": "evitosaltarme", "dir": 1, "cat": "Integridad"},
    {"txt": "laformadehacer", "dir": -1, "cat": "Integridad"},
    {"txt": "intentoseguir", "dir": 1, "cat": "Positividad"},
    {"txt": "mantengoelanimo", "dir": 1, "cat": "Positividad"},
    {"txt": "ensituaciones", "dir": 1, "cat": "Positividad"},
    {"txt": "procuronocontagiarme", "dir": 1, "cat": "Positividad"},
    {"txt": "endiascomplicados", "dir": -1, "cat": "Positividad"},
    {"txt": "lascriticasme", "dir": -1, "cat": "Positividad"},
    {"txt": "meresultadificil", "dir": -1, "cat": "Positividad"},
    {"txt": "suelopensarque", "dir": -1, "cat": "Positividad"},
    {"txt": "ayudoauncompanero", "dir": 1, "cat": "Generosidad"},
    {"txt": "compartoinformacion", "dir": 1, "cat": "Generosidad"},
    {"txt": "intentoecharuna", "dir": 1, "cat": "Generosidad"},
    {"txt": "colaboro", "dir": 1, "cat": "Generosidad"},
    {"txt": "sivoyjusto", "dir": -1, "cat": "Generosidad"},
    {"txt": "ayudaraotros", "dir": -1, "cat": "Generosidad"},
    {"txt": "cadapersona", "dir": -1, "cat": "Generosidad"},
    {"txt": "nosueloinplicarme", "dir": -1, "cat": "Generosidad"},
    {"txt": "nosueloinvolucrarme", "dir": -1, "cat": "Generosidad"},
    {"txt": "sigointentando", "dir": 1, "cat": "Determinación"},
    {"txt": "terminoloque", "dir": 1, "cat": "Determinación"},
    {"txt": "mantengolaconstancia", "dir": 1, "cat": "Determinación"},
    {"txt": "buscootraforma", "dir": 1, "cat": "Determinación"},
    {"txt": "avecesdejo", "dir": -1, "cat": "Determinación"},
    {"txt": "mecuestamantener", "dir": -1, "cat": "Determinación"},
    {"txt": "pierdomotivacion", "dir": -1, "cat": "Determinación"},
    {"txt": "abandonoantes", "dir": -1, "cat": "Determinación"},
]

MAP_LIKERT_COMPS = [
    {"txt": "revisomitrabajo", "dir": 1, "cat": "Atención al detalle"},
    {"txt": "detectofallos", "dir": 1, "cat": "Atención al detalle"},
    {"txt": "suelofijarme", "dir": 1, "cat": "Atención al detalle"},
    {"txt": "comprueboque", "dir": 1, "cat": "Atención al detalle"},
    {"txt": "medoycuenta", "dir": 1, "cat": "Atención al detalle"},
    {"txt": "cuandotengopoco", "dir": -1, "cat": "Atención al detalle"},
    {"txt": "analizoqueha", "dir": 1, "cat": "Capacidad de análisis"},
    {"txt": "intentoencontrar", "dir": 1, "cat": "Capacidad de análisis"},
    {"txt": "sialgonoesta", "dir": 1, "cat": "Capacidad de análisis"},
    {"txt": "cuandohaymucha", "dir": -1, "cat": "Capacidad de análisis"},
    {"txt": "mecuestaanalizar", "dir": -1, "cat": "Capacidad de análisis"},
    {"txt": "intentoexplicar", "dir": 1, "cat": "Comunicación"},
    {"txt": "sinomeentienden", "dir": 1, "cat": "Comunicación"},
    {"txt": "escuchoconatencion", "dir": 1, "cat": "Comunicación"},
    {"txt": "ajustomiforma", "dir": 1, "cat": "Comunicación"},
    {"txt": "meesfuerzoporqueel", "dir": 1, "cat": "Comunicación"},
    {"txt": "tomodecisiones", "dir": 1, "cat": "Liderazgo"},
    {"txt": "avecesdecido", "dir": -1, "cat": "Liderazgo"},
    {"txt": "meresultadificildecirle", "dir": -1, "cat": "Liderazgo"},
    {"txt": "prefieroqueotrosdecidan", "dir": -1, "cat": "Liderazgo"},
    {"txt": "meesfuerzoporentender", "dir": 1, "cat": "Orientación al cliente"},
    {"txt": "procuromantener", "dir": 1, "cat": "Orientación al cliente"},
    {"txt": "buscosolucionesque", "dir": 1, "cat": "Orientación al cliente"},
    {"txt": "buscoresolver", "dir": 1, "cat": "Orientación al cliente"},
    {"txt": "tengoencuenta", "dir": 1, "cat": "Orientación al cliente"},
    {"txt": "cumploconloque", "dir": 1, "cat": "Responsabilidad"},
    {"txt": "asumoresponsabilidades", "dir": 1, "cat": "Responsabilidad"},
    {"txt": "meresponsabilizo", "dir": 1, "cat": "Responsabilidad"},
    {"txt": "avisocontiempo", "dir": 1, "cat": "Responsabilidad"},
    {"txt": "meorganizopara", "dir": 1, "cat": "Responsabilidad"},
    {"txt": "bajopresion", "dir": -1, "cat": "Trabajo bajo presión"},
    {"txt": "ensituationesdemucha", "dir": -1, "cat": "Trabajo bajo presión"},
    {"txt": "ensituacionesdemucha", "dir": -1, "cat": "Trabajo bajo presión"},
    {"txt": "mecuestaordenar", "dir": -1, "cat": "Trabajo bajo presión"},
    {"txt": "enmomentosde", "dir": -1, "cat": "Trabajo bajo presión"},
    {"txt": "mecuestapensar", "dir": -1, "cat": "Trabajo bajo presión"},
    {"txt": "sielequipose", "dir": 1, "cat": "Trabajo en equipo"},
    {"txt": "trabajomejor", "dir": 1, "cat": "Trabajo en equipo"},
    {"txt": "ayudoaqueel", "dir": 1, "cat": "Trabajo en equipo"},
    {"txt": "mecoordino", "dir": 1, "cat": "Trabajo en equipo"},
    {"txt": "compartolainformacionnecesaria", "dir": 1, "cat": "Trabajo en equipo"},
    {"txt": "pidoayuda", "dir": 1, "cat": "Trabajo en equipo"},
    {"txt": "meadaptocuando", "dir": 1, "cat": "Adaptabilidad"},
    {"txt": "meresultasencillo", "dir": 1, "cat": "Adaptabilidad"},
    {"txt": "aceptocambios", "dir": 1, "cat": "Adaptabilidad"},
    {"txt": "meadaptocon", "dir": 1, "cat": "Adaptabilidad"},
    {"txt": "mecuestacambiar", "dir": -1, "cat": "Adaptabilidad"},
    {"txt": "cuandosurge", "dir": 1, "cat": "Resolución de problemas"},
    {"txt": "siunasolucion", "dir": 1, "cat": "Resolución de problemas"},
    {"txt": "anteunproblema", "dir": -1, "cat": "Resolución de problemas"},
]

MAP_RANKING_KEYWORDS = [
    {"txt": "cliente", "cat": "Orientación al cliente", "dir": 1},
    {"txt": "servicio", "cat": "Orientación al cliente", "dir": 1},
    {"txt": "usuario", "cat": "Orientación al cliente", "dir": 1},
    {"txt": "atiendo", "cat": "Orientación al cliente", "dir": 1},
    {"txt": "analiz", "cat": "Capacidad de análisis", "dir": 1},
    {"txt": "entender", "cat": "Capacidad de análisis", "dir": 1},
    {"txt": "evaluo", "cat": "Capacidad de análisis", "dir": 1},
    {"txt": "informacion", "cat": "Capacidad de análisis", "dir": 1},
    {"txt": "cuadra", "cat": "Capacidad de análisis", "dir": 1},
    {"txt": "calma", "cat": "Trabajo bajo presión", "dir": 1},
    {"txt": "presion", "cat": "Trabajo bajo presión", "dir": 1},
    {"txt": "tensa", "cat": "Trabajo bajo presión", "dir": 1},
    {"txt": "comunic", "cat": "Comunicación", "dir": 1},
    {"txt": "escuchar", "cat": "Comunicación", "dir": 1},
    {"txt": "equipo", "cat": "Trabajo en equipo", "dir": 1},
    {"txt": "coordinar", "cat": "Trabajo en equipo", "dir": 1},
    {"txt": "apoyar", "cat": "Trabajo en equipo", "dir": 1},
    {"txt": "incidencia", "cat": "Trabajo en equipo", "dir": 1},
    {"txt": "lider", "cat": "Liderazgo", "dir": 1},
    {"txt": "iniciativa", "cat": "Liderazgo", "dir": 1},
    {"txt": "guiar", "cat": "Liderazgo", "dir": 1},
    {"txt": "inspirar", "cat": "Liderazgo", "dir": 1},
    {"txt": "direccion", "cat": "Liderazgo", "dir": 1},
    {"txt": "adapt", "cat": "Adaptabilidad", "dir": 1},
    {"txt": "ajust", "cat": "Adaptabilidad", "dir": 1},
    {"txt": "cambio", "cat": "Adaptabilidad", "dir": 1},
    {"txt": "solucion", "cat": "Resolución de problemas", "dir": 1},
    {"txt": "resolver", "cat": "Resolución de problemas", "dir": 1},
    {"txt": "practica", "cat": "Resolución de problemas", "dir": 1},
    {"txt": "obstaculo", "cat": "Resolución de problemas", "dir": 1},
    {"txt": "responsabil", "cat": "Responsabilidad", "dir": 1},
    {"txt": "asumo", "cat": "Responsabilidad", "dir": 1},
    {"txt": "avances", "cat": "Responsabilidad", "dir": 1},
    {"txt": "detalle", "cat": "Atención al detalle", "dir": 1},
    {"txt": "calidad", "cat": "Atención al detalle", "dir": 1},
    {"txt": "revisar", "cat": "Atención al detalle", "dir": 1},
    {"txt": "fijarme", "cat": "Atención al detalle", "dir": 1},
]

MAP_STJ = [
    {"colTitle": ["glaseado", "entregable", "formato"], "key": ["cambio", "otra"],
     "targetComp": "Atención al detalle", "scenarioName": "Caso Formato/Glaseado"},
    {"colTitle": ["duda", "procedimiento"],
     "key": ["sencillas", "palabras", "explico", "explic", "paso", "sugiero", "indico", "dudas"],
     "targetComp": "Comunicación", "scenarioName": "Caso Duda/Procedimiento"},
    {"colTitle": ["cobraron", "proveedor", "molesto"], "key": ["solucion", "rapida", "escucho", "desahogarse"],
     "targetComp": "Orientación al cliente", "scenarioName": "Caso Cliente Molesto", "targetValueCheck": "Positividad"},
    {"colTitle": ["quedandoatras", "atras", "cierre"], "key": ["ayudo", "echo", "mano", "ayudar", "ofrezco"],
     "targetComp": "Trabajo en equipo", "scenarioName": "Caso Ayuda Compañero", "targetValueCheck": "Generosidad"},
    {"colTitle": ["maquinade", "sistema", "maquina"],
     "key": ["informo", "alternativas", "aviso", "organizar", "papel", "alternativo", "formato"],
     "targetComp": "Resolución de problemas", "scenarioName": "Caso Sistema/Máquina", "targetValueCheck": "Determinación"},
    {"colTitle": ["cerrarcaja", "presupuesto"], "key": ["reviso", "operaciones", "encuentro", "revisar", "error", "no", "entrego"],
     "targetComp": "Responsabilidad", "scenarioName": "Caso Caja/Presupuesto", "targetValueCheck": "Integridad"},
    {"colTitle": ["coincide", "cifra", "analizando"], "key": ["reviso", "paso", "detengo", "contacto", "consultar", "entender"],
     "targetComp": "Capacidad de análisis", "scenarioName": "Caso Análisis Pedido", "targetValueCheck": "Determinación"},
    {"colTitle": ["teatro", "interrumpiendo", "constantemente"],
     "key": ["indicaciones", "breves", "atiendo", "inversion", "anote", "dudas", "observe"],
     "targetComp": "Liderazgo", "scenarioName": "Caso Liderazgo", "targetValueCheck": "Determinación"},
    {"colTitle": ["bandeja", "incorrecto"], "key": ["aviso", "limpio", "erratas", "disculpas", "envio"],
     "targetComp": "Responsabilidad", "scenarioName": "Caso Error/Bandeja", "targetValueCheck": "Integridad"},
    {"colTitle": ["afluencia", "humanamente"], "key": ["mantengo", "calma", "quedo", "extra", "terminar"],
     "targetComp": "Trabajo bajo presión", "scenarioName": "Caso Sobrecarga", "targetValueCheck": "Determinación"},
]

_NON_ALNUM = re.compile(r"[^a-z0-9]")
_FECHA_CANDIDATAS = ["Hora de finalización", "Hora de finalizacion", "Hora de inicio"]


def _normalize(s):
    if not s:
        return ""
    s = str(s).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _NON_ALNUM.sub("", s)


def _truncate(s, n):
    return s[: n - 1] + "..." if len(s) > n else s


def _col_letter(index):
    dividend = index + 1
    name = ""
    while dividend > 0:
        modulo = (dividend - 1) % 26
        name = chr(65 + modulo) + name
        dividend = (dividend - 1) // 26
    return name


def _likert_points_strict(val_norm, direction):
    base = 0
    # El módulo de Test envía directamente el punto (1-5) en vez del texto
    # de la leyenda — así el admin puede personalizar las etiquetas de la
    # escala sin romper la puntuación, que ya no depende de las palabras
    # exactas "Totalmente de acuerdo" etc. Los Excel de Forms (donde sí
    # viene el texto tal cual) siguen reconociéndose por las ramas de abajo.
    if val_norm in ("1", "2", "3", "4", "5"):
        base = int(val_norm)
    elif "totalmentedeacuerdo" in val_norm:
        base = 5
    elif "totalmenteendesacuerdo" in val_norm:
        base = 1
    elif "nideacuerdo" in val_norm:
        base = 3
    elif "endesacuerdo" in val_norm:
        base = 2
    elif "deacuerdo" in val_norm:
        base = 4
    if base == 0:
        return 0
    if direction == 1:
        if base in (2, 3):
            return 2
        return base
    return {5: 1, 4: 2, 3: 2, 2: 4, 1: 5}.get(base, 0)


def parece_valores_competencias(filas, umbral=15):
    """Heurística para reconocer un export crudo de Valores y Competencias
    por sus preguntas conocidas — no depende del nombre del tipo/empresa,
    para que funcione igual con Krispy Kreme, Saona o el que venga después."""
    if not filas:
        return False
    headers_norm = [_normalize(h) for h in filas[0].keys()]
    keywords = [m["txt"] for m in MAP_LIKERT_VALUES] + [m["txt"] for m in MAP_LIKERT_COMPS]
    matches = sum(1 for hn in headers_norm for kw in keywords if kw in hn)
    return matches >= umbral


def _detectar_columna(headers, headers_norm, exactas, contiene, max_len):
    for h, hn in zip(headers, headers_norm):
        if hn in exactas:
            return h
    for h, hn in zip(headers, headers_norm):
        if any(c in hn for c in contiene) and len(hn) < max_len:
            return h
    return None


def _detectar_fecha(headers, headers_norm):
    for candidata in _FECHA_CANDIDATAS:
        cn = _normalize(candidata)
        for h, hn in zip(headers, headers_norm):
            if hn == cn:
                return h
    for h in headers:
        if any(hint in h.lower() for hint in ("fecha", "hora", "date")):
            return h
    return None


def calcular(filas, columnas_extra=None):
    """Recibe las filas crudas de la hoja "Respuestas" (lista de dicts
    columna->valor, tal como las devuelve read_workbook_sheets) y devuelve
    (scoring_rows, dashboard_rows) — mismas columnas que generaba el script
    de Excel, más "Fecha del test" tomada de la hoja de respuestas.

    columnas_extra: nombres de columna (normalmente preguntas abiertas o de
    "ordenar prioridades" del módulo de Test) que se copian tal cual, sin
    puntuar, a Scoring/Dashboard — así el resultado de cada candidato se ve
    de un vistazo junto al puntaje, sin tener que ir a mirar la hoja
    "Respuestas" aparte. No aplica a los Excel importados a mano (ahí no se
    sabe qué columna es "abierta"): solo se activa cuando lo pide
    explícitamente el módulo de Test, que sí conoce el tipo de cada
    pregunta."""
    if not filas:
        return [], []
    columnas_extra = columnas_extra or set()

    headers = list(filas[0].keys())
    headers_norm = [_normalize(h) for h in headers]

    email_col = _detectar_columna(headers, headers_norm, {"correoelectronico1", "email1"}, ("correo", "email"), 30)
    name_col = _detectar_columna(headers, headers_norm, {"nombreyapellido", "nombrecompleto"}, ("nombre",), 20)
    fecha_col = _detectar_fecha(headers, headers_norm)

    scoring_rows = []
    dashboard_rows = []

    for fila in filas:
        val_scores = {cat: [0, 0] for cat in LIST_VALUES}
        comp_scores = {cat: [0, 0] for cat in LIST_COMPS}
        ranking_scores = {cat: 0 for cat in LIST_COMPS}
        stj_tracker = {cat: {"passed": False, "evaluated": False, "col": "", "snippet": ""} for cat in LIST_COMPS}

        for idx, header in enumerate(headers):
            h_norm = headers_norm[idx]
            ans_raw = fila.get(header)
            ans = "" if ans_raw is None else str(ans_raw)
            ans_norm = _normalize(ans)
            found = False

            for m in MAP_LIKERT_VALUES:
                if m["txt"] in h_norm:
                    pts = _likert_points_strict(ans_norm, m["dir"])
                    if pts > 0:
                        val_scores[m["cat"]][0] += pts
                        val_scores[m["cat"]][1] += 1
                    found = True
                    break
            if found:
                continue

            for m in MAP_LIKERT_COMPS:
                if m["txt"] in h_norm:
                    pts = _likert_points_strict(ans_norm, m["dir"])
                    if pts > 0:
                        comp_scores[m["cat"]][0] += pts
                        comp_scores[m["cat"]][1] += 1
                    found = True
                    break
            if found:
                continue

            for m in MAP_STJ:
                if any(t in h_norm for t in m["colTitle"]):
                    tracker = stj_tracker[m["targetComp"]]
                    tracker["evaluated"] = True
                    tracker["col"] = _col_letter(idx)
                    tracker["snippet"] = _truncate(ans, 40)
                    if any(k in ans_norm for k in m["key"]):
                        comp_scores[m["targetComp"]][0] += 5
                        comp_scores[m["targetComp"]][1] += 1
                        tracker["passed"] = True
                    found = True
                    break
            if found:
                continue

            if "ordenalas" in h_norm or "ordena" in h_norm:
                if not ans:
                    continue
                partes = [p for p in re.split(r"[;,\n]", ans) if len(p.strip()) > 3]
                pts = 4
                for parte in partes:
                    if pts <= 0:
                        break
                    p_norm = _normalize(parte)
                    for m in MAP_RANKING_KEYWORDS:
                        if m["txt"] in p_norm:
                            comp_scores[m["cat"]][0] += pts
                            comp_scores[m["cat"]][1] += 1
                            ranking_scores[m["cat"]] += pts
                            break
                    pts -= 1

        nombre = str(fila.get(name_col) or "Anon") if name_col else "Anon"
        correo = str(fila.get(email_col) or "") if email_col else ""

        final_val_scores = {}
        suma_val = 0.0
        for cat in LIST_VALUES:
            s, c = val_scores[cat]
            score = ((s / c) - 1) / 4 * 100 if c > 0 else 0
            if score < 0:
                score = 0
            final_val_scores[cat] = round(score, 2)
            suma_val += score
        final_val = suma_val / len(LIST_VALUES)

        alerts = []
        for m in MAP_STJ:
            target_val = m.get("targetValueCheck")
            # target_val debe ser uno de los 4 VALORES (no una competencia) —
            # esta comprobación evita que un futuro error de tipeo en
            # targetValueCheck tumbe todo el cálculo de puntuación en vez de
            # simplemente no generar esa alerta concreta.
            if target_val and target_val in final_val_scores and stj_tracker[m["targetComp"]]["evaluated"]:
                val_score = final_val_scores[target_val]
                tr = stj_tracker[m["targetComp"]]
                if val_score >= LIKERT_THRESHOLD_FOR_LIE and not tr["passed"]:
                    alerts.append(f'{target_val} {round(val_score)}% | Falló: {tr["col"]} ("{tr["snippet"]}")')

        temp_comp = []
        final_comp_scores = {}
        suma_comp = 0.0
        for cat in LIST_COMPS:
            s, c = comp_scores[cat]
            score = ((s / c) - 1) / 4 * 100 if c > 0 else 0
            if score < 0:
                score = 0
            final_score = round(score, 2)
            tracker = stj_tracker[cat]
            if tracker["evaluated"] and final_score >= LIKERT_THRESHOLD_FOR_LIE and not tracker["passed"]:
                alerts.append(f'{cat} {round(final_score)}% | Falló: {tracker["col"]} ("{tracker["snippet"]}")')
            final_comp_scores[cat] = final_score
            temp_comp.append((cat, final_score))
            suma_comp += score
        final_comp = suma_comp / len(LIST_COMPS)

        alerts_unicas = list(dict.fromkeys(alerts))
        alerta_detallada = "✅ Coherente" if not alerts_unicas else f"{len(alerts_unicas)} ⚠️ " + "   ".join(alerts_unicas)
        alertas_resumen = "✅" if not alerts_unicas else f"{len(alerts_unicas)} ⚠️"

        max_cat = max(temp_comp, key=lambda x: x[1])
        min_cat = min(temp_comp, key=lambda x: x[1])
        destacados = (
            f"⬆️ {max_cat[0]} ({max_cat[1]})  ⬇️ {min_cat[0]} ({min_cat[1]})"
            if max_cat[1] != min_cat[1] else "— Equilibrado —"
        )

        r_val = round(final_val, 2)
        r_comp = round(final_comp, 2)
        r_global = round(r_val * W_VAL + r_comp * W_COMP, 2)

        if r_global >= 80:
            resultado = "⭐ Excelente"
        elif r_global >= 70:
            resultado = "✅ Alineado"
        else:
            resultado = "❌ No apto"

        adn_ordenado = sorted(
            ((cat, pts) for cat, pts in ranking_scores.items() if pts > 0), key=lambda x: -x[1]
        )
        adn = " > ".join(c for c, _ in adn_ordenado[:3]) if adn_ordenado else "Sin datos"

        fecha_valor = fila.get(fecha_col) if fecha_col else None

        scoring_row = {"Nombre": nombre, "Correo": correo}
        scoring_row.update(final_val_scores)
        scoring_row.update(final_comp_scores)
        scoring_row.update({
            "TOTAL VALORES": r_val, "TOTAL COMP": r_comp, "SCORE GLOBAL": r_global,
            "RESULTADO": resultado, "DESTACADOS": destacados,
            "ALERTA DETALLADA": alerta_detallada, "ADN PRIORIDADES": adn,
        })
        dashboard_row = {
            "Nombre": nombre, "Correo": correo,
            "TOTAL VALORES (50%)": r_val, "TOTAL COMP (50%)": r_comp,
            "SCORE GLOBAL": r_global, "RESULTADO": resultado, "ALERTAS": alertas_resumen,
        }
        if fecha_col:
            scoring_row["Fecha del test"] = fecha_valor
            dashboard_row["Fecha del test"] = fecha_valor

        if columnas_extra:
            for h in headers:
                if h in columnas_extra:
                    valor_extra = fila.get(h)
                    scoring_row[h] = valor_extra
                    dashboard_row[h] = valor_extra

        scoring_rows.append(scoring_row)
        dashboard_rows.append(dashboard_row)

    return scoring_rows, dashboard_rows
