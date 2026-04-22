# Multi-stage build for iDAS backend
FROM python:3.13-slim AS builder

# uv: fast Python package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv venv && uv pip install --no-cache .

# ── runtime stage ───────────────────────────────────────────────
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src /app/src
COPY pyproject.toml /app/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    IDAS_HOST=0.0.0.0 \
    IDAS_PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()" || exit 1

CMD ["uvicorn", "idas.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
