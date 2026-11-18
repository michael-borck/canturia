# Canturía

**Words into a song, rendered by your own ACE-Step server.**

Canturía is a small, privacy-first text-to-song tool. Paste lyrics or describe a
topic, choose a genre and a length, and get an MP3 back. It is the same shape as
[Limn](https://github.com/michael-borck/limn), but for music: a Python library
and CLI, a single-page web UI, and (next) a Tauri desktop app.

No account, no telemetry, no hosted service. The only network egress is the
generation request to the ACE-Step server you configure.

## Two ways in

- **Lyrics** — paste your own words, with `[Verse]` / `[Chorus]` tags for
  structure. This works with the ACE-Step language model switched off.
- **Describe** — give it a topic or a sentence and let ACE-Step write the
  lyrics. This needs the server's 5Hz language model enabled
  (`resident: true` in `puente.yml`); Canturía detects and explains when it is
  off.

Both modes take a genre chip or free-text genre, optional style details, and a
length from 10 to 600 seconds.

## Install

```bash
pip install "canturia[serve]"
```

For development:

```bash
uv sync --all-groups
uv run canturia --help
```

## Configure

Canturía reads `~/.canturia.yaml`, then `./canturia.yaml`, then CLI flags.
Write a template and edit it once:

```bash
canturia --init-config
```

```yaml
base_url: http://192.168.20.120:8002

# Optional upstream auth (Bearer or HTTP Basic):
# api_key: "${ACESTEP_API_KEY}"
# username: admin
# password: "${ACESTEP_PASSWORD}"

timeout: 900          # cold start can take minutes
poll_interval: 2
genre: folk
duration: 30

serve:
  host: 127.0.0.1
  port: 2268
  # password: "${CANTURIA_SERVE_PASSWORD}"
  out_dir: ~/Music/Canturia
```

Secrets can be referenced as `${VAR}` so no plaintext keys live in the file.
The same settings are available as `CANTURIA_BASE_URL`,
`CANTURIA_API_KEY`, `CANTURIA_USERNAME`, `CANTURIA_PASSWORD`, and for the web
server `CANTURIA_SERVE_PASSWORD`.

## CLI

```bash
# Lyrics mode (the default command)
canturia "[Verse]\nMorning light across the floor\n[Chorus]\nGrow a little every day" \
  -g folk -t 30 -o morning.mp3

# Read lyrics from a file ('-' for stdin)
canturia --lyrics-file words.txt -g indie -t 60

# Describe mode: ACE-Step writes the lyrics (requires its LM)
canturia describe "a warm song about growing up by the sea" -g folk -t 45

# Check the server and whether the lyrics writer is on
canturia health

# Web UI
canturia serve
```

Every saved song gets a `<song>.json` sidecar with the mode, genre, style,
prompt, lyrics, duration, and server metadata.

## Web UI

```bash
canturia serve --password "something" --host 0.0.0.0
```

The page has Lyrics and Describe tabs, genre chips, length presets plus a
custom field, a style-details field, and a session gallery with an audio player,
Save, Download, Again, and Delete. The gallery is in memory only; Save writes
into `~/Music/Canturia` (or `serve.out_dir`).

When `serve` binds beyond localhost without a password, it generates one and
prints it. The upstream ACE-Step credentials are separate: use `api_key` for a
Bearer token or `username`/`password` for HTTP Basic at a reverse proxy.

## ACE-Step notes

- The API is asynchronous: `POST /release_task`, poll `POST /query_result`,
  then download `GET /v1/audio?path=...`.
- `query_result` nests a JSON **string** inside `data[0].result`; Canturía
  decodes it to find the generated file path.
- Canturía always sends `batch_size: 1`, so one Generate makes one song.
- The first cold request can download ~8 GB of weights. The default timeout is
  15 minutes; raise it if your first run is slower.
- The server runs either the Gradio UI or the API, not both. This client needs
  the API mode.

## Desktop

The Tauri v2 shell lives in `desktop/`. It bootstraps a private Python runtime
with `uv`, runs `canturia serve` on a random localhost port, and shows the web
UI in the window. Settings writes `~/.canturia.yaml`.

```bash
cargo install tauri-cli --locked
cd desktop && cargo tauri dev
```

The sidecar installs `canturia[serve]==0.1.0` from PyPI. For local Python
changes, set `CANTURIA_DEV_PATH="$PWD"` to install the repo in editable mode
instead.

## Why Python, and why Tauri

Python is the core because the same code is the PyPI library, the CLI, and the
local server the desktop app runs. Tauri wraps that server with the OS webview,
so there is no bundled browser engine; Electron would only add weight. The
desktop app bootstraps a private runtime with `uv`, exactly like Limn, rather
than shipping a 1 GB Python bundle.

## Development

On this machine the repo is on an exFAT drive, so keep the venv on the internal
disk (the same workaround Limn uses):

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/canturia"
uv sync --all-groups
uv run --no-sync ruff check src tests
uv run --no-sync basedpyright
uv run --no-sync pytest
```

## Roadmap

- **M1** — Python core, CLI, web UI (done).
- **M2** — Tauri desktop shell with a Settings sheet for the server URL and
  credentials, uv-bootstrapped sidecar, installers in CI (shell and CI in this
  repo; the sidecar installs `canturia[serve]==0.1.0` from PyPI).
- **M3** — Optional advanced controls, documented but hidden by default: BPM,
  key, time signature, instrumental, vocal language, LoRA selection.

## Name

**Canturía** (Spanish): the act or manner of singing — *"esta composición tiene
buena canturía."* Package and CLI: `canturia`.

## License

MIT.
