// Canturía desktop: a thin Tauri shell around the Python core.
//
// On first launch it bootstraps a private Python runtime with uv (downloaded
// if absent), installs canturia[serve] into an app-data venv, then runs
// `canturia serve` as a localhost sidecar and shows its UI in the webview.
// Settings write the user's ~/.canturia.yaml — bring your own ACE-Step server;
// nothing ever leaves the machine except requests to that server.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

/// The canturia release the runtime installs; bump with PyPI releases.
const CANTURIA_VERSION: &str = "0.2.2";

struct Sidecar(Mutex<Option<Child>>);

#[derive(Serialize, Deserialize, Default, Clone)]
struct Settings {
    base_url: String,
    api_key: String,
    username: String,
    password: String,
}

fn status(app: &AppHandle, message: &str) {
    let _ = app.emit("status", message.to_string());
}

fn config_path() -> Result<PathBuf, String> {
    dirs::home_dir()
        .map(|home| home.join(".canturia.yaml"))
        .ok_or_else(|| "Could not determine home directory".into())
}

fn yaml_str(value: &serde_yaml::Value, key: &str) -> String {
    value
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string()
}

#[tauri::command]
fn get_settings() -> Settings {
    let Ok(path) = config_path() else {
        return Settings::default();
    };
    let Ok(text) = fs::read_to_string(&path) else {
        return Settings::default();
    };
    let Ok(root) = serde_yaml::from_str::<serde_yaml::Value>(&text) else {
        return Settings::default();
    };
    Settings {
        base_url: yaml_str(&root, "base_url"),
        api_key: yaml_str(&root, "api_key"),
        username: yaml_str(&root, "username"),
        password: yaml_str(&root, "password"),
    }
}

#[tauri::command]
fn save_settings(settings: Settings) -> Result<(), String> {
    if settings.base_url.trim().is_empty() {
        return Err("Enter your ACE-Step server URL".into());
    }
    if !settings.username.is_empty() && settings.password.is_empty() {
        return Err("Basic auth needs both a username and a password".into());
    }
    let path = config_path()?;

    // Preserve an existing config's other keys; only update what we own.
    let mut root = fs::read_to_string(&path)
        .ok()
        .and_then(|t| serde_yaml::from_str::<serde_yaml::Value>(&t).ok())
        .unwrap_or(serde_yaml::Value::Mapping(Default::default()));
    let serde_yaml::Value::Mapping(map) = &mut root else {
        return Err(format!(
            "{} is not a YAML mapping; edit it by hand",
            path.display()
        ));
    };

    map.insert(
        "base_url".into(),
        settings.base_url.trim().to_string().into(),
    );
    for (key, value) in [
        ("api_key", &settings.api_key),
        ("username", &settings.username),
        ("password", &settings.password),
    ] {
        let trimmed = value.trim();
        let value_key = serde_yaml::Value::String(key.to_string());
        if trimmed.is_empty() {
            map.remove(&value_key);
        } else {
            map.insert(value_key, trimmed.to_string().into());
        }
    }

    let text = serde_yaml::to_string(&root).map_err(|e| e.to_string())?;
    fs::write(&path, text).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

fn command(program: impl AsRef<std::ffi::OsStr>) -> Command {
    let cmd = Command::new(program);
    #[cfg(windows)]
    let cmd = {
        use std::os::windows::process::CommandExt;
        let mut c = cmd;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        c
    };
    cmd
}

fn run_ok(cmd: &mut Command) -> Result<(), String> {
    let output = cmd.output().map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn find_uv() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(home) = dirs::home_dir() {
        candidates.push(home.join(".local/bin/uv"));
        candidates.push(home.join(".cargo/bin/uv"));
    }
    candidates.push("/opt/homebrew/bin/uv".into());
    candidates.push("/usr/local/bin/uv".into());
    #[cfg(windows)]
    if let Some(home) = dirs::home_dir() {
        candidates.push(home.join(".local\\bin\\uv.exe"));
    }
    for path in candidates {
        if path.exists() {
            return Some(path);
        }
    }
    let probe = command("uv").arg("--version").output();
    if matches!(probe, Ok(ref o) if o.status.success()) {
        return Some("uv".into());
    }
    None
}

fn install_uv(app: &AppHandle) -> Result<PathBuf, String> {
    status(app, "Downloading uv (one-time)…");
    #[cfg(not(windows))]
    run_ok(command("sh").args([
        "-c",
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
    ]))?;
    #[cfg(windows)]
    run_ok(command("powershell").args([
        "-NoProfile",
        "-ExecutionPolicy",
        "ByPass",
        "-Command",
        "irm https://astral.sh/uv/install.ps1 | iex",
    ]))?;
    find_uv().ok_or_else(|| "uv installed but not found".into())
}

fn canturia_bin(venv: &Path) -> PathBuf {
    #[cfg(windows)]
    return venv.join("Scripts").join("canturia.exe");
    #[cfg(not(windows))]
    venv.join("bin").join("canturia")
}

fn venv_python(venv: &Path) -> PathBuf {
    #[cfg(windows)]
    return venv.join("Scripts").join("python.exe");
    #[cfg(not(windows))]
    venv.join("bin").join("python")
}

/// First run: create the app's private venv and install canturia[serve].
///
/// For development before the first PyPI release, set CANTURIA_DEV_PATH to
/// the repo root and the editable package is installed instead.
fn ensure_runtime(app: &AppHandle, force_update: bool) -> Result<PathBuf, String> {
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;
    let venv = data_dir.join("runtime");
    let bin = canturia_bin(&venv);

    let marker = venv.join("canturia-version");
    let installed = fs::read_to_string(&marker).unwrap_or_default();
    if bin.exists() && installed.trim() == CANTURIA_VERSION && !force_update {
        return Ok(bin);
    }

    let uv = match find_uv() {
        Some(uv) => uv,
        None => install_uv(app)?,
    };

    if !venv.exists() {
        status(app, "Setting up Python runtime (one-time, ~a minute)…");
        run_ok(command(&uv).args(["venv", "--python", "3.12"]).arg(&venv))?;
    }

    let dev_path = std::env::var("CANTURIA_DEV_PATH")
        .ok()
        .filter(|path| !path.trim().is_empty());
    if let Some(path) = dev_path {
        status(app, "Installing Canturía from source…");
        run_ok(
            command(&uv)
                .args(["pip", "install", "--upgrade", "--python"])
                .arg(venv_python(&venv))
                .arg("-e")
                .arg(path),
        )?;
    } else {
        status(app, "Installing Canturía…");
        run_ok(
            command(&uv)
                .args(["pip", "install", "--upgrade", "--python"])
                .arg(venv_python(&venv))
                .arg(format!("canturia[serve]=={CANTURIA_VERSION}")),
        )?;
    }
    let _ = fs::write(&marker, CANTURIA_VERSION);
    Ok(bin)
}

fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    Ok(listener.local_addr().map_err(|e| e.to_string())?.port())
}

