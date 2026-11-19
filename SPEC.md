# Canturía — specification

> *canturía (Spanish): the act or manner of singing; a song's way of being sung.*

A small, privacy-first tool that turns words into a song. Paste lyrics or
describe a topic, choose a genre and a length, get audio. No account, no
telemetry, bring your own ACE-Step server.

---

## 1. Vision

Most music tools are either a locked-in web service or a full DAW. Canturía sits
in between: the simplest possible "words → song" surface, that you own.

- **Three ways in.** Describe a topic and let a local Ollama model write the
  lyrics, paste your own lyrics, or press Surprise and let ACE-Step invent
  everything. The first two are reliable; the last is an explicit experiment.
- **Minimal by design.** Genre, length, and optional style details. Nothing
  else in the main flow.
- **Bring your own server.** Point Canturía at an ACE-Step 1.5 API on your LAN
  or behind your own proxy. Swap the URL with one setting.
- **Private by default.** No account, no telemetry, no server-side storage of
  prompts or audio. The desktop app is fully local apart from the request to
  *your* server; the web UI keeps the session gallery in memory and only writes
  a file when you press Save.

## 2. Principles

1. **Simple beats powerful.** One screen, two modes, one Generate button.
2. **Local-first.** Session gallery in memory; Save is explicit.
3. **Provider-shaped, not provider-locked.** The ACE-Step client and the
   Ollama lyricist are thin modules; the core does not depend on a UI.
4. **Progressive surfaces.** The same core powers a CLI, a web UI, and a
   desktop app. Each is optional.
5. **Fail visibly.** No silent fallback when the server's lyrics writer is off
   or the request fails.

## 3. Surfaces

### v1 — CLI

```bash
canturia "[Verse]\nMorning light...\n[Chorus]\nGrow a little every day" -g folk -t 30
canturia describe "a warm song about growing up by the sea" -g folk -t 45
canturia health
canturia serve
```

Options: `--lyrics-file`, `--genre`, `--style`, `--duration`, `--out`,
`--config`, `--base-url`, `--api-key`, `--username`, `--password`,
`--timeout`, `--init-config`.

### v2 — Web UI (`canturia serve`)

A single page:

- **About a topic** (default) and **Write lyrics** tabs, plus a **Surprise me**
  button for the raw ACE-Step path.
- A **lyricist selector**: Ollama, OpenAI-compatible (BYOK), or ACE-Step LM
  (experimental), with availability and model shown.
- **Preview lyrics**: write the words first, edit them, then **Sing these
  lyrics** with an exact duration. This is the comparison workflow.
- **Help** sheet and inline hints: what each mode does, where lyrics come from,
  what Surprise does, where files are saved, BYOK, and the cold-start
  expectation.
- Genre chips (folk, pop, rock, indie, lo-fi, electronic, hip-hop, soul,
  country, jazz, classical, ambient, metal, lullaby) plus optional free-text
  style details.
- Length presets 30/45/60 s plus a custom 10–600 s field.
- Generate → a pending card with live progress (Ollama writing, then ACE-Step
  generating) → an audio card.
- Audio player, Save, Download, Again, Delete.
- Status pill for both ACE-Step and Ollama; contextual notices when either is
  offline.
- In-memory session gallery (max 50 songs) and JSON sidecars on Save.

FastAPI + a self-contained HTML page (no CDNs). Binds `127.0.0.1` by default;
an optional shared password gates hosted instances.

### v3 — Desktop (Tauri + Python sidecar)

A native, installable app. Tauri v2 uses the OS webview (no bundled browser
engine). On first launch it bootstraps a private runtime with `uv`, creates a
venv in the app-data directory, installs `canturia[serve]==<pin>`, runs
`canturia serve` on a random localhost port, and shows the served UI. Settings
writes `~/.canturia.yaml` (merge-preserving, chmod 600), the same file the CLI
uses. Saves land in `~/Music/Canturia`. Distributed as a signed installer; not
on the Mac App Store (runtime-download rules).

## 4. Input modes

| Mode | Input | Path | Reliable? |
|---|---|---|---|
| `topic` *(default)* | Topic / theme / sentence | Chosen lyricist writes lyrics → ACE-Step `prompt` + `lyrics` + exact `audio_duration` + `vocal_language` + `thinking` | Yes |
| `lyrics` | Lyrics with `[Verse]` / `[Chorus]` tags | Same ACE-Step path; words pass through | Yes |
| `describe` | Topic / sentence | ACE-Step `sample_mode: true` + `sample_query` with an appended English + length hint | No — experimental |

`prompt` is built from the genre preset plus optional style details, e.g.
`gentle acoustic folk, warm vocals, fingerpicked guitar, close mic`.

### Lyricists

