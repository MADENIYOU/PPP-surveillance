# syntax=docker/dockerfile:1
# Backend FastAPI — Surveillance Pollution Dakar (DIC2)
# ─── Étage build : compile les dépendances dans un venv isolé ────────────────
FROM python:3.11-slim AS builder

# Toolchain pour psycopg2/cryptography/bcrypt si un wheel manque (absent du final)
RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests \
    gcc libpq-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# ─── Étage final : slim, aucune lib système runtime (psycopg2-binary embarque libpq) ─
FROM python:3.11-slim

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Utilisateur non-root (règle Docker du projet)
RUN useradd --create-home --shell /usr/sbin/nologin apiuser

WORKDIR /app
COPY app ./app

USER apiuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
