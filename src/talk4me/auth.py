"""Konten (nur mit TALK4ME_AUTH=1): Registrierung per E-Mail-Link, Anmeldung mit Passwort, je Konto eine eigene Satz-Datenbank.

Ablauf: POST /api/register {email} schickt einen Link mit Einmal-Token; erst /api/verify {token, password} legt das Konto an (oder setzt bei
bestehendem Konto das Passwort neu) und meldet an. Sitzung = Cookie `t4m`; in der Datenbank steht nur der SHA-256 des Tokens."""
import hashlib, hmac, os, re, secrets, smtplib, sqlite3, threading, time
from contextlib import closing
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import db

ENABLED = os.environ.get("TALK4ME_AUTH") == "1"
USERS_DB = db.DATA / "users.db"
USER_DIR = db.DATA / "users"
PENDING_TTL, SESSION_TTL = 24 * 3600, 30 * 24 * 3600
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

MAIL = {  # Sprache -> (Betreff, Text mit {0} = Link)
    "de": ("Talk4Me: Konto anlegen", "Öffne diesen Link, um dein Talk4Me-Konto anzulegen oder das Passwort neu zu setzen (24 Stunden gültig):\n\n{0}\n\nHast du das nicht angefordert, ignoriere diese E-Mail."),
    "en": ("Talk4Me: create your account", "Open this link to create your Talk4Me account or to set a new password (valid for 24 hours):\n\n{0}\n\nIf you did not request this, ignore this email."),
    "it": ("Talk4Me: crea il tuo account", "Apri questo link per creare il tuo account Talk4Me o impostare una nuova password (valido 24 ore):\n\n{0}\n\nSe non l'hai richiesto, ignora questa e-mail."),
    "fr": ("Talk4Me : créer votre compte", "Ouvrez ce lien pour créer votre compte Talk4Me ou définir un nouveau mot de passe (valable 24 heures) :\n\n{0}\n\nSi vous n'avez rien demandé, ignorez cet e-mail."),
    "hu": ("Talk4Me: fiók létrehozása", "Nyisd meg ezt a hivatkozást a Talk4Me-fiókod létrehozásához vagy új jelszó beállításához (24 óráig érvényes):\n\n{0}\n\nHa nem te kérted, hagyd figyelmen kívül ezt az e-mailt."),
    "ja": ("Talk4Me：アカウントの作成", "次のリンクを開いて、Talk4Meのアカウントを作成するか、パスワードを再設定してください（24時間有効）：\n\n{0}\n\n心当たりがない場合は、このメールを無視してください。"),
    "es": ("Talk4Me: crea tu cuenta", "Abre este enlace para crear tu cuenta de Talk4Me o establecer una nueva contraseña (válido 24 horas):\n\n{0}\n\nSi no lo solicitaste, ignora este correo."),
    "ru": ("Talk4Me: создание аккаунта", "Откройте эту ссылку, чтобы создать аккаунт Talk4Me или задать новый пароль (действует 24 часа):\n\n{0}\n\nЕсли вы этого не запрашивали, проигнорируйте письмо."),
    "zh": ("Talk4Me：创建账户", "请打开此链接以创建 Talk4Me 账户或设置新密码（24 小时内有效）：\n\n{0}\n\n如果这不是你本人的操作，请忽略此邮件。"),
}

_hits, _hits_lock = {}, threading.Lock()