| Name | What | Auth |
|---|---|---|
| `ollama` | Local Ollama chat model; default `qwen3.5:4b`, auto-picked from `/api/tags` | None |
| `openai-compatible` | Any `/v1/chat/completions` endpoint: OpenAI, LM Studio, llama.cpp, OpenRouter | Bearer key for cloud; optional locally |
| `acestep` | ACE-Step's 5Hz LM via `/v1/create_sample`, for comparison only | Uses the ACE-Step server auth |

By default, the topic path does **not** use ACE-Step's 5Hz LM to write lyrics.
That model is a music planner: in testing it returned 144 s of Vietnamese and
184 s of Danish for the same English one-liner, ignoring both duration and
language. Ollama writes the lyrics locally in one call; ACE-Step receives
explicit lyrics, an exact duration, English vocals, and `thinking: true`. A 30 s
request returned 30.000 s. The ACE-Step LM is still selectable as an
experimental lyricist for comparison.

BYOK applies to the OpenAI-compatible lyricist. Keys live in
`~/.canturia.yaml` or the environment and are sent only to the endpoint the
user configures. The desktop Settings sheet writes them; the hosted web UI
reads the operator's config and never exposes keys to the browser.

For Surprise/describe, the language demand is put into the description itself
("with lyrics in English and English vocals, about N seconds long"), because
`vocal_language` is ignored in sample mode. This is a strong suggestion, not a
contract: testing produced Vietnamese, Danish, Swedish, and English from the
same English prompt, and 30–45 s requests returned 144–188 s.

The web UI reads `/health` and `/api/ollama`, disables the topic box when Ollama
is offline, and disables Surprise when ACE-Step's own LM is off
(`llm_initialized: false`). `resident: true` stays useful for `thinking: true`,
metadata backfill, and Surprise.

Durations are validated in the client at 10–600 seconds, matching ACE-Step.
`batch_size` is always 1; "Again" creates another take.

## 5. ACE-Step API contract

Verified against the live service and the upstream OpenAPI/source at commit
`ca1e85fe`. The API is LAN-only and unauthenticated today; the client supports
the auth it exposes for the move behind a proxy.

### Envelope

Every endpoint returns:

```json
{"data": ..., "code": 200, "error": null, "timestamp": 1795042169917}
```

A non-200 `code` is an error. `data` is the useful payload.

### Submit

```http
POST /release_task
Content-Type: application/json

{
  "prompt": "gentle acoustic folk, warm female vocals, fingerpicked guitar",
  "lyrics": "[Verse]\nMorning light...\n[Chorus]\nGrow a little every day",
  "audio_duration": 30,
  "batch_size": 1,
  "thinking": true,
  "vocal_language": "en"
}
```

Returns `data.task_id` (also `status`, `queue_position`). The first cold request
may download ~8 GB of weights; it queues rather than failing.

### Poll

```http
POST /query_result
Content-Type: application/json

{"task_id_list": ["<task_id>"]}
```

Returns `data` as a list. Each item has `task_id`, `status`
(`0` running, `1` done, `2` failed), `progress_text`, and `result`.

**Gotcha:** `result` is a JSON *string*. Decode it again to get a list of
result objects. When done, each object has `file` (a server-side path),
`prompt`, `lyrics`, and `metas` (`bpm`, `duration`, `genres`, `keyscale`,
`timesignature`). When failed, the object carries `error`.

### Download

```http
GET /v1/audio?path=%2Fapp%2Foutputs%2F...
```

The `path` query parameter must be URL-encoded; pass the decoded server path
through the HTTP client's params and let it encode. The response is audio bytes.

### Auth

`/release_task` and `/query_result` accept an `ai_token` body field or
`Authorization: Bearer <token>`. `/v1/audio` and `/v1/models` accept the
`Authorization` header. A reverse proxy can use HTTP Basic instead. Canturía
supports Bearer (`api_key`) and Basic (`username` + `password`).

## 6. Auth model

- **Upstream:** optional Bearer or Basic, stored in `~/.canturia.yaml` or
  environment variables. Never exposed to the browser.
- **App:** an optional shared password for `canturia serve`. A successful login
  sets an HttpOnly, SameSite=Strict session cookie backed by an in-memory
  session table. When binding beyond localhost without a password, `serve`
  generates one and prints it. Localhost needs no password by default.
- **Desktop:** the sidecar binds `127.0.0.1` with no app password; the Settings
  sheet stores the upstream URL/credentials.

## 7. Config

Layered, later wins:

1. Built-in defaults.
2. `~/.canturia.yaml`.
3. `./canturia.yaml` (or `--config FILE`).
4. CLI flags / environment.

