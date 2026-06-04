# CLIP server — Hugging Face Spaces target (CPU, port 7860, non-root).
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    HF_HUB_DISABLE_XET=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install CPU-only torch first (the default PyPI wheel bundles ~900MB of CUDA
# libraries this CPU service never uses). The +cpu build satisfies torch==2.5.1.
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the CLIP model at build time so cold starts on HF Spaces are fast.
ENV CLIP_MODEL_NAME=clip-ViT-B-32
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${CLIP_MODEL_NAME}', device='cpu')"

COPY app ./app
COPY migrations.sql .

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
