# Canturía troubleshooting

## The app asks for a password

Update to **0.4.2 or later**. The desktop shell passes a per-launch token to the
local sidecar, and the page uses bearer auth instead of a cookie, so it should
open directly.

If it still appears, quit the app, install the latest DMG over the old one, and
launch it again. The runtime marker updates on launch. The hosted web UI
(`canturia serve --host 0.0.0.0`) still uses a shared password; that is separate
from the desktop token.

## ACE-Step is offline

1. Check the server URL in Settings or `~/.canturia.yaml`.
2. Open the server's `/health` endpoint on the ACE-Step host, for example
   `http://192.168.20.120:8002/health`.
3. Click the status pill in the app to recheck.

A cold server may answer `/health` before its model is ready. The first request
can still take minutes while weights load.

## The lyricist is unavailable

- **Ollama:** run `ollama serve`, then `ollama pull qwen3.5:4b` (or set
  `lyricists.ollama.model`).
- **OpenAI-compatible:** set the base URL (including `/v1`), model, and API key
  in Settings, or in `~/.canturia.yaml` / `CANTURIA_OPENAI_*`.
- **Write lyrics** still works without any lyricist.

The topic and Preview buttons are disabled when the selected lyricist is
unavailable. The status pill and the notice above the gallery explain why.

## Surprise me / ACE-Step LM is unavailable

ACE-Step's own 5Hz LM is a music planner, not a reliable lyricist. It needs
`resident: true` in `puente.yml` (or the equivalent server setting). Even then,
it can ignore length/language and produce `[Instrumental]` or repeated lines.
Canturía flags repetitive output; use it for comparison, not as the default.

## I see "no adapter loaded" for LoRA

LoRA is server-side. The path you enter must exist on the ACE-Step host. Load it
first, then use/bypass or scale it. The app does not upload adapters.

## Where are my songs?

Saved files live in `~/Music/Canturia` by default, or `serve.out_dir`:

- `<name>.mp3`
- `<name>.mp3.json` (mode, genre, prompt, lyrics, duration, advanced parameters)

The **Saved songs** section lists that folder. In the desktop app, **Open
folder** reveals it. `canturia library` lists the same songs from the CLI.

## The first generation is very slow

The first cold ACE-Step request can download/load roughly 8 GB of weights. It is
queued, not failed. Later requests are much faster. The default timeout is 900
seconds; raise `timeout` in the config if your first run is slower.

## macOS says the app is damaged or cannot be opened

Release builds are signed and notarized. If you built locally, the binary is
unsigned; use `cargo tauri dev` or run `xattr -dr com.apple.quarantine` on the
app you built. Do not disable Gatekeeper globally.

## Windows SmartScreen blocked the installer

Windows builds are currently unsigned. Choose **More info → Run anyway**. A
signed Windows build is a future release task.

## Updating

The desktop app checks for updates at launch and from the **Updates** button.
It downloads, installs, and restarts when you confirm. The first install is a
manual download from https://michael-borck.github.io/canturia/.

Updater artifacts are signed with the per-app key; `latest.json` lives on the
latest GitHub release. If an update check fails, check the release and network,
then use the landing page as a fallback.

## CLI

```bash
canturia health
canturia library
canturia lora status
```

`canturia health` reports ACE-Step, the default lyricist, and whether the
ACE-Step LM is on. Use `--config FILE` to point at a specific config.
