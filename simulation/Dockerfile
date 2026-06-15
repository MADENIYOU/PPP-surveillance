# syntax=docker/dockerfile:1
# ─── Étage build : venv isolé (wheels précompilés, gcc en secours) ───────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# ─── Étage final : slim, aucune lib système runtime ──────────────────────────
FROM python:3.11-slim

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# --duration 0 = boucle infinie (la condition d'arrêt teste `if duration and ...`).
# --broker mosquitto : nom du service sur dakar-net. --headless : pas d'affichage TTY.
# Le CMD est surchargé par docker-compose, ces valeurs servent de défaut.
CMD ["python", "data_generator.py", "--broker", "mosquitto", "--port", "1883", \
     "--duration", "0", "--headless"]
