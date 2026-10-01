# Talk4Me

Type a sentence, hear it spoken. Sentences you have used before are remembered and suggested while you type, so you can repeat them with two key presses and no mouse. Optionally, the sentence is translated into German, English, Italian or French first.

![Talk4Me web UI](docs/screenshot.png)

*The screenshot shows demo data. The settings are hidden in the ☰ menu at the top left.*

## Features

- **Fuzzy suggestions while typing**, ranked by similarity plus a bonus for sentences used often and recently. With an empty input field, the 50 most recently used sentences are shown, scrollable with the arrow keys (each only once).
- **Keyboard only**: `↑`/`↓` select a suggestion, `Tab` speaks it, `Enter` speaks what you typed, `Esc` stops the playback (or clears the field when nothing is playing).
- **Translation** between German, English, Italian and French. Translations are stored and reused, in both directions (a stored translation also leads back to its original).
- **Settings in a hamburger menu** (top left of the web UI): they appear when you hover the ☰ button. Input and target language, male or female voice, German variant (Austria, Switzerland, Germany) and speed from 80 to 150 %.
- **One SQLite database** shared by the web UI and the terminal UI. Every sentence is stored once, with its language, first and last use date and use count.

## Requirements

- macOS (the terminal UI speaks through `say`)
- [uv](https://docs.astral.sh/uv/) with Python 3.13 or newer
- A browser for the web UI. No Python dependencies.

## Usage

### Web UI

```sh
uv run talk4me serve          # http://127.0.0.1:8765, opens the browser
uv run talk4me serve 9000     # another port
```

Open the page through this server. Opened as a plain file it cannot reach the database.

### Docker

The web UI also runs as a small container (multi-stage build on `python:3.13-alpine`, about 75 MB, runs as a non-root user):

```sh
docker compose up -d --build   # http://127.0.0.1:8765
docker compose down
```

- The database is mounted from `./data`, so the container and a local start share the same sentences.
- The port is published on `127.0.0.1` only, because the API has no login. Do not expose it to a network.
- The container serves the page and the database only. Speech and translation happen in your browser, so nothing changes there. The terminal UI needs macOS `say` and is not part of the image.
- Settings: `TALK4ME_DATA` (data directory, default `/data` in the image) and `TALK4ME_HOST` (bind address, `0.0.0.0` in the image, `127.0.0.1` otherwise).

### Terminal UI

```sh
uv run talk4me                # default voice
uv run talk4me -v Anna        # choose a voice (list them with: say -v '?')
```

The terminal UI has the same suggestions and keys, but no translation and no voice settings beyond `-v`.

## Audio mixer

A separate tool, independent of the speech UI: it reads [BlackHole](https://existential.audio/blackhole/) and the default input device (microphone) and plays both mixed on the default output device.

```sh
uv run --extra mixer talk4me-mixer                 # uses sounddevice and numpy, installed only with the extra
uv run --extra mixer talk4me-mixer --list          # show audio devices
uv run --extra mixer talk4me-mixer --gain-mic 0.8 --gain-blackhole 1.2
uv run --extra mixer talk4me-mixer --mic "USB" --out "Kopfhörer"   # pick devices by name part
```

- Both inputs are converted to stereo, summed and limited to full scale. A level meter shows whether signal arrives.
- The default block size of 512 frames at the output device's sample rate gives roughly 10 to 40 ms of delay (`--block` changes it). Different device clocks are compensated by dropping the oldest samples.
- **Avoid feedback**: the output must not lead back into BlackHole. The mixer refuses to start if the output is BlackHole itself, but it cannot see inside a *Multi-Output Device* that contains BlackHole. Choose a plain output (speakers, headphones) with `--out`. Use headphones so the microphone does not pick up the speakers.
- macOS asks for microphone access for the terminal on first use.

## Data

Everything is stored in `data/talk4me.db` (SQLite, excluded from git):

| Table | Content |
|---|---|
| `sentences` | one row per unique sentence: text, language, `first_used`, `last_used`, `use_count` |
| `translations` | `sentence_id` (foreign key to `sentences`), target language, translated text |

Inspect it with `sqlite3 data/talk4me.db "SELECT text, use_count FROM sentences"`.

## Good to know

- **Translation** uses the unofficial, keyless Google Translate endpoint from the browser. It may be throttled or blocked at any time; if it fails, the original sentence is spoken and a message is shown. Sentences are sent to Google only when input and target language differ and no stored translation exists.
- **Output device**: the browser's speech API speaks through the system's default output and cannot pick another device. Change it in macOS (Sound settings).
- **Voices** come from your system through the browser's Web Speech API, which does not report gender. The UI picks voices from name lists per language (`VOICES` in `src/talk4me/index.html`).
- **Austrian and Swiss voices** are not part of macOS. The browser Microsoft Edge offers them as online voices (Jonas and Ingrid for Austria, Jan and Leni for Switzerland). Without such a voice, the standard German voice is used and the page tells you so.

## Project layout

```
src/talk4me/__init__.py   terminal UI (curses) and entry point
src/talk4me/db.py         SQLite storage, translations, suggestion ranking
src/talk4me/server.py     local web server and JSON API
src/talk4me/mixer.py      separate audio mixer (BlackHole + microphone)
src/talk4me/index.html    web UI
Dockerfile, docker-compose.yml   container for the web UI
```
