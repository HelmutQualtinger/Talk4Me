"""Separater Audio-Mixer (macOS): mischt BlackHole und das Standard-Eingabegerät auf das Standard-Ausgabegerät.

Aufruf: uv run --extra mixer talk4me-mixer [--list] [--blackhole NAME] [--mic NAME] [--out NAME]
                                          [--gain-blackhole 1.0] [--gain-mic 1.0] [--block 512]
Ctrl-C beendet. Kopfhörer benutzen, sonst hört das Mikrofon die Lautsprecher (Rückkopplung).
"""
import argparse
import sys
import threading
import time

import numpy as np
import sounddevice as sd


class Buffer:
    """Stereo-Puffer (float32) zwischen einem Eingang und dem Ausgang. Überlauf verwirft die ältesten Samples
    (hält die Verzögerung klein und gleicht Takt-Drift zwischen den Geräten aus), Unterlauf liefert Stille."""

    def __init__(self, max_frames):
        self.data = np.zeros((0, 2), np.float32)
        self.max = max_frames
        self.lock = threading.Lock()

    def write(self, block):
        with self.lock:
            self.data = np.concatenate((self.data, block))[-self.max:]

    def read(self, frames):
        with self.lock:
            out, self.data = self.data[:frames], self.data[frames:]
        return np.pad(out, ((0, frames - len(out)), (0, 0)))


def to_stereo(block):
    return np.repeat(block, 2, axis=1) if block.shape[1] == 1 else block[:, :2]


def mix(a, b, gain_a, gain_b):
    """Summe beider Signale, auf [-1, 1] begrenzt."""
    return np.clip(a * gain_a + b * gain_b, -1.0, 1.0)


def find(kind, name=None):
    """Geräte-Index: per Namensteil (ohne Groß-/Kleinschreibung) oder das Standardgerät."""
    devs = sd.query_devices()
    ok = lambda i: devs[i][f"max_{kind}_channels"] > 0
    if name:
        hits = [i for i in range(len(devs)) if ok(i) and name.lower() in devs[i]["name"].lower()]
        if not hits:
            sys.exit(f"Kein {kind}-Gerät mit '{name}'. Geräte anzeigen: --list")
        return hits[0]
    default = sd.query_devices(kind=kind)["name"]
    return next(i for i in range(len(devs)) if ok(i) and devs[i]["name"] == default)


def main():
    ap = argparse.ArgumentParser(description="BlackHole + Standard-Eingabe -> Standard-Ausgabe")
    ap.add_argument("--list", action="store_true", help="Audiogeräte anzeigen und beenden")
    ap.add_argument("--blackhole", default="BlackHole", help="Namensteil des BlackHole-Geräts")
    ap.add_argument("--mic", help="Eingabegerät statt Standard (Namensteil)")
    ap.add_argument("--out", help="Ausgabegerät statt Standard (Namensteil)")
    ap.add_argument("--gain-blackhole", type=float, default=1.0)
    ap.add_argument("--gain-mic", type=float, default=1.0)
    ap.add_argument("--block", type=int, default=512, help="Blockgröße in Frames (kleiner = weniger Verzögerung)")
    args = ap.parse_args()

    if args.list:
        print(sd.query_devices())
        return

    bh, mic, out = find("input", args.blackhole), find("input", args.mic), find("output", args.out)
    devs = sd.query_devices()
    if bh == mic:
        sys.exit("Standard-Eingabe ist BlackHole. Mikrofon mit --mic wählen oder in macOS als Eingabe einstellen.")
    if "blackhole" in devs[out]["name"].lower():
        sys.exit("Standard-Ausgabe ist BlackHole: das gäbe eine Rückkopplung. Anderes Ausgabegerät mit --out wählen.")

    rate = int(devs[out]["default_samplerate"])
    out_ch = min(2, devs[out]["max_output_channels"])
    bufs = {bh: Buffer(4 * args.block), mic: Buffer(4 * args.block)}
    peak = {bh: 0.0, mic: 0.0}

    def capture(idx):
        def cb(indata, frames, t, status):
            block = to_stereo(indata)
            peak[idx] = float(np.abs(block).max())
            bufs[idx].write(block)
        return cb

    def play(outdata, frames, t, status):
        m = mix(bufs[bh].read(frames), bufs[mic].read(frames), args.gain_blackhole, args.gain_mic)
        outdata[:] = m if out_ch == 2 else m.mean(axis=1, keepdims=True)

    kw = dict(samplerate=rate, blocksize=args.block, dtype="float32", latency="low")
    try:
        with sd.InputStream(device=bh, channels=devs[bh]["max_input_channels"], callback=capture(bh), **kw), \
             sd.InputStream(device=mic, channels=devs[mic]["max_input_channels"], callback=capture(mic), **kw), \
             sd.OutputStream(device=out, channels=out_ch, callback=play, **kw):
            print(f"BlackHole: {devs[bh]['name']}\nMikrofon:  {devs[mic]['name']}\nAusgabe:   {devs[out]['name']}"
                  f"  ({rate} Hz, Block {args.block})\nCtrl-C beendet.", file=sys.stderr)
            bar = lambda p: "█" * int(min(p, 1.0) ** 0.5 * 20)
            while True:
                print(f"\rBlackHole {bar(peak[bh]):<20}  Mikrofon {bar(peak[mic]):<20}", end="", file=sys.stderr)
                time.sleep(0.1)
    except KeyboardInterrupt:
        print(file=sys.stderr)
    except sd.PortAudioError as e:
        sys.exit(f"Audio-Fehler: {e}\nMikrofonzugriff für das Terminal erlauben (Systemeinstellungen > Datenschutz) "
                 f"und prüfen, ob alle Geräte {rate} Hz unterstützen.")


if __name__ == "__main__":
    main()
