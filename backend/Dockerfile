# Backend FastAPI — Surveillance Pollution Dakar (DIC2)
FROM python:3.11-slim

# Dépendances système pour psycopg2, cryptography, bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root (règle Docker du projet)
RUN useradd --create-home --shell /usr/sbin/nologin apiuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY app ./app

USER apiuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
