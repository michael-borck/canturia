# Canturía desktop

A native shell (Tauri v2) around the Python core. It uses the OS webview, so
the installer stays small: no bundled browser engine, no 1 GB Python bundle.

## How it works

1. **First launch** bootstraps a private runtime: finds (or downloads) `uv`,
   creates a venv in the app-data dir with a uv-managed Python, and installs
   `canturia[serve]` pinned to `CANTURIA_VERSION` in `src-tauri/src/main.rs`.
2. The shell runs `canturia serve` on a random localhost port as a sidecar
   (killed on exit) and shows the web UI in the window.
3. **Settings** (shown on first run, and from the header) is the BYO-server
   screen: server URL, optional Bearer token, optional Basic username/password,
   and the lyricist choice (Ollama, OpenAI-compatible BYOK, or ACE-Step LM) →
   written to `~/.canturia.yaml` (chmod 600), the same config the CLI uses.
   Saves land in `Music/Canturia`.

Privacy: no account, no telemetry, no bundled cloud — the only egress is the
generation request to the server the user configures.

## Develop

```bash
cargo install tauri-cli --locked
cd desktop
cargo tauri dev
```

The sidecar installs `canturia[serve]==0.3.0` from PyPI. To use the local source
instead, set `CANTURIA_DEV_PATH="/Volumes/Crucial X9/Projects/song-gen"`; the
first run downloads `uv` if needed, then installs the editable package. Delete
the app-data `runtime/canturia-version` marker to force a reinstall after
Python changes.

On this repo's exFAT drive, set `CARGO_TARGET_DIR` to an internal disk.

## Release

Bump `CANTURIA_VERSION` (if a new release is on PyPI) and the versions in
`src-tauri/tauri.conf.json` + `src-tauri/Cargo.toml`, then:

```bash
git tag desktop-v0.1.0 && git push origin desktop-v0.1.0
```

A CI workflow can build macOS (arm64 + x86_64), Windows (msi/exe) and Linux
(AppImage/deb/rpm) installers with `tauri-action`. Builds are unsigned until a
signing identity is configured.

## Icons

`src-tauri/icons/` carries a placeholder waveform icon generated from
`icons/icon.svg` (terracotta squircle, cream bars). Replace the SVG and rerun
the conversion when a real icon is designed.
