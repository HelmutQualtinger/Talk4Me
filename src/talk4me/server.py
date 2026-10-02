"""Web-UI + JSON-API auf localhost: GET/POST/DELETE /api/sentences, GET /api/suggest?q=, GET/POST /api/translation, GET /api/tts[/voices] (Piper)."""
import json, os, threading, webbrowser
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db, tts

PAGE = Path(__file__).with_name("index.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/sentences":
            self._send(200, json.dumps(db.all()).encode())
        elif u.path == "/api/suggest":  # ?q=… -> Fuzzy + Häufigkeit/Aktualität
            self._send(200, json.dumps(db.suggest(parse_qs(u.query).get("q", [""])[0])).encode())
        elif u.path == "/api/translation":  # ?text=&from=&to= -> {text: Übersetzung | null}
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            self._send(200, json.dumps({"text": db.translation(q.get("text", ""), q.get("from"), q.get("to"))}).encode())
        elif u.path == "/api/tts/voices":  # {lang: [m, f]} der installierten Piper-Stimmen
            self._send(200, json.dumps(tts.available()).encode())
        elif u.path == "/api/tts":  # ?text=&lang=&gender=m|f&rate=1.0&emotion= -> audio/wav
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                wav = tts.synth(q.get("text", ""), q.get("lang", ""), q.get("gender", "m"), float(q.get("rate", 1)), q.get("emotion", ""))
            except Exception:
                wav = None
            self._send(200, wav, "audio/wav") if wav else self._send(404)
        elif u.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404)

    def do_POST(self):
        if self.path not in ("/api/sentences", "/api/translation"):
            return self._send(404)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text = d["text"].strip()
            assert text
            if self.path == "/api/translation":  # {text, to, translation}
                assert db.add_translation(text, d["to"], d["translation"])
            else:
                lang = d.get("lang", "de")
                assert isinstance(lang, str)
                db.add(text, lang)
        except Exception:
            return self._send(400)
        self._send(204)

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path != "/api/sentences":
            return self._send(404)
        text = parse_qs(u.query).get("text")  # ?text=… löscht einen Satz, sonst alle
        if text:
            return self._send(204 if db.delete(text[0]) else 404)
        db.clear()
        self._send(204)

    def log_message(self, *a):
        pass


def serve(port=8765):
    host = os.environ.get("TALK4ME_HOST", "127.0.0.1")  # im Container 0.0.0.0, sonst nur lokal
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=tts.ensure_voices, daemon=True).start()
    url = f"http://{host}:{port}/"
    print("Talk4Me läuft auf", url, "(Ctrl-C beendet)", flush=True)
    if host == "127.0.0.1":
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
