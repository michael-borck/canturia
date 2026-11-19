"""Canturía web UI: one page, two input modes, a session song gallery.

The gallery lives in memory only. Save writes to the user's Music folder and
a JSON sidecar; nothing is logged. A shared password gates hosted instances;
the desktop sidecar runs on localhost without one.
"""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from canturia import __version__
from canturia.config import resolve_settings
from canturia.core import (
    Generation,
    audio_extension,
    client_from_settings,
    generate,
    genre_options,
    lyricist_choices,
    ollama_status,
    save_song,
    slugify,
    unique_path,
)
from canturia.core import lyrics as write_lyrics_only
from canturia.lyricists.base import LyricResult
from canturia.providers import AceStepError, SongResult

SESSION_COOKIE = "canturia_session"
SESSION_TTL = 7 * 24 * 3600
MAX_SONGS = 50
MAX_JOBS = 50
MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}


@dataclass
class Song:
    id: str
    generation: Generation
    song: SongResult
    created: float
    request: dict[str, Any] = field(default_factory=dict)

    def meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.generation.mode,
            "genre": self.generation.genre,
            "style": self.generation.style,
            "duration": self.generation.duration,
            "text": self.generation.text,
            "prompt": self.song.prompt,
            "lyrics": self.song.lyrics,
            "lyricist": self.generation.lyricist,
            "lyricist_model": self.generation.lyricist_model,
            "metas": self.song.metas,
            "created": self.created,
        }


@dataclass
class Job:
    id: str
    status: str
    progress: str
    created: float
    song_ids: list[str] = field(default_factory=list)
    error: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    lyrics: dict[str, Any] | None = None


class GeneratePayload(BaseModel):
    mode: Literal["topic", "lyrics", "describe"] = "topic"
    text: str = Field(min_length=1)
    genre: str = "folk"
    style: str | None = None
    duration: float = Field(default=30, ge=10, le=600)
    lyricist: str | None = None


class LyricsPayload(BaseModel):
    topic: str = Field(min_length=1)
    genre: str = "folk"
    style: str | None = None
    duration: float = Field(default=30, ge=10, le=600)
    lyricist: str | None = None


class LoginPayload(BaseModel):
    password: str


class SavePayload(BaseModel):
    filename: str | None = None


def _payload_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


def _parse_range(header: str, length: int) -> tuple[int, int] | None:
    if not header.lower().startswith("bytes="):
        return None
    spec = header[6:].split(",")[0].strip()
    start_text, _, end_text = spec.partition("-")
    try:
        if start_text == "":
            suffix = int(end_text)
            if suffix <= 0:
                return None
            start = max(length - suffix, 0)
            end = length - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else length - 1
    except ValueError:
        return None
    if start < 0 or start > end or start >= length:
        return None
    return start, min(end, length - 1)


