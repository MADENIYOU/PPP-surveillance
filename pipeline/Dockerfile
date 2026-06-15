# syntax=docker/dockerfile:1
# ─── Étage build : compile les dépendances dans un venv isolé ────────────────
FROM python:3.11-slim AS builder

# gcc/g++ + libpq-dev nécessaires SEULEMENT à la compilation (absents de l'image finale).
# g++ requis par cmdstan (prophet). Confinés à l'étage builder → image finale légère.
RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests \
    gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# ─── Étage final : slim sans toolchain, ne reçoit que le venv + le code ──────
FROM python:3.11-slim

# curl : seule dépendance système runtime (healthcheck des workers)
RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Répertoires persistables (modèles ML, dead-letter, états Kalman)
RUN mkdir -p /app/models /app/dead_letter /app/logs

# Le CMD est surchargé par docker-compose selon le service (workers vs flows)
CMD ["python", "-m", "run_flows"]
