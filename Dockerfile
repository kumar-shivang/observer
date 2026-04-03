FROM python:3.12-slim

# nvidia-smi is provided at runtime via --gpus all; we just need the CLI path to exist.
# Install minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor/ monitor/

# Data volume mount point
RUN mkdir -p /data

# Port exposed by FastAPI (Prometheus + JSON API)
EXPOSE 8000

CMD ["python", "-m", "monitor.main"]
