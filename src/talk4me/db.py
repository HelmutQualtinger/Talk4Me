"""SQLite-Speicher + Suche, gemeinsam genutzt von Terminal-UI und Web-UI. Ein Satz = eine Zeile."""
import math
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "talk4me.db"  # <Projekt>/data/
OLD_DB = Path.home() / ".talk4me" / "talk4me.db"  # früherer Speicherort

SCHEMA = """CREATE TABLE IF NOT EXISTS sentences (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL UNIQUE,
    lang TEXT NOT NULL DEFAULT 'de',
    first_used TEXT NOT NULL,
    last_used TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 1)"""

# Übersetzungen: FK sentence_id zeigt vom Eintrag zum Original; umgekehrt findet man über sentence_id alle Übersetzungen eines Satzes
TRANSLATIONS = """CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    lang TEXT NOT NULL,
    text TEXT NOT NULL,
    created TEXT NOT NULL,
    UNIQUE (sentence_id, lang))"""


def _connect():
    DB.parent.mkdir(exist_ok=True)
    if not DB.exists() and OLD_DB.exists():
        shutil.move(OLD_DB, DB)
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    if any(r[1] == "ts" for r in c.execute("PRAGMA table_info(sentences)")):  # altes Schema: 1 Zeile je Verwendung
        with c:
            c.execute("ALTER TABLE sentences RENAME TO sentences_old")
            c.execute(SCHEMA)
            c.execute("INSERT INTO sentences (text, lang, first_used, last_used, use_count) "
                      "SELECT text, MAX(lang), MIN(ts), MAX(ts), COUNT(*) FROM sentences_old GROUP BY text")
            c.execute("DROP TABLE sentences_old")
    c.execute(SCHEMA)
    c.execute(TRANSLATIONS)
    c.execute("CREATE INDEX IF NOT EXISTS translations_rev ON translations (lang, text)")
    return c


def add(text, lang="de"):
    """Neuer Satz oder Zähler +1 und Datum aktualisieren."""
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as c, c:
        c.execute("INSERT INTO sentences (text, lang, first_used, last_used) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(text) DO UPDATE SET lang = excluded.lang, last_used = excluded.last_used, "
                  "use_count = use_count + 1", (text, lang, now, now))


def all():
    """Alle Sätze, zuletzt verwendet zuerst."""
    with closing(_connect()) as c:
        return [{"text": t, "lang": l, "first_used": f, "last_used": u, "count": n} for t, l, f, u, n in
                c.execute("SELECT text, lang, first_used, last_used, use_count FROM sentences "
                          "ORDER BY last_used DESC, id DESC")]


def translation(text, src, dst):
    """Gespeicherte Übersetzung von `text` (Sprache src) nach dst oder None.
    Vorwärts: Original -> Übersetzung. Rückwärts: ist `text` selbst eine gespeicherte Übersetzung, liefert die FK das Original."""
    with closing(_connect()) as c:
        row = (c.execute("SELECT t.text FROM translations t JOIN sentences s ON s.id = t.sentence_id "
                         "WHERE s.text = ? AND t.lang = ?", (text, dst)).fetchone()
               or c.execute("SELECT s.text FROM translations t JOIN sentences s ON s.id = t.sentence_id "
                            "WHERE t.text = ? AND t.lang = ? AND s.lang = ?", (text, src, dst)).fetchone())
        return row[0] if row else None


def add_translation(text, dst, translated):
    """Speichert die Übersetzung am vorhandenen Satz `text`; False, wenn es den Satz nicht gibt."""
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as c, c:
        row = c.execute("SELECT id FROM sentences WHERE text = ?", (text,)).fetchone()
        if row:
            c.execute("INSERT INTO translations (sentence_id, lang, text, created) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(sentence_id, lang) DO UPDATE SET text = excluded.text", (row[0], dst, translated, now))
        return bool(row)


def clear():
    with closing(_connect()) as c, c:
        c.execute("DELETE FROM sentences")


def _fuzzy(q, s):
    s = s.lower()
    best = SequenceMatcher(None, q, s).ratio() + (q in s)  # Teilstring-Treffer belohnen
    return max(best, max((SequenceMatcher(None, q, w).ratio() for w in s.split()), default=0))


def _popularity(r):
    """Bonus für häufig (log) und kürzlich (Halbwertszeit 7 Tage) verwendete Sätze."""
    age = (datetime.now() - datetime.fromisoformat(r["last_used"])).total_seconds() / 86400
    return 0.1 * math.log1p(r["count"]) + 0.2 * 0.5 ** (age / 7)


def suggest(q, n=8):
    """Leere Eingabe: die 5 zuletzt verwendeten Sätze. Sonst Fuzzy-Treffer (Schwelle 0.4) plus Popularitätsbonus."""
    q = q.strip().lower()
    if not q:
        return all()[:5]  # jeder Satz steht nur einmal in der Tabelle
    scored = [(f + _popularity(r), r) for r in all() if (f := _fuzzy(q, r["text"])) > 0.4]
    return [r for _, r in sorted(scored, key=lambda x: x[0], reverse=True)[:n]]
