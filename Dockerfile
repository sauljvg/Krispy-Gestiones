FROM python:3.12.13 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app


RUN python -m venv .venv
COPY requirements.txt ./
RUN .venv/bin/pip install -r requirements.txt
FROM python:3.12.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY . .
# La app real vive en backend/main.py (no en la raíz), así que "fastapi run"
# sin argumentos no la encuentra — y aunque la encontrara, por defecto usa
# el puerto 8000, que no coincide con el internal_port=8080 de fly.toml.
# Se arranca directamente con el mismo comando ya probado en local/Replit
# (backend/main.py ya lee el puerto desde la variable de entorno PORT).
CMD ["/app/.venv/bin/python", "backend/main.py"]
