# Backend FastAPI — Surveillance Pollution Dakar (DIC2)
FROM python:3.11-slim

# Utilisateur non-root (règle Docker du projet)
RUN useradd --create-home --shell /usr/sbin/nologin apiuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER apiuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
