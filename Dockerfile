# syntax=docker/dockerfile:1.7
#
# API image (FastAPI + retrieval models). Build context: the repository root.
#
#   docker build -t compliance-copilot-api .                          # CPU PyTorch (default)
#   docker build -t compliance-copilot-api:cuda --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu130 .
#
# The retrieval models (BGE-M3, bge-reranker-v2-m3, ~4.5 GB) are NOT baked in: they are
# downloaded once into the /models volume (HF_HOME) on first start, or mounted.

FROM python:3.15-slim AS builder
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV UV_LINK_MODE=copy PIP_NO_CACHE_DIR=1
RUN pip install uv==0.12.13
WORKDIR /build
COPY pyproject.toml uv.lock ./
# Install exactly the locked dependencies, except PyTorch: the lock pins the CUDA wheels, so choose
# CPU or CUDA explicitly. torch goes in FIRST so packages that depend on it (sentence-transformers)
# find it already satisfied instead of pulling the CUDA build from PyPI.
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --index-url "$TORCH_INDEX" "torch>=2.6" \
 && uv export --frozen --no-dev --no-hashes --no-emit-project \
      | grep -Ev '^(torch|nvidia-|cuda-|triton|pytorch-triton)' > requirements.txt \
 && uv pip install --python /opt/venv/bin/python -r requirements.txt

FROM python:3.15-slim
# libgomp: OpenMP runtime used by PyTorch CPU kernels
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models \
    COPILOT_LOG_FORMAT=json
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY src ./src
COPY config ./config
COPY data ./data
COPY eval ./eval
# Writable locations for the unprivileged user: model cache, downloaded PDFs, OCR/LLM caches, reports
RUN mkdir -p /models /app/data/raw /app/data/processed /app/docs /app/eval/results \
 && chown -R app:app /models /app/data /app/docs /app/eval \
 && printf '#!/bin/sh\nexec python -m compliance_copilot "$@"\n' > /usr/local/bin/copilot \
 && chmod +x /usr/local/bin/copilot
USER app
EXPOSE 8000
# /ready turns green once the database answers and the models are loaded; the first start
# downloads them, hence the long grace period.
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4).status == 200 else 1)"
# One worker: every worker would load its own copy of the models.
CMD ["uvicorn", "compliance_copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
