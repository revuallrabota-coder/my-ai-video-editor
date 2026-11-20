FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/whisper_cache

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffmpeg fontconfig fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    fonts-lato fonts-comfortaa \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-api.txt ./
RUN pip install -r requirements.txt -r requirements-api.txt

COPY . .

EXPOSE 10000
CMD ["sh", "-c", "uvicorn editor_api:app --host 0.0.0.0 --port 10000 --workers 1"]
