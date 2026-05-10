FROM python:3.12-slim

WORKDIR /app

# Zainstaluj zależności systemowe
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Skopiuj i zainstaluj zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Skopiuj kod aplikacji
COPY main.py .
COPY services/ ./services/
COPY templates/ ./templates/
COPY static/ ./static/

# Utwórz katalogi na dane (będą podmontowane jako volume)
RUN mkdir -p data/portfolios data/imports data/history_cache data/div_cache

# Expose port
EXPOSE 8000

# Uruchom aplikację
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
