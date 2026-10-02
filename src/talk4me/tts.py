"""Server-seitige Sprachausgabe mit Piper (nur im Docker-Image installiert; sonst ist alles leer und die Web-UI nimmt Browser-Stimmen)."""
import io, os, threading, urllib.request, wave
from pathlib import Path

VOICE_DIR = Path(os.environ.get("TALK4ME_VOICES", "/voices"))
# Sprache -> {m, f}: Piper-Modellname (ohne .onnx). Fehlt ein Geschlecht, wird das andere genommen.
VOICES = {
    "de": {"m": "de_DE-thorsten_emotional-medium", "f": "de_DE-eva_k-x_low"},
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


def ensure_voices():
    """Lädt fehlende Modelle von Hugging Face nach VOICE_DIR (läuft beim Serverstart im Hintergrund, Fehler werden nur gemeldet)."""
    try:
        import piper  # noqa: F401
    except ImportError:
        return
    names = sorted({n for v in VOICES.values() for n in v.values()})
    for name in names:
        lang, speaker, quality = name.split("-")
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang[:2]}/{lang}/{speaker}/{quality}/{name}"
        for ext in (".onnx.json", ".onnx"):  # .onnx zuletzt: erst dann gilt die Stimme als vorhanden
            dst = VOICE_DIR / (name + ext)
            if dst.exists():
                continue
            try:
                VOICE_DIR.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + ".part")
                urllib.request.urlretrieve(base + ext, tmp)
                tmp.rename(dst)
                print("Stimme geladen:", name, flush=True)
            except Exception as e:
                print("Stimme", name, "nicht geladen:", e, flush=True)
                break


def available():
    """{lang: [Geschlechter mit eigener Stimme]} der tatsächlich installierten Modelle."""
    try:
        import piper  # noqa: F401
    except ImportError:
        return {}
    return {l: [g for g, n in v.items() if (VOICE_DIR / f"{n}.onnx").exists()] for l, v in VOICES.items()
            if any((VOICE_DIR / f"{n}.onnx").exists() for n in v.values())}


def synth(text, lang, gender="m", rate=1.0, emotion=""):
    """WAV-Bytes oder None, wenn es für die Sprache keine Stimme gibt. emotion: Sprecher-Name bei Mehrsprecher-Modellen
    (thorsten_emotional: amused, angry, disgusted, drunk, neutral, sleepy, surprised, whisper); ohne Angabe neutral."""
    name = _name(lang, gender)
    if not name or not text.strip():
        return None
    from piper import PiperVoice, SynthesisConfig
    with _lock:  # ONNX-Sitzung nicht parallel benutzen
        voice = _loaded.get(name) or _loaded.setdefault(name, PiperVoice.load(VOICE_DIR / f"{name}.onnx"))
        speakers = voice.config.speaker_id_map  # leer bei Einzelsprecher-Modellen
        sid = speakers.get(emotion, speakers.get("neutral")) if speakers else None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            voice.synthesize_wav(text[:2000], w, SynthesisConfig(speaker_id=sid, length_scale=1 / max(0.3, min(rate, 3.0))))
    return buf.getvalue()
