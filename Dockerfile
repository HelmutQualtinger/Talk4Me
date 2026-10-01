# syntax=docker/dockerfile:1

# ---- Build: Abhängigkeiten und Paket in ein virtuelles Environment installieren ----
# Debian (slim) statt Alpine: onnxruntime für Piper gibt es nur für glibc
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && uv pip install --python .venv/bin/python piper-tts

# ---- Laufzeit: nur Python + fertiges venv, ohne uv und Build-Werkzeuge ----
FROM python:3.13-slim
RUN useradd -m -u 1000 talk4me && mkdir /data /voices && chown talk4me /data /voices
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TALK4ME_HOST=0.0.0.0 \
    TALK4ME_DATA=/data \
    TALK4ME_VOICES=/voices
USER talk4me
VOLUME /data /voices
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/api/suggest?q=')"
CMD ["talk4me", "serve", "8765"]
