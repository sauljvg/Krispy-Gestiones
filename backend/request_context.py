from contextvars import ContextVar

# Tiendas a las que el usuario de la petición actual tiene acceso en Reseñas.
# Lista vacía = sin restricción. La rellena un middleware en main.py al
# principio de cada petición, y build_filters()/analytics.py la leen sin
# necesidad de pasarla como parámetro por cada endpoint.
tiendas_permitidas_actual: ContextVar[list[str]] = ContextVar("tiendas_permitidas_actual", default=[])