def _c():
    USER_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(USERS_DB)
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, salt BLOB NOT NULL, pw BLOB NOT NULL, created INTEGER NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS pending (token TEXT PRIMARY KEY, email TEXT NOT NULL, expires INTEGER NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL)")
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _hash(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def limited(key, n, window):
    """True, wenn `key` in den letzten `window` Sekunden schon n-mal vorkam (zählt diesen Aufruf mit)."""
    now = time.time()
    with _hits_lock:
        hits = [t for t in _hits.get(key, []) if now - t < window]
        hits.append(now)
        _hits[key] = hits
        if len(_hits) > 10000:  # Speicher begrenzen
            for k in [k for k, v in _hits.items() if now - v[-1] > window]:
                del _hits[k]
        return len(hits) > n


def norm(email):
    email = (email or "").strip().lower()
    return email if EMAIL.match(email) else None


def user_db(uid):
    return USER_DIR / f"{int(uid)}.db"


def _send(to, subject, body):
    host = os.environ.get("TALK4ME_SMTP_HOST")
    if not host:  # ohne Mailserver: Link ins Container-Log (Entwicklung)
        print(f"[Talk4Me] E-Mail an {to}: {subject}\n{body}", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, to
    msg["From"] = os.environ.get("TALK4ME_SMTP_FROM") or os.environ.get("TALK4ME_SMTP_USER") or "talk4me@localhost"
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid(domain=msg["From"].rsplit("@", 1)[-1].strip("> "))  # fehlen sie, werten Spamfilter strenger
    msg.set_content(body)
    port = int(os.environ.get("TALK4ME_SMTP_PORT", "587"))
    try:
        with (smtplib.SMTP_SSL(host, port, timeout=20) if port == 465 else smtplib.SMTP(host, port, timeout=20)) as s:
            if port != 465 and os.environ.get("TALK4ME_SMTP_STARTTLS", "1") != "0":
                s.starttls()
            if os.environ.get("TALK4ME_SMTP_USER"):
                s.login(os.environ["TALK4ME_SMTP_USER"], os.environ.get("TALK4ME_SMTP_PASSWORD", ""))
            s.send_message(msg)
    except Exception as e:
        print("[Talk4Me] E-Mail an", to, "fehlgeschlagen:", e, flush=True)


def register(email, base_url, lang="de"):
    """Schickt den Link (im Hintergrund). Antwort ist immer gleich, damit sich nicht erkennen lässt, ob es die Adresse schon gibt."""
    token = secrets.token_urlsafe(32)
    with closing(_c()) as c, c:
        c.execute("DELETE FROM pending WHERE expires < ?", (time.time(),))
        c.execute("INSERT INTO pending VALUES (?, ?, ?)", (_h(token), email, time.time() + PENDING_TTL))
    subject, body = MAIL.get(lang, MAIL["en"])
    link = f"{base_url.rstrip('/')}/?verify={token}"
    threading.Thread(target=_send, args=(email, subject, body.format(link)), daemon=True).start()


def _session(c, uid):
    token = secrets.token_urlsafe(32)
    c.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    c.execute("INSERT INTO sessions VALUES (?, ?, ?)", (_h(token), uid, time.time() + SESSION_TTL))
    return token


def verify(token, password):
    """Token einlösen: Konto anlegen oder Passwort neu setzen; liefert das Sitzungs-Token oder None."""
    if len(password or "") < 8 or len(password) > 200:
        return None
    with closing(_c()) as c, c:
        row = c.execute("DELETE FROM pending WHERE token = ? AND expires > ? RETURNING email", (_h(token or ""), time.time())).fetchone()
        if not row:
            return None
        email, salt = row[0], secrets.token_bytes(16)
        pw = _hash(password, salt)
        c.execute("INSERT INTO users (email, salt, pw, created) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(email) DO UPDATE SET salt = excluded.salt, pw = excluded.pw", (email, salt, pw, int(time.time())))
        uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))  # nach Passwortwechsel alle alten Sitzungen beenden
        _adopt(email, uid)
        return _session(c, uid)


def _adopt(email, uid):
    """Der Konto-Inhaber TALK4ME_ADOPT_EMAIL übernimmt die frühere Einzelnutzer-Datenbank (Kopie, falls er noch keine hat)."""
    target = user_db(uid)
    if email == (os.environ.get("TALK4ME_ADOPT_EMAIL") or "").strip().lower() and db.DB.exists() and not target.exists():
        with closing(sqlite3.connect(db.DB)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)


def login(email, password):
    with closing(_c()) as c, c:
        row = c.execute("SELECT id, salt, pw FROM users WHERE email = ?", (email,)).fetchone()
        salt = row[1] if row else b"\0" * 16  # auch bei unbekannter Adresse rechnen: gleiche Antwortzeit
        ok = hmac.compare_digest(_hash(password or "", salt), row[2] if row else b"\0" * 32)
        return _session(c, row[0]) if row and ok else None


def user_of(token):
    """(id, email) zur Sitzung oder None."""
    if not token:
        return None
    with closing(_c()) as c:
        return c.execute("SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires > ?",
                         (_h(token), time.time())).fetchone()


def logout(token):
    with closing(_c()) as c, c:
        c.execute("DELETE FROM sessions WHERE token = ?", (_h(token or ""),))
