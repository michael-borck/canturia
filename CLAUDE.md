# Canturía — agent handover

`SPEC.md` is the source of truth. This file is the short working note.

## What it is

A privacy-first **text-to-song** tool: paste lyrics or describe a topic, choose
a genre and a length, get an MP3 from an ACE-Step 1.5 server you point it at.
Same shape as Limn: Python core + Typer CLI + FastAPI single page + Tauri v2
shell. PyPI package and CLI: `canturia`.

## Status (0.1.0)

- Python core, ACE-Step client, CLI, web UI, password gate, tests — done and
  verified live against `http://192.168.20.120:8002` (lyrics mode).
- Published on PyPI as `canturia` 0.1.0. Install with
  `pip install "canturia[serve]"`.
- Tauri shell, icons, `cargo check`, CI workflows — in the repo. The sidecar
  installs `canturia[serve]==0.1.0` from PyPI; use `CANTURIA_DEV_PATH` for
  editable local source.
- **Describe mode is untested live** because the server currently reports
  `llm_initialized: false`. It uses `sample_mode`/`sample_query`; enable the
  server's LM (`resident: true` in `puente.yml`) to use it.
- 41 tests, ruff clean, basedpyright 0 errors.

## Local commands

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/canturia"   # repo is on exFAT
uv sync --all-groups
uv run --no-sync ruff check src tests
uv run --no-sync basedpyright
uv run --no-sync pytest
```

Live smoke test:

```bash
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
  is a stale global log line. Never use it as the error; say the lyrics writer
  may be off when Describe failed.
- `batch_size` defaults to 2; Canturía always sends 1.
- First cold request downloads ~8 GB of weights; default timeout is 900 s.

## Machine gotchas

- The repo is on exFAT. Keep the venv on the internal disk
  (`UV_PROJECT_ENVIRONMENT`), and delete AppleDouble `._*` files before Tauri
  builds. `desktop/src-tauri/build.rs` clears them from `capabilities/` and
  `icons/` automatically.
- Tauri dev installs `canturia[serve]==0.1.0` from PyPI. Set
  `CANTURIA_DEV_PATH` to use the local source instead.

## Decisions

- Two modes: `lyrics` (LM off) and `describe` (LM on).
- Genre chips + free-text style; length presets + custom 10–600 s.
- Session gallery in memory; Save to `~/Music/Canturia` + JSON sidecar;
  Download/Again/Delete.
- Shared app password for hosted `serve`; upstream Bearer/Basic separately.
- No advanced controls in v1; document BPM/key/time signature/instrumental/
  language/LoRA for later.
- Build order: CLI + web, then Tauri (both now in the repo).