```yaml
base_url: http://192.168.20.120:8002
api_key: "${ACESTEP_API_KEY}"        # optional Bearer
username: admin                      # optional Basic
password: "${ACESTEP_PASSWORD}"
timeout: 900
request_timeout: 60
poll_interval: 2
genre: folk
style: ""
duration: 30
vocal_language: en
thinking: true
lyricist: ollama          # ollama | openai-compatible | acestep
lyricists:
  ollama:
    base_url: http://127.0.0.1:11434
    model: qwen3.5:4b
    timeout: 90
  openai-compatible:
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    api_key: "${OPENAI_API_KEY}"
    timeout: 90
serve:
  host: 127.0.0.1
  port: 2268
  password: "${CANTURIA_SERVE_PASSWORD}"
  out_dir: ~/Music/Canturia
```

Environment overrides: `CANTURIA_BASE_URL`, `CANTURIA_API_KEY`,
`CANTURIA_USERNAME`, `CANTURIA_PASSWORD`, `CANTURIA_MODEL`,
`CANTURIA_TIMEOUT`, `CANTURIA_POLL_INTERVAL`, `CANTURIA_GENRE`,
`CANTURIA_DURATION`, `CANTURIA_VOCAL_LANGUAGE`, `CANTURIA_THINKING`,
`CANTURIA_LYRICIST`, `CANTURIA_OLLAMA_URL`, `CANTURIA_OLLAMA_MODEL`,
`CANTURIA_OPENAI_BASE_URL`, `CANTURIA_OPENAI_MODEL`,
`CANTURIA_OPENAI_API_KEY`, `CANTURIA_HOST`, `CANTURIA_PORT`,
`CANTURIA_SERVE_PASSWORD`, `CANTURIA_OUT_DIR`.

## 8. Architecture

```
canturia/
  providers/acestep.py   thin ACE-Step client (submit, poll, download)
  providers/ollama.py    Ollama chat client
  lyricists/             ollama | openai-compatible | acestep
  lyrics_text.py         shared prompts and lyric cleanup
  core.py                modes, lyricists, genre presets, saving
  config.py              layered config + env expansion
  cli.py                 Typer CLI
  serve.py               FastAPI app factory
  serve_page.html        self-contained web UI + Help sheet (package data)
  desktop/               Tauri v2 shell + uv-bootstrapped sidecar
tests/
```

- **Python 3.10+**, `typer`, `rich`, `requests`, `pyyaml`.
- **Web:** `fastapi` + `uvicorn` behind the `[serve]` extra.
- **Packaging:** hatchling; `pip install canturia`, publish to PyPI.
- **Desktop:** Tauri v2 (Rust) + Python sidecar, `uv`-bootstrapped runtime.

## 9. Privacy and storage

- No account, no telemetry, no logging of prompts or audio.
- Ollama runs locally. The OpenAI-compatible lyricist sends prompts only to the
  endpoint and key the user configures; keys are never exposed to the browser.
- The web session gallery is in memory, capped at 50 songs, and dies with the
  process.
- Save writes the audio plus a `<song>.json` sidecar into
  `~/Music/Canturia` (configurable). Save never overwrites.
- The only egress is the request to the configured ACE-Step server.

## 10. Non-goals

- Not a DAW, editor, or stem separator.
- Not a model host; Canturía calls the server you point it at.
- Not a prompt-engineering IDE. Advanced musical controls stay out of the main
  flow.
- Not a hosted multi-tenant service. The web UI is for one person or a trusted
  group behind a password/proxy.

## 11. Milestones

1. **M1 — Core, CLI, web UI.** `canturia "lyrics"`, `canturia topic`,
   `canturia describe`, all three in the web UI, session gallery with
   Save/Download/Again/Delete, password gate, Help sheet, tests. Published on
   PyPI.
2. **M2 — Desktop.** Tauri shell, first-run uv runtime, Settings sheet for the
   server URL, credentials, and lyricist/BYOK, CI installers, landing page.
3. **M3 — Lyricists and preview.** `lyricists/` providers, `canturia lyrics`,
   `canturia compare`, web Preview lyrics → edit → Sing, 0.3.2.
4. **M4 — Optional depth.** Hidden/advanced controls: instrumental, vocal
   language, BPM, key, time signature, inference steps, LoRA selection. Same
   "simple by default" rule as Limn.

## 12. Future controls (documented, not in the v1 UI)

ACE-Step accepts these; they are deliberately omitted from the main screen:

- `instrumental` (topic mode)
- `vocal_language` (already fixed to `en`; expose per request later)
- `bpm`, `key_scale`, `time_signature`
- `inference_steps`, `guidance_scale`, `seed`
- `model` (DiT variant)
- LoRA load/toggle/scale endpoints

When added, they belong under an Options disclosure, not in the main flow.
