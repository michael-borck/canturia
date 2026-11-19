# Canturía

**Words into a song, rendered by your own ACE-Step server.**

Canturía is a small, privacy-first text-to-song tool. Type what the song is
about, or paste your own lyrics, choose a genre and a length, and get an MP3
back. It is the same shape as [Limn](https://github.com/michael-borck/limn), but
for music: a Python library and CLI, a single-page web UI, and a Tauri desktop
app.

No account, no telemetry, no hosted service. Nothing leaves your box except the
request to the ACE-Step server you configure and the local Ollama call that
writes lyrics.

**Download the desktop app:** https://michael-borck.github.io/canturia/ — direct
links for macOS Apple Silicon, macOS Intel, Windows, and Linux.

```
"What's the song about?" ──► Ollama writes lyrics ──► ACE-Step sings
"Write your own lyrics" ───────────────────────────► ACE-Step sings
"Surprise me" ──────────────────────────────────────► ACE-Step invents
```

## Three ways in

- **About a topic** *(default)* — type a theme or a sentence. Canturía asks
  Ollama on this machine for original lyrics, then sends them to ACE-Step with
  your genre, exact length, and English vocals.
- **Write lyrics** — paste your own words, with `[Verse]` / `[Chorus]` tags for
  structure. Your words go straight to ACE-Step; length is honoured exactly.
- **Surprise me** — the raw ACE-Step `sample_query` path. Experimental: the
  5Hz LM is a music planner, not a lyricist, so length and language can wander.
  Use it for a happy accident.

The topic path can use one of three **lyricists**:

- **Ollama** — local, no key, the default.
- **OpenAI-compatible** — bring your own key: OpenAI, LM Studio, llama.cpp,
  OpenRouter, or any `/v1/chat/completions` endpoint.
- **ACE-Step LM** — experimental, for comparison; it often returns
  `[Instrumental]`.

The web UI has a **Preview lyrics** button: write the words first, edit them,
then **Sing these lyrics** with an exact length. The CLI equivalents are
`canturia lyrics` and `canturia compare`.

All paths take a genre chip or free-text genre, optional style details, and a
length from 10 to 600 seconds (30/45/60 are the fast presets).

## Install

```bash
pip install "canturia[serve]"
ollama pull qwen3.5:4b      # or another chat model; set ollama.model if needed
```

For development:

```bash
uv sync --all-groups
uv run canturia --help
```

Ollama runs locally. If it is not running, the **Write lyrics** path still
works; the **About a topic** path explains what is missing.

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

# Who writes the lyrics: ollama | openai-compatible | acestep
lyricist: ollama

lyricists:
  ollama:
    base_url: http://127.0.0.1:11434
    model: qwen3.5:4b      # empty = auto-pick from /api/tags
    timeout: 90

  # Bring your own key. Works with OpenAI, LM Studio, llama.cpp, OpenRouter, …
  openai-compatible:
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    api_key: "${OPENAI_API_KEY}"
    timeout: 90

  # ACE-Step's own LM, for comparison only; often returns [Instrumental].
  # acestep: {}

vocal_language: en
thinking: true           # better audio/metadata; resident: true on the server

serve:
  host: 127.0.0.1
  port: 2268
  # password: "${CANTURIA_SERVE_PASSWORD}"
  out_dir: ~/Music/Canturia
```

Secrets can be referenced as `${VAR}` so no plaintext keys live in the file.
Environment overrides include `CANTURIA_BASE_URL`, `CANTURIA_API_KEY`,
`CANTURIA_USERNAME`, `CANTURIA_PASSWORD`, `CANTURIA_LYRICIST`,
`CANTURIA_OLLAMA_URL`, `CANTURIA_OLLAMA_MODEL`, `CANTURIA_OPENAI_BASE_URL`,
`CANTURIA_OPENAI_MODEL`, `CANTURIA_OPENAI_API_KEY`,
`CANTURIA_SERVE_PASSWORD`, and `CANTURIA_OUT_DIR`.

## CLI

```bash
# Topic mode: the chosen lyricist writes, then ACE-Step sings
canturia topic "a warm song about growing up by the sea" -g folk -t 30
canturia topic "a warm song about growing up by the sea" -g folk -t 30 \
  --lyricist openai-compatible

# Lyrics only, no audio
canturia lyrics "a birthday song for grandma" -g folk -t 30 --lyricist ollama

# Compare lyricists side by side
canturia compare "a birthday song for grandma" -g folk -t 30 \
  --with ollama --with acestep

# Your own lyrics (the default command)
canturia "[Verse]\nMorning light across the floor\n[Chorus]\nGrow a little every day" \
  -g folk -t 30 -o morning.mp3

# Raw ACE-Step describe path (experimental)
canturia describe "a surprising song about a robot who learns to dance" -g pop -t 30

# Read lyrics from a file ('-' for stdin)
canturia --lyrics-file words.txt -g indie -t 60

# Check ACE-Step and Ollama
canturia health

# Web UI
canturia serve
```

Every saved song gets a `<song>.json` sidecar with the mode, lyrics writer,
genre, style, prompt, lyrics, duration, vocal language, and server metadata.

## Web UI

```bash
canturia serve --password "something" --host 0.0.0.0
```

The page has **About a topic** and **Write lyrics** tabs, a lyricist selector,
a **Preview lyrics** panel (edit before singing), a **Surprise me** button,
genre chips, 30/45/60 s presets plus a custom field, style details, a **Help**
sheet, and inline hints. Songs appear in a session gallery with an audio player,
Save, Download, Again, and Delete. The gallery is in memory only; Save writes
into `~/Music/Canturia` (or `serve.out_dir`).

When `serve` binds beyond localhost without a password, it generates one and
prints it. The upstream ACE-Step credentials are separate: use `api_key` for a
Bearer token or `username`/`password` for HTTP Basic at a reverse proxy.

## The 5Hz LM and the topic path

ACEStep's `describe`/`sample_query` mode is a chaos knob: the same one-liner can
return a different duration and language (144 s Vietnamese, then 184 s Danish
in one test). That is why the topic box does not use it. Ollama writes the
lyrics first, and ACE-Step receives explicit lyrics, `audio_duration`,
`vocal_language: en`, and `thinking: true`. A 30 s request came back at exactly
30.000 s.

For the raw **Surprise me** path, Canturía appends "with lyrics in English and
English vocals, about N seconds long" to the description, because putting the
language in the words is the only lever that moved the 5Hz LM in testing. It is
still best-effort: the same prompt produced Vietnamese, Danish, Swedish, and
English across four runs, and 30–45 s requests came back at 144–188 s. Treat
Surprise as a novelty, not a contract.

`resident: true` still earns its VRAM: `thinking: true` improves audio and
metadata backfill, the raw Surprise path stays available, and the ACE-Step LM
can be selected as an experimental lyricist for comparison. The default topic
path never uses it to write lyrics.

## ACE-Step notes

- The API is asynchronous: `POST /release_task`, poll `POST /query_result`,
  then download `GET /v1/audio?path=...`.
- `query_result` nests a JSON **string** inside `data[0].result`; Canturía
  decodes it to find the generated file path.
- The finished `file` is a ready-made relative URL, not a raw path; the client
  accepts both.
- Canturía always sends `batch_size: 1`, so one Generate makes one song.
- The first cold request can load/download ~8 GB of weights. The default
  timeout is 15 minutes; raise it if your first run is slower.
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

The sidecar installs `canturia[serve]==0.3.1` from PyPI. For local Python
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
- **M2** — Tauri desktop shell with a Settings sheet for the server URL,
  credentials, and lyricist/BYOK, uv-bootstrapped sidecar, installers in CI
  (done; PyPI 0.3.1).
- **M3** — Optional advanced controls, documented but hidden by default: BPM,
  key, time signature, instrumental, vocal language, LoRA selection.

## Name

**Canturía** (Spanish): the act or manner of singing — *"esta composición tiene
buena canturía."* Package and CLI: `canturia`.

## License

MIT.
