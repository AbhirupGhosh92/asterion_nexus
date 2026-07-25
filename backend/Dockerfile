FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Cloud Run injects $PORT (defaults to 8080)
ENV PORT=8080
CMD ["sh", "-c", "uvicorn fast_api_app:app --host 0.0.0.0 --port ${PORT}"]
