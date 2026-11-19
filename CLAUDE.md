# Canturía — agent handover

`SPEC.md` is the source of truth. This file is the short working note.

## What it is

A privacy-first **text-to-song** tool: describe a topic (Ollama writes the
lyrics locally), paste your own lyrics, or press Surprise (raw ACE-Step), choose
a genre and a length, and get an MP3 from an ACE-Step 1.5 server you point it
at. Same shape as Limn: Python core + Typer CLI + FastAPI single page + Tauri v2
shell. PyPI package and CLI: `canturia`.

## Status (0.3.1)

- Python core, ACE-Step client, lyricist providers, CLI, web UI, Help sheet,
  password gate, tests — done.
- **Lyricist providers**: `ollama` (default), `openai-compatible` (BYOK), and
  `acestep` (experimental, via `/v1/create_sample`). `canturia lyrics` writes
  lyrics only; `canturia compare` runs several side by side.
- **Web preview**: write lyrics with the selected lyricist, edit them, then
  **Sing these lyrics** with an exact duration.
- **Topic mode verified live**: Ollama (`qwen3.5:4b`) wrote English lyrics, and
  a 30 s ACE-Step request returned exactly 30.000 s with `vocal_language: en`
  and `thinking: true`.
- **ACE-Step as lyricist** often returns `[Instrumental]` or repetitive text;
  label it experimental. `compare` now shows this honestly.
- **Surprise/describe is experimental**: the same one-liner returned 144 s
  Vietnamese, then 184 s Danish. The default topic box deliberately does not
  use it; the ACE-Step lyricist is opt-in for comparison.
- `resident: true` is live on the server. It keeps `thinking: true`, metadata
  backfill, Surprise, and the ACE-Step lyricist available.
- Tauri shell, icons, `cargo check`, CI workflows, lyricist/BYOK Settings — in
  the repo. The desktop release uses the shared app-hq workflow and adds stable
  ASCII asset aliases for the landing page.
- Landing page in `landing/` (platform detection, direct stable download
  links), deployed by `.github/workflows/pages.yml` to
  https://michael-borck.github.io/canturia/.
- 63 tests, ruff clean, basedpyright 0 errors.
- Published on PyPI as `canturia`; 0.3.1 is the current source version.

## Local commands

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/canturia"   # repo is on exFAT
uv sync --all-groups
uv run --no-sync ruff check src tests
uv run --no-sync basedpyright
uv run --no-sync pytest
```

Live smoke tests:

```bash
# Lyrics only
uv run --no-sync canturia lyrics "a warm song about growing up by the sea" \
  -g folk -t 30 --lyricist ollama --base-url http://192.168.20.120:8002

# Compare lyricists
uv run --no-sync canturia compare "a birthday song for grandma" \
  -g folk -t 30 --with ollama --with acestep \
  --base-url http://192.168.20.120:8002

# Topic path: a lyricist writes, ACE-Step sings
uv run --no-sync canturia topic "a warm song about growing up by the sea" \
  -g folk -t 30 -o /tmp/topic.mp3 --base-url http://192.168.20.120:8002

# Lyrics path
uv run --no-sync canturia "[Verse]\nMorning light" -g folk -t 10 -o /tmp/x.mp3 \
  --base-url http://192.168.20.120:8002
```

## API gotchas (verified)

- `query_result` wraps its payload in `{data, code, error, timestamp}`.
- `data[0].result` is a **JSON string**; decode it again.
- A finished result's `file` is a ready-made relative URL:
  `/v1/audio?path=%2Fapp%2F...`, **not** a raw path. `AceStepClient.download`
  accepts both a ready URL and a raw path.
- Failed jobs sometimes have `status: 2` with no reason, and `progress_text`
  is a stale global log line. Never use it as the error.
- `batch_size` defaults to 2; Canturía always sends 1.
- `thinking: true` + `vocal_language` are sent explicitly on the reliable paths.
- ACE-Step's `sample_mode`/`sample_query` (Surprise) is a chaos knob; duration
  and language are not reliable there. `vocal_language` is ignored in that
  path. Canturía appends "with lyrics in English and English vocals, about N
  seconds long" to the description; it is the only lever that moved language
  (Vietnamese → Danish → Swedish → English across four runs). Length still
  came back 144–188 s for 30–45 s requests.
- `/format_input` honours duration/language but may return `[Instrumental]` for
  sung vocals; do not use it as the topic path.
- First cold request loads/downloads ~8 GB of weights; default timeout is 900 s.

## Lyricist gotchas

- Ollama default model is `qwen3.5:4b`. `qwen3:4b` puts planning text in
  `content`; qwen3.5 and gemma3 work. `think: false` is set.
- `resolve_model` prefers qwen3.5, gemma3, llama3.1, llama3, mistral, phi3,
  qwen2.5, qwen3. Set `lyricists.ollama.model` to override.
- OpenAI-compatible requires a `base_url` ending at the API root (include
  `/v1`) and a `model`; `api_key` is optional for local servers. The key lives
  in `~/.canturia.yaml` or `CANTURIA_OPENAI_API_KEY` and is never exposed to
  the browser.
- ACE-Step's `/v1/create_sample` often returns `[Instrumental]`; `compare`
  reports that as an error for that provider and keeps the others.
- If the selected lyricist is offline, Lyrics mode still works; the topic tab
  is disabled with an explanation.

## Machine gotchas

- The repo is on exFAT. Keep the venv on the internal disk
  (`UV_PROJECT_ENVIRONMENT`), and delete AppleDouble `._*` files before Tauri
  builds. `desktop/src-tauri/build.rs` clears them from `capabilities/` and
  `icons/` automatically.
- Tauri dev installs `canturia[serve]==0.2.0` from PyPI. Set
  `CANTURIA_DEV_PATH` to use the local source instead.

## Decisions

- Three input modes: `topic` (chosen lyricist, default), `lyrics` (user),
  `describe` (raw ACE-Step, labelled "Surprise me").
- Lyricists: `ollama` (default), `openai-compatible` (BYOK), `acestep`
  (experimental). Preview/edit before singing.
- Genre chips + free-text style; length presets 30/45/60 + custom 10–600 s.
- Session gallery in memory; Save to `~/Music/Canturia` + JSON sidecar;
  Download/Again/Delete.
- Shared app password for hosted `serve`; upstream Bearer/Basic separately.
- In-app Help sheet plus inline hints; no separate docs page in the UI.
- No advanced controls in v1; document BPM/key/time signature/instrumental/
  language/LoRA for later.
- Build order: CLI + web, then Tauri (both now in the repo).
