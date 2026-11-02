# Field Shift WhatsApp assistant. Build from the repo root:  docker build -t field-shift .
FROM python:3.12-slim
WORKDIR /app
COPY requirements-assistant.txt .
RUN pip install --no-cache-dir -r requirements-assistant.txt
COPY src ./src
COPY data/shared ./data/shared
ENV PYTHONUNBUFFERED=1
CMD uvicorn src.assistant.whatsapp:app --host 0.0.0.0 --port ${PORT:-8000}
