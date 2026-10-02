"""Web-UI + JSON-API auf localhost: GET/POST/DELETE /api/sentences, GET /api/suggest?q=, GET/POST /api/translation, GET /api/tts[/voices] (Piper)."""
import json, os, threading, webbrowser
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import auth, db, tts

PAGE = Path(__file__).with_name("index.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- Konten (nur mit TALK4ME_AUTH=1) ----
    def _token(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "t4m":
                return v

    def _cookie(self, token, session_only=False):  # leeres Token löscht das Cookie; Gäste: Sitzungs-Cookie (endet mit dem Browser)
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        age = "" if session_only and token else f"; Max-Age={auth.SESSION_TTL if token else 0}"
        return [("Set-Cookie", f"t4m={token}; Path=/; HttpOnly; SameSite=Lax{age}{secure}")]

    def _ip(self):
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

    def _base(self):
        base = os.environ.get("TALK4ME_BASE_URL")
        if base:
            return base
        host = self.headers.get("Host", "localhost")  # nur ohne TALK4ME_BASE_URL: Host-Header ist vom Client steuerbar
        return f"{self.headers.get('X-Forwarded-Proto', 'http')}://{host}"

    def _body(self):
        d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 10_000)))
        assert isinstance(d, dict)
        return d

    def _account(self, method, path):
        """Behandelt /api/me|register|verify|login|logout; True, wenn die Anfrage damit erledigt ist."""
        if path == "/api/me" and method == "GET":
            user = auth.ENABLED and auth.user_of(self._token())
            if auth.ENABLED and not user:
                self._send(401)
            else:
                self._send(200, json.dumps({"auth": auth.ENABLED, "email": user and user["email"], "guest": bool(user and user["guest"])}).encode())
            return True
        if not auth.ENABLED or method != "POST" or path not in ("/api/register", "/api/verify", "/api/login", "/api/logout", "/api/guest"):
            return False
        try:
            d = {} if path in ("/api/logout", "/api/guest") else self._body()
            if path == "/api/logout":
                auth.logout(self._token())
                self._send(204, headers=self._cookie(""))
            elif path == "/api/guest":
                if auth.limited("guest:" + self._ip(), 10, 3600):
                    return self._send(429) or True
                self._send(204, headers=self._cookie(auth.guest(), session_only=True))
            elif path == "/api/register":
                email = auth.norm(d.get("email"))
                if not email:
                    return self._send(400) or True
                if auth.limited("reg-ip:" + self._ip(), 10, 3600) or auth.limited("reg:" + email, 3, 3600):
                    return self._send(429) or True
                lang = d.get("lang") if isinstance(d.get("lang"), str) else "de"
                auth.register(email, self._base(), lang)
                self._send(204)
            elif path == "/api/verify":
                if auth.limited("ver:" + self._ip(), 20, 3600):
                    return self._send(429) or True
                token = auth.verify(str(d.get("token", "")), str(d.get("password", "")))
                self._send(204, headers=self._cookie(token)) if token else self._send(400)
            else:  # login
                email = auth.norm(d.get("email"))
                if not email or auth.limited("login:" + self._ip(), 20, 900) or auth.limited("login:" + email, 10, 900):
                    return self._send(429 if email else 400) or True
                token = auth.login(email, str(d.get("password", "")))
                self._send(204, headers=self._cookie(token)) if token else self._send(401)
        except Exception:
            self._send(400)
        return True

    def _run(self, method, fn):
        """Konto-Endpunkte, dann Anmeldung prüfen und die Datenbank des Kontos für diese Anfrage setzen."""
        path = urlparse(self.path).path
        if self._account(method, path):
            return
        if auth.ENABLED and path.startswith("/api/"):
            user = auth.user_of(self._token())
            if not user:
                return self._send(401)
            ctx = db.CURRENT.set(user["path"])
            try:
                return fn()
            finally:
                db.CURRENT.reset(ctx)
        fn()

    def do_GET(self):
        self._run("GET", self._get)

    def do_POST(self):
        self._run("POST", self._post)

    def do_DELETE(self):
        self._run("DELETE", self._delete)

    def _get(self):
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

    def _post(self):
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

    def _delete(self):
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
