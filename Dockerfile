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

# ---- Piper-Stimmen (~800 MB) in eigener Stufe, damit sie beim Code-Umbau im Cache bleiben ----
FROM python:3.13-slim AS voices
COPY src/talk4me/tts.py /tmp/tts.py
RUN mkdir /voices && python - <<'PY'
import re, urllib.request
src = open("/tmp/tts.py").read()
for name in sorted(set(re.findall(r'"([a-z]{2}_[A-Z]{2}-[\w]+-(?:x_low|low|medium|high))"', src))):
    lang, speaker, quality = name.split("-")
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang[:2]}/{lang}/{speaker}/{quality}/{name}"
    for ext in (".onnx", ".onnx.json"):
        urllib.request.urlretrieve(base + ext, f"/voices/{name}{ext}")
PY

# ---- Laufzeit: nur Python + fertiges venv, ohne uv und Build-Werkzeuge ----
FROM python:3.13-slim
RUN useradd -m -u 1000 talk4me && mkdir /data && chown talk4me /data
COPY --from=voices /voices /voices
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TALK4ME_HOST=0.0.0.0 \
    TALK4ME_DATA=/data \
    TALK4ME_VOICES=/voices
USER talk4me
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/api/suggest?q=')"
CMD ["talk4me", "serve", "8765"]
