FROM python:3.12-slim

WORKDIR /app

# Install deps first so dependency layers cache across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/ ./packages/
COPY services/ ./services/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