fn kill_sidecar(sidecar: &Sidecar) {
    if let Ok(mut guard) = sidecar.0.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn spawn_sidecar(app: &AppHandle, bin: &Path) -> Result<u16, String> {
    let settings = get_settings();
    if settings.base_url.trim().is_empty() {
        return Err("Set up your ACE-Step server first".into());
    }

    let port = free_port()?;
    let out_dir = dirs::audio_dir()
        .or_else(dirs::home_dir)
        .unwrap_or_else(|| ".".into())
        .join("Canturia");

    status(app, "Starting Canturía…");
    let child = command(bin)
        .args([
            "serve",
            "--no-browser",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--out-dir",
        ])
        .arg(&out_dir)
        .spawn()
        .map_err(|e| format!("Could not start canturia: {e}"))?;

    let sidecar: State<Sidecar> = app.state();
    kill_sidecar(&sidecar);
    *sidecar.0.lock().unwrap() = Some(child);

    let deadline = Instant::now() + Duration::from_secs(30);
    let addr = format!("127.0.0.1:{port}");
    loop {
        if TcpStream::connect(&addr).is_ok() {
            std::thread::sleep(Duration::from_millis(300));
            return Ok(port);
        }
        if Instant::now() > deadline {
            return Err("Canturía server did not come up within 30s".into());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

#[tauri::command]
async fn start_server(app: AppHandle, update: bool) -> Result<u16, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if get_settings().base_url.trim().is_empty() {
            return Err("Set up your ACE-Step server first".into());
        }
        let bin = ensure_runtime(&app, update)?;
        spawn_sidecar(&app, &bin)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn restart_server(app: AppHandle) -> Result<u16, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let bin = ensure_runtime(&app, false)?;
        spawn_sidecar(&app, &bin)
    })
    .await
    .map_err(|e| e.to_string())?
}

fn main() {
    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            get_settings,
            save_settings,
            start_server,
            restart_server
        ])
        .build(tauri::generate_context!())
        .expect("error while building Canturía")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_sidecar(&app.state::<Sidecar>());
            }
        });
}