def _audio_response(
    data: bytes,
    *,
    media_type: str,
    filename: str,
    download: bool,
    request: Request,
) -> Response:
    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    range_header = request.headers.get("range")
    if range_header:
        selected = _parse_range(range_header, len(data))
        if selected is None:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{len(data)}"},
            )
        start, end = selected
        chunk = data[start : end + 1]
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        headers["Content-Length"] = str(len(chunk))
        return Response(
            content=chunk,
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers["Content-Length"] = str(len(data))
    return Response(content=data, media_type=media_type, headers=headers)


LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canturía — password</title>
<style>
  :root {
    --bg: #f6f5f2; --panel: #ffffff; --ink: #1d1f24; --muted: #6b7280;
    --line: #e3e1dc; --accent: #b85c38; --accent-ink: #ffffff; --danger: #c2452d;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #101216; --panel: #181b21; --ink: #e8e6e1; --muted: #8b93a1;
      --line: #262a32; --accent: #e08a5f; --accent-ink: #1b1210; --danger: #e06c50;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: var(--bg); color: var(--ink);
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    padding: 1.5rem; width: min(380px, 92vw);
  }
  h1 { margin: 0 0 .25rem; font-size: 1.35rem; }
  p { color: var(--muted); font-size: .9rem; margin: 0 0 1rem; }
  input {
    width: 100%; font: inherit; color: var(--ink); background: var(--bg);
    border: 1px solid var(--line); border-radius: 8px; padding: .55rem .7rem;
  }
  button {
    width: 100%; margin-top: .7rem; font: inherit; font-weight: 600;
    color: var(--accent-ink); background: var(--accent); border: 0;
    border-radius: 8px; padding: .55rem .7rem; cursor: pointer;
  }
  #error { color: var(--danger); font-size: .85rem; min-height: 1.2em; margin-top: .6rem; }
</style>
</head>
<body>
<form class="card" id="login">
  <h1>Canturía</h1>
  <p>This instance is password-protected.</p>
  <input id="password" type="password" autocomplete="current-password" autofocus
         placeholder="Password">
  <button type="submit">Enter</button>
  <div id="error"></div>
</form>
<script>
"use strict";
const form = document.getElementById("login");
const error = document.getElementById("error");
form.onsubmit = async (event) => {
  event.preventDefault();
  error.textContent = "";
  const password = document.getElementById("password").value;
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) {
      error.textContent = "That password is not right.";
      return;
    }
    window.location.reload();
  } catch (err) {
    error.textContent = "Could not reach the server.";
  }
};
</script>
</body>
</html>
"""


def create_app(
    config: dict[str, Any],
    *,
    password: str | None = None,
    out_dir: Path | None = None,
    generate_fn: Callable[..., Generation] | None = None,
    client_factory: Callable[[], Any] | None = None,
    ollama_status_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    lyrics_fn: Callable[..., LyricResult] | None = None,
    lyricist_options_fn: Callable[[dict[str, Any]], list[dict[str, Any]]]
    | None = None,
    desktop: bool = False,
) -> FastAPI:
    """Build the Canturía web app around a loaded config."""
    settings = resolve_settings(config)
    app_password = password or ""
    save_dir = (out_dir or Path.cwd()).expanduser().resolve()
    index_html = (
        resources.files("canturia").joinpath("serve_page.html").read_text("utf-8")
    )

    def desktop_index() -> str:
        script = (
            "<script>window.CANTURIA_TOKEN = "
            f"{json.dumps(app_password)};</script>"
        )
        return index_html.replace("</head>", script + "</head>", 1)
    run_generation = generate_fn or generate
    make_client = client_factory or (lambda: client_from_settings(settings))
    get_ollama = ollama_status_fn or ollama_status
    run_lyrics = lyrics_fn or write_lyrics_only
    get_lyricists = lyricist_options_fn or lyricist_choices

    songs: dict[str, Song] = {}
    jobs: dict[str, Job] = {}
    sessions: dict[str, float] = {}
    lock = threading.Lock()

    def supplied_token(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return request.query_params.get("token") or request.cookies.get(
            SESSION_COOKIE
        )

    def session_ok(request: Request) -> bool:
        if not app_password:
            return True
        token = supplied_token(request)
        if not token:
            return False
        if secrets.compare_digest(token, app_password):
            return True
        with lock:
            created = sessions.get(token)
            if created is None:
                return False
            if time.time() - created > SESSION_TTL:
                sessions.pop(token, None)
                return False
        return True

    def require_auth(request: Request) -> None:
        if not session_ok(request):
            raise HTTPException(status_code=401, detail="Password required")

    def set_session_cookie(response: Response, request: Request) -> None:
        token = secrets.token_urlsafe(32)
        with lock:
            sessions[token] = time.time()
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_TTL,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )

    def evict_jobs_locked() -> None:
        while len(jobs) > MAX_JOBS:
            removable = next(
                (
                    job_id
                    for job_id, job in jobs.items()
                    if job.status in ("done", "failed")
                ),
                None,
            )
            if removable is None:
                break
            del jobs[removable]

    def evict_songs_locked() -> None:
        while len(songs) > MAX_SONGS:
            del songs[next(iter(songs))]

    def set_progress(job_id: str, message: str) -> None:
        with lock:
            job = jobs.get(job_id)
            if job and job.status in ("queued", "running"):
                job.status = "running"
                job.progress = message

    def run_job(job_id: str, payload: GeneratePayload) -> None:
        with lock:
            job = jobs.get(job_id)
            if job:
                job.status = "running"
                job.progress = "submitting"
        try:
            generation = run_generation(
                payload.mode,
                payload.text,
                settings,
                genre=payload.genre,
                style=payload.style,
                duration=payload.duration,
                lyricist=payload.lyricist,
                on_progress=lambda message: set_progress(job_id, message),
            )
            requested = _payload_dict(payload)
            with lock:
                job = jobs.get(job_id)
                if job is None:
                    return
                for result in generation.songs:
                    song_id = secrets.token_urlsafe(8)
                    songs[song_id] = Song(
                        id=song_id,
                        generation=generation,
                        song=result,
                        created=time.time(),
                        request=requested,
                    )
                    job.song_ids.append(song_id)
                evict_songs_locked()
                job.status = "done"
                job.progress = "done"
        except Exception as exc:  # background thread: keep the failure visible
            with lock:
                job = jobs.get(job_id)
                if job:
                    job.status = "failed"
                    job.error = str(exc)
                    job.progress = ""

    def start_job(payload: GeneratePayload) -> str:
        job_id = secrets.token_urlsafe(8)
        with lock:
            jobs[job_id] = Job(
                id=job_id,
                status="queued",
                progress="queued",
                created=time.time(),
                request=_payload_dict(payload),
            )
            evict_jobs_locked()
        threading.Thread(
            target=run_job, args=(job_id, payload), daemon=True
        ).start()
        return job_id

    def run_lyrics_job(job_id: str, payload: LyricsPayload) -> None:
        with lock:
            job = jobs.get(job_id)
            if job:
                job.status = "running"
                job.progress = "writing lyrics…"
        try:
            result = run_lyrics(
                payload.topic,
                settings,
                genre=payload.genre,
                style=payload.style,
                duration=payload.duration,
                lyricist=payload.lyricist,
                on_progress=lambda message: set_progress(job_id, message),
            )
            with lock:
                job = jobs.get(job_id)
                if job is None:
                    return
                job.lyrics = {
                    "lyrics": result.lyrics,
                    "provider": result.provider,
                    "model": result.model,
                    "caption": result.caption,
                    "error": result.error,
                }
                job.status = "done"
                job.progress = "done"
        except Exception as exc:
            with lock:
                job = jobs.get(job_id)
                if job:
                    job.status = "failed"
                    job.error = str(exc)
                    job.progress = ""

    def start_lyrics_job(payload: LyricsPayload) -> str:
        job_id = secrets.token_urlsafe(8)
        with lock:
            jobs[job_id] = Job(
                id=job_id,
                status="queued",
                progress="queued",
                created=time.time(),
                request=_payload_dict(payload),
            )
            evict_jobs_locked()
        threading.Thread(
            target=run_lyrics_job, args=(job_id, payload), daemon=True
        ).start()
        return job_id

    app = FastAPI(title="Canturía", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        supplied = request.query_params.get("password")
        if app_password and supplied is not None and secrets.compare_digest(
            supplied, app_password
        ):
            if desktop:
                # A Tauri iframe is cross-site; WKWebView drops the session
                # cookie. Embed the per-launch token and use bearer auth.
                return HTMLResponse(desktop_index())
            response = RedirectResponse("/", status_code=303)
            set_session_cookie(response, request)
            return response
        if not session_ok(request):
            return HTMLResponse(LOGIN_HTML)
        return HTMLResponse(index_html)

    @app.post("/api/login")
    def login(payload: LoginPayload, request: Request) -> Response:
        if app_password and not secrets.compare_digest(
            payload.password, app_password
        ):
            # Slow down trivial brute force on a hosted instance.
            time.sleep(0.5)
            raise HTTPException(status_code=401, detail="Wrong password")
        response = JSONResponse({"ok": True})
        if app_password:
            set_session_cookie(response, request)
        return response

    @app.post("/api/logout")
    def logout(request: Request) -> Response:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            with lock:
                sessions.pop(token, None)
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/api/config", dependencies=[Depends(require_auth)])
    def api_config() -> dict[str, Any]:
        return {
            "version": __version__,
            "base_url": settings.get("base_url"),
            "auth": bool(app_password),
            "genres": genre_options(),
            "durations": [30, 45, 60],
            "genre": settings.get("genre") or "folk",
            "style": settings.get("style") or "",
            "duration": settings.get("duration") or 30,
            "vocal_language": settings.get("vocal_language") or "en",
            "thinking": bool(settings.get("thinking", True)),
            "default_mode": "topic",
            "desktop": desktop,
            "lyricist": settings.get("lyricist") or "ollama",
            "ollama_model": (settings.get("ollama") or {}).get("model"),
        }

    @app.get("/api/lyricists", dependencies=[Depends(require_auth)])
    def api_lyricists() -> dict[str, Any]:
        return {
            "default": settings.get("lyricist") or "ollama",
            "lyricists": get_lyricists(settings),
        }

    @app.post("/api/lyrics", dependencies=[Depends(require_auth)])
    def api_lyrics(payload: LyricsPayload) -> dict[str, Any]:
        return {"job_id": start_lyrics_job(payload)}

    @app.get("/api/ollama", dependencies=[Depends(require_auth)])
    def api_ollama() -> dict[str, Any]:
        return get_ollama(settings)

    @app.get("/api/health", dependencies=[Depends(require_auth)])
    def api_health() -> dict[str, Any]:
        try:
            client = make_client()
            try:
                client.request_timeout = min(
                    float(getattr(client, "request_timeout", 8)), 8.0
                )
            except (AttributeError, TypeError, ValueError):
                pass
            return client.health()
        except (AceStepError, ValueError) as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @app.post("/api/generate", dependencies=[Depends(require_auth)])
    def api_generate(payload: GeneratePayload) -> dict[str, Any]:
        return {"job_id": start_job(payload)}

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(require_auth)])
    def api_job(job_id: str) -> dict[str, Any]:
        with lock:
            job = jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="No such job")
            metas = [
                songs[song_id].meta()
                for song_id in job.song_ids
                if song_id in songs
            ]
            return {
                "job_id": job.id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "songs": metas,
                "lyrics": job.lyrics,
            }

    @app.get("/api/songs", dependencies=[Depends(require_auth)])
    def api_songs() -> dict[str, Any]:
        with lock:
            return {"songs": [song.meta() for song in songs.values()]}

    @app.get("/api/songs/{song_id}", dependencies=[Depends(require_auth)])
    def api_song(
        song_id: str, request: Request, download: bool = False
    ) -> Response:
        with lock:
            item = songs.get(song_id)
        if item is None:
            raise HTTPException(status_code=404, detail="No such song")
        extension = audio_extension(item.song.data, item.song.remote_name)
        filename = slugify(item.generation.text) + extension
        return _audio_response(
            item.song.data,
            media_type=MEDIA_TYPES.get(extension, "audio/mpeg"),
            filename=filename,
            download=download,
            request=request,
        )

    @app.delete("/api/songs/{song_id}", dependencies=[Depends(require_auth)])
    def api_delete(song_id: str) -> dict[str, Any]:
        with lock:
            if song_id not in songs:
                raise HTTPException(status_code=404, detail="No such song")
            del songs[song_id]
        return {"deleted": song_id}

    @app.post(
        "/api/songs/{song_id}/save", dependencies=[Depends(require_auth)]
    )
    def api_save(
        song_id: str, payload: SavePayload | None = None
    ) -> dict[str, Any]:
        with lock:
            item = songs.get(song_id)
        if item is None:
            raise HTTPException(status_code=404, detail="No such song")

        requested = (payload.filename or "").strip() if payload else ""
        if requested:
            name = Path(requested).name
            if not name or name.startswith("."):
                raise HTTPException(status_code=400, detail="Bad filename")
            target = save_dir / name
            if target.exists():
                target = unique_path(target)
            path, sidecar = save_song(
                item.generation, item.song, out=str(target)
            )
        else:
            path, sidecar = save_song(
                item.generation, item.song, out_dir=save_dir
            )
        return {"path": str(path), "metadata": str(sidecar)}

    @app.post(
        "/api/songs/{song_id}/again", dependencies=[Depends(require_auth)]
    )
    def api_again(song_id: str) -> dict[str, Any]:
        with lock:
            item = songs.get(song_id)
        if item is None:
            raise HTTPException(status_code=404, detail="No such song")
        payload = GeneratePayload(**item.request)
        return {"job_id": start_job(payload)}

    return app
