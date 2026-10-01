"""Server-seitige Sprachausgabe mit Piper (nur im Docker-Image installiert; sonst ist alles leer und die Web-UI nimmt Browser-Stimmen)."""
import io, os, threading, wave
from pathlib import Path

VOICE_DIR = Path(os.environ.get("TALK4ME_VOICES", "/voices"))
# Sprache -> {m, f}: Piper-Modellname (ohne .onnx). Fehlt ein Geschlecht, wird das andere genommen.
VOICES = {
    "de": {"m": "de_DE-thorsten-medium", "f": "de_DE-eva_k-x_low"},
    "en": {"m": "en_US-ryan-medium", "f": "en_US-amy-medium"},
    "it": {"m": "it_IT-riccardo-x_low", "f": "it_IT-paola-medium"},
    "fr": {"m": "fr_FR-tom-medium", "f": "fr_FR-siwis-medium"},
    "hu": {"m": "hu_HU-imre-medium", "f": "hu_HU-anna-medium"},
    "es": {"m": "es_ES-davefx-medium"},
    "ru": {"m": "ru_RU-denis-medium", "f": "ru_RU-irina-medium"},
    "zh": {"f": "zh_CN-huayan-medium"},
}
_loaded, _lock = {}, threading.Lock()


def _name(lang, gender):
    v = VOICES.get(lang, {})
    for n in (v.get(gender), *v.values()):
        if n and (VOICE_DIR / f"{n}.onnx").exists():
            return n


def available():
    """{lang: [Geschlechter mit eigener Stimme]} der tatsächlich installierten Modelle."""
    try:
        import piper  # noqa: F401
    except ImportError:
        return {}
    return {l: [g for g, n in v.items() if (VOICE_DIR / f"{n}.onnx").exists()] for l, v in VOICES.items()
            if any((VOICE_DIR / f"{n}.onnx").exists() for n in v.values())}


def synth(text, lang, gender="m", rate=1.0):
    """WAV-Bytes oder None, wenn es für die Sprache keine Stimme gibt."""
    name = _name(lang, gender)
    if not name or not text.strip():
        return None
    from piper import PiperVoice, SynthesisConfig
    with _lock:  # ONNX-Sitzung nicht parallel benutzen
        voice = _loaded.get(name) or _loaded.setdefault(name, PiperVoice.load(VOICE_DIR / f"{name}.onnx"))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            voice.synthesize_wav(text[:2000], w, SynthesisConfig(length_scale=1 / max(0.3, min(rate, 3.0))))
    return buf.getvalue()
