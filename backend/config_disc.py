"""Parametros del algoritmo DISC, ajustados con scipy.optimize (Nelder-Mead)
contra los 21 resultados oficiales TTI disponibles en 'DISC KK'.

IMPORTANTE -- que representa realmente esta comparacion: las 24 respuestas
crudas (hoja "Respuestas" del Excel) NO son la sesion que produjo esos PDF
oficiales. Los PDF son informes de TTI Success Insights, pagados aparte por
cada persona, respondidos directamente en la plataforma de TTI. Las
respuestas del Excel vienen de la herramienta propia (otra sesion, otro
momento, posiblemente otra version del formulario). Es decir: NO se esta
comparando "la misma respuesta procesada de dos formas" -- se esta
comparando dos sesiones distintas de la misma persona, una con nuestra
herramienta y otra con TTI. Es una senal aproximada de si nuestra
herramienta tiende al mismo perfil que TTI para esa persona, no una prueba
estricta de que el algoritmo reproduce el mismo calculo. Con eso en mente,
la mejora medida abajo hay que leerla como "se acerca mas a lo que dice TTI
para la misma persona en otro momento", no como "reproduce exactamente el
mismo resultado".

Antes (pesos originales 4,3,2,1 + factores V2): MAE=16.78 (precision aprox. 83.2%)
Despues (optimizado, sobre la muestra de 11 personas con datos crudos):
  MAE=9.60 (precision aprox. 90.4%)
Validado con leave-one-out (n=11, 9 parametros libres -> riesgo real de
sobreajuste dado el tamano de muestra): MAE fuera de muestra=10.67
(precision aprox. 89.3%) vs MAE baseline fuera de muestra=16.78 (83.2%).
La mejora se sostiene fuera de muestra, no es sobreajuste.

Ver optimization_report.json para el detalle completo (por persona, por
letra, con y sin validacion cruzada).

IMPORTANTE: n=11 es una muestra pequena (solo 11 de los 21 empleados con PDF
oficial tenian tambien sus 24 respuestas crudas registradas). Estos pesos
deberian re-optimizarse en cuanto haya mas empleados con ambos datos
disponibles (respuestas + PDF TTI oficial)."""

# Pesos de puntuacion bruta por posicion de ranking (1a, 2a, 3a, 4a opcion
# elegida por el respondiente, en ese orden) -- NO por letra D/I/S/C.
PESOS_RANKING = [4.0, 3.664, 1.831, 0.424]

# Parametros de la transformacion TTI (polarizacion + normalizacion a un
# total fijo), uno por perfil.
FACTORES_TTI = {
    "adaptado": {"top": 2.794, "bottom": 1.643, "target": 205.3},
    "natural": {"top": 1.488, "bottom": 0.849, "target": 209.45},
}

# Valores previos (algoritmo V2 original), conservados para poder comparar o
# revertir sin tener que ir a buscar el git history.
PESOS_RANKING_ANTERIOR = [4.0, 3.0, 2.0, 1.0]
FACTORES_TTI_ANTERIOR = {
    "adaptado": {"top": 3.5, "bottom": 0.7, "target": 200.0},
    "natural": {"top": 3.8, "bottom": 0.5, "target": 205.0},
}

PRECISION_ANTES_PCT = 83.2
PRECISION_DESPUES_PCT = 90.4
PRECISION_DESPUES_LOO_PCT = 89.3
N_MUESTRA_OPTIMIZACION = 11
