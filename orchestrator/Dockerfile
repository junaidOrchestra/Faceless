FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The xet download backend can hang on some networks; force plain HTTPS.
# HF_HOME points the model cache at a shared path readable by the non-root user.
ENV HF_HUB_DISABLE_XET=1 \
    HF_HOME=/opt/hf-cache

# Pre-download the default faster-whisper model at build time so runtime needs
# no network. Override with --build-arg WHISPER_MODEL=small (etc.) if desired.
ARG WHISPER_MODEL=base
RUN mkdir -p /opt/hf-cache \
    && python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"

COPY app ./app
COPY migrations.sql .
COPY inspect_beats.py .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/faceless-render /tmp/faceless-results \
    && chown -R appuser:appuser /app /tmp/faceless-render /tmp/faceless-results /opt/hf-cache
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
