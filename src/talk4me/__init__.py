#!/usr/bin/env python3
"""Talk4Me: Text eintippen, per macOS `say` sprechen, Sätze speichern, Fuzzy-Vorschläge.

Enter = tippen & sprechen | ↑/↓ = Vorschlag wählen | Tab = Vorschlag sprechen | Esc/Ctrl-C = Ende
Aufruf: uv run talk4me [-v Voice]  |  uv run talk4me serve [port]  (Web-UI)   (Voices: `say -v '?'`, z.B. Anna für Deutsch)
"""
import curses, subprocess, sys

from . import db

VOICE = sys.argv[sys.argv.index("-v") + 1] if "-v" in sys.argv else None
proc = None


def speak(text):
    global proc
    if proc and proc.poll() is None:
        proc.terminate()
    proc = subprocess.Popen(["say", *(["-v", VOICE] if VOICE else []), "--", text])


def run(scr):
    curses.curs_set(1)
    buf, sel = "", 0
    while True:
        sugg = db.suggest(buf, 10)
        sel = min(sel, max(len(sugg) - 1, 0))
        scr.erase()
        h, w = scr.getmaxyx()
        scr.addnstr(0, 0, "> " + buf, w - 1)
        for i, s in enumerate(sugg[: h - 2]):
            scr.addnstr(i + 1, 0, ("▶ " if i == sel else "  ") + f"{s['text']}  ({s['count']}×)", w - 1,
                        curses.A_REVERSE if i == sel else 0)
        scr.move(0, min(2 + len(buf), w - 1))
        scr.refresh()

        k = scr.get_wch()
        if k == "\x1b" or k == "\x03":
            return
        elif k == curses.KEY_DOWN:
            sel = min(sel + 1, len(sugg) - 1)
        elif k == curses.KEY_UP:
            sel = max(sel - 1, 0)
        elif k == "\t" and sugg:
            speak(sugg[sel]["text"])
            db.add(sugg[sel]["text"], sugg[sel]["lang"])
            buf, sel = "", 0
        elif k in ("\n", "\r") and buf.strip():
            speak(buf.strip())
            db.add(buf.strip())
            buf, sel = "", 0
        elif k in ("\x7f", "\b", curses.KEY_BACKSPACE):
            buf, sel = buf[:-1], 0
        elif isinstance(k, str) and k.isprintable():
            buf, sel = buf + k, 0


def main():
    if sys.argv[1:2] == ["serve"]:  # talk4me serve [port]
        from .server import serve
        return serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8765)
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass
