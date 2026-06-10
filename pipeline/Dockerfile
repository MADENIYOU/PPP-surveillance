FROM python:3.11-slim

# Dépendances système (psycopg2 binary, numpy, scikit-learn)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
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
