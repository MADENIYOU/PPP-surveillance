FROM python:3.11-slim

# Dépendances système pour scikit-learn, scipy, psycopg2 (multi-arch amd64/arm64)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ gfortran libpq-dev curl libopenblas-dev liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Répertoires persistables (modèles ML, dead-letter, états Kalman)
RUN mkdir -p /app/models /app/dead_letter /app/logs

# Le CMD est surchargé par docker-compose selon le service (workers vs flows)
CMD ["python", "-m", "run_flows"]
