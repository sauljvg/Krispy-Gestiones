"""Rejilla de posiciones para ventanas visibles de Chrome (Uber Eats) cuando corren
varios procesos del scraper en paralelo -- si todos usaran el mismo punto, sus ventanas
quedarían apiladas exactamente encima unas de otras y un challenge real solo sería
visible/resoluble en la que quedara arriba del todo (ver BaseAggregatorScraper en
scrapers/base.py). Compartida entre buscar_limite_cobertura.py (--ventana-slot) y
daemon.py (--worker-index), para no mantener la misma rejilla en dos sitios."""

# Rejilla 4 columnas x 2 filas (8 celdas) sobre el segundo monitor (x: 1920-3840,
# y: 0-1032 -- WorkingArea real del equipo, deja fuera la barra de tareas). Subida de 6
# a 8 procesos en paralelo el 10/08 (CPU/RAM sin problemas) -- celdas más pequeñas
# (480x516, ventana 440x480) para que quepan las 8 sin salirse del monitor.
COLUMNAS, FILAS = 4, 2
CELDA_ANCHO, CELDA_ALTO = 480, 516
MONITOR_X0, MONITOR_Y0 = 1920, 0
TAMANO_VENTANA = "440,480"


def calcular_posicion_ventana(slot: int) -> tuple[str, str]:
    """Devuelve (posicion, tamano) listos para BaseAggregatorScraper.posicion_ventana_visible
    / tamano_ventana_visible, repartiendo `slot` en la rejilla de arriba."""
    slot = slot % (COLUMNAS * FILAS)
    col, fila = slot % COLUMNAS, slot // COLUMNAS
    x = MONITOR_X0 + col * CELDA_ANCHO
    y = MONITOR_Y0 + fila * CELDA_ALTO
    return f"{x},{y}", TAMANO_VENTANA
