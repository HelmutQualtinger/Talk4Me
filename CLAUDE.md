# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Run: `uv run talk4me [-v Voice]` (Voices: `say -v '?'`). Needs a real TTY (curses); it cannot be driven from Claude's Bash tool. To smoke-test, spawn it in a `pty.fork()` and send keystrokes.
- Pure logic can be tested without a TTY: `uv run python -c "import talk4me.db as db; print(db.suggest('morg'))"` (reads the real database in `data/`; `add()` writes to it).
- No tests, linter or build config exist yet.

- Docker: `docker compose up -d --build` (web UI only; multi-stage python:slim image (~2 GB: includes Piper TTS + ~800 MB voice models from huggingface rhasspy/piper-voices, installed only in the image; alpine has no onnxruntime), image user uid 1000 but `docker-compose.yml` overrides it with `user: root`, `./data` mounted at `/data`, published on 127.0.0.1 only because the API is unauthenticated). The DB directory comes from `TALK4ME_DATA`, the bind address from `TALK4ME_HOST` (the image sets `0.0.0.0` and `/data`; locally the defaults are `127.0.0.1` and `<project>/data`). Free port 8765 first if a local `talk4me serve` is running.

## Architecture

stdlib only, no dependencies, macOS only (shells out to `say`). `pyproject.toml` maps the `talk4me` script to `talk4me:main`.

- `src/talk4me/__init__.py`: curses UI + fuzzy search; `main()` dispatches `serve` to the web server, otherwise starts the curses loop `run()`.
- `db.py`: SQLite at `<project>/data/talk4me.db` (git-ignored), shared by both UIs. Table `sentences` has one row per unique text (`lang`, `first_used`, `last_used`, `use_count`); `add()` upserts and increments the counter. Table `translations` (`sentence_id` FK -> `sentences.id` ON DELETE CASCADE, `lang`, `text`, UNIQUE per sentence+lang; foreign keys are enabled per connection) caches translations; `translation()` looks up forward (original -> translation) and backward (a stored translation -> its original via the FK). It also holds the search: `suggest()` ranks fuzzy hits (difflib, threshold 0.4) over sentences and their stored translations (a translation hit returns the original, with `via`) plus a popularity bonus (log of use count, 7-day half-life on last use); an empty query returns the 50 most recently used sentences (the web list scrolls). Old layouts (per-use rows, or the DB in `~/.talk4me/`) are migrated automatically on connect.
- `server.py` + `index.html`: `uv run talk4me serve [port]` (default 8765, localhost only) serves the page and the JSON API `GET/POST/DELETE /api/sentences` plus `GET /api/suggest?q=` (the page has no search logic of its own). The settings live in a hover-only hamburger menu (`#menu`, CSS `:hover`/`:focus-within`). The browser does the speaking; a server-side `say -a` output-device path was tried and removed on request. The page has no own storage; opened via `file://` it cannot persist. Before translating, the page asks `GET /api/translation` (DB first) and stores new results with `POST /api/translation`; otherwise it translates in the browser via the unofficial, keyless `translate.googleapis.com` gtx endpoint (DeepL was tried and dropped). It speaks via the browser's Web Speech API, choosing voices from hard-coded name lists per gender and language (`VOICES` in `index.html`, since Web Speech exposes no gender; the gender select is remembered in localStorage).
- `tts.py` + `/api/tts[/voices]`: server-side Piper speech (Docker image only; `VOICES` maps lang -> m/f model names, the Dockerfile downloads exactly the names listed there; no Japanese voice exists in Piper). The page prefers Piper when the server has the language and no concrete browser voice is chosen, falling back to Web Speech (Brave has almost no browser voices). Missing gender falls back to the other one (es: male only, zh: female only).
- Curses keys: Enter speaks and logs typed text; Up/Down select; Tab speaks and logs the selected suggestion; Esc/Ctrl-C quit (Esc has curses' ~1s delay). `speak()` kills any running `say` first.
