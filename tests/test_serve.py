from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from canturia.core import Generation
from canturia.lyricists import LyricResult
from canturia.providers import SongRequest, SongResult
from canturia.serve import create_app

CONFIG: dict[str, Any] = {
    "base_url": "http://ace",
    "genre": "folk",
    "style": "",
    "duration": 30,
    "vocal_language": "en",
    "thinking": True,
    "lyricist": "ollama",
    "lyricists": {
        "ollama": {"base_url": "http://ollama", "model": "qwen3.5:4b"},
        "openai-compatible": {
            "base_url": "http://lyrics/v1",
            "model": "test-model",
        },
    },
    "ollama": {
        "base_url": "http://ollama",
        "model": "qwen3.5:4b",
        "timeout": 90,
    },
    "serve": {"host": "127.0.0.1", "port": 2268},
}


def fake_ollama_status(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "model": "qwen3.5:4b",
        "models": ["qwen3.5:4b", "gemma3:4b"],
        "error": None,
    }


def fake_lyricists(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "ollama",
            "label": "Ollama (local)",
            "model": "qwen3.5:4b",
            "models": ["qwen3.5:4b"],
            "available": True,
            "error": None,
        },
        {
            "name": "openai-compatible",
            "label": "OpenAI-compatible (BYOK)",
            "model": "test-model",
            "models": ["test-model"],
            "available": True,
            "error": None,
        },
        {
            "name": "acestep",
            "label": "ACE-Step LM (experimental)",
            "model": "ACE-Step 5Hz LM",
            "models": [],
            "available": False,
            "error": "off",
        },
    ]


def fake_lyrics(
    topic: str,
    settings: dict[str, Any],
    *,
    genre: str | None = None,
    style: str | None = None,
    duration: Any = None,
    lyricist: str | None = None,
    language: str | None = None,
    on_progress: Any = None,
) -> LyricResult:
    if on_progress:
        on_progress("writing lyrics")
    return LyricResult(
        lyrics="[Verse]\npreview words",
        provider=lyricist or "ollama",
        model="qwen3.5:4b",
    )


class FakeClient:
    request_timeout = 5.0

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "models_initialized": True,
            "llm_initialized": False,
            "loaded_model": "acestep-v15-turbo",
        }

    def models(self) -> list[str]:
        return ["acestep-v15-turbo"]

    def lora_status(self) -> dict[str, Any]:
        return {"lora_loaded": True, "use_lora": True, "lora_scale": 1.0}

    def lora_load(self, path: str, name: str | None = None) -> dict[str, Any]:
        return {"message": f"loaded {path}", "adapter_name": name}

    def lora_unload(self) -> dict[str, Any]:
        return {"message": "unloaded"}

    def lora_toggle(self, use_lora: bool) -> dict[str, Any]:
        return {"use_lora": use_lora}

    def lora_scale(
        self, scale: float, name: str | None = None
    ) -> dict[str, Any]:
        return {"scale": scale, "adapter_name": name}


def fake_generate(
    mode: str,
    text: str,
    settings: dict[str, Any],
    *,
    genre: str | None = None,
    style: str | None = None,
    duration: Any = None,
    lyricist: str | None = None,
    on_progress: Any = None,
    **kwargs: Any,
) -> Generation:
    if on_progress:
        on_progress("rendering")
    seconds = float(duration or 30)
    if mode == "topic":
        lyrics = "[Verse]\nollama words"
    elif mode == "lyrics":
        lyrics = text
    else:
        lyrics = ""
    if kwargs.get("instrumental"):
        lyrics = "[Instrumental]"
    request = SongRequest(
        prompt="gentle acoustic folk",
        lyrics=lyrics,
        duration=seconds,
        sample_query=text if mode == "describe" else None,
        thinking=True,
        vocal_language=kwargs.get("vocal_language") or "en",
        bpm=kwargs.get("bpm"),
        key_scale=kwargs.get("key_scale"),
        time_signature=kwargs.get("time_signature"),
        seed=kwargs.get("seed"),
        model=kwargs.get("model"),
        inference_steps=kwargs.get("inference_steps"),
        guidance_scale=kwargs.get("guidance_scale"),
        instrumental=bool(kwargs.get("instrumental")),
    )
    return Generation(
        songs=[
            SongResult(
                data=b"ID3fake-audio",
                file_path="/app/outputs/x.mp3",
                prompt=request.prompt,
                lyrics=request.lyrics,
                metas={"bpm": 96, "duration": seconds},
                remote_name="x.mp3",
                duration=seconds,
            )
        ],
        mode=mode,
        genre=genre or "folk",
        style=style or "",
        text=text,
        style_prompt=request.prompt,
        duration=seconds,
        request=request,
        lyricist=(
            "ollama" if mode == "topic"
            else ("user" if mode == "lyrics" else "acestep")
        ),
        lyricist_model=(
            "qwen3.5:4b" if mode == "topic"
            else ("ACE-Step 5Hz LM" if mode == "describe" else None)
        ),
    )


def make_app(
    tmp_path: Path,
    password: str | None = None,
    desktop: bool = False,
):
    return create_app(
        CONFIG,
        password=password,
        out_dir=tmp_path,
        desktop=desktop,
        generate_fn=fake_generate,
        client_factory=FakeClient,
        ollama_status_fn=fake_ollama_status,
        lyrics_fn=fake_lyrics,
        lyricist_options_fn=fake_lyricists,
    )


def wait_for_job(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_page_and_config(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Canturía" in page.text
        config = client.get("/api/config").json()
        assert config["base_url"] == "http://ace"
        assert any(genre["key"] == "folk" for genre in config["genres"])
        assert config["durations"] == [30, 45, 60]
        assert config["default_mode"] == "topic"
        assert config["lyricist"] == "ollama"
        assert config["ollama_model"] == "qwen3.5:4b"
        assert client.get("/api/health").json()["llm_initialized"] is False
        ollama = client.get("/api/ollama").json()
        assert ollama["ok"] is True
        assert ollama["model"] == "qwen3.5:4b"
        options = client.get("/api/lyricists").json()
        assert options["default"] == "ollama"
        assert any(item["name"] == "openai-compatible" for item in options["lyricists"])


def test_library_endpoints(
    tmp_path: Path, monkeypatch: Any
) -> None:
    audio = tmp_path / "saved.mp3"
    audio.write_bytes(b"ID3saved")
    audio.with_suffix(".mp3.json").write_text(
        json.dumps(
            {
                "source_text": "a saved song",
                "genre": "folk",
                "duration": 30,
                "lyrics": "[Verse]\nhello",
            }
        ),
        encoding="utf-8",
    )
    with TestClient(make_app(tmp_path)) as client:
        songs = client.get("/api/library").json()["songs"]
        assert songs[0]["id"] == "saved.mp3"
        assert songs[0]["title"] == "a saved song"
        assert client.get("/api/library/saved.mp3").content == b"ID3saved"
        download = client.get("/api/library/saved.mp3?download=1")
        assert "attachment" in download.headers["content-disposition"]
        assert client.delete("/api/library/saved.mp3").status_code == 200
        assert client.get("/api/library/saved.mp3").status_code == 404

    audio.write_bytes(b"ID3saved")
    monkeypatch.setattr("canturia.serve.reveal_folder", lambda path: None)
    with TestClient(make_app(tmp_path, desktop=True)) as client:
        assert client.post("/api/library/reveal").status_code == 200


def test_password_gate(tmp_path: Path) -> None:
    with TestClient(
        make_app(tmp_path, password="secret"),
        follow_redirects=False,
    ) as redirect_client:
        redirect = redirect_client.get("/?password=secret")
        assert redirect.status_code == 303
    with TestClient(make_app(tmp_path, password="secret")) as client:
        login_page = client.get("/")
        assert "password-protected" in login_page.text
        assert client.get("/api/config").status_code == 401
        assert (
            client.post("/api/login", json={"password": "wrong"}).status_code
            == 401
        )
        assert (
            client.post("/api/login", json={"password": "secret"}).status_code
            == 200
        )
        assert client.get("/api/config").status_code == 200
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/config").status_code == 401


def test_desktop_auto_login_with_url_password(tmp_path: Path) -> None:
    with TestClient(
        make_app(tmp_path, password="secret", desktop=True),
        follow_redirects=False,
    ) as client:
        response = client.get("/?password=secret")
        assert response.status_code == 200
        assert "CANTURIA_TOKEN" in response.text
        assert "password-protected" not in response.text
        # A Tauri iframe is cross-site, so the desktop page uses bearer auth
        # rather than a cookie.
        config = client.get(
            "/api/config",
            headers={"Authorization": "Bearer secret"},
        )
        assert config.status_code == 200
        assert config.json()["desktop"] is True
        query = client.get("/api/config?token=secret")
        assert query.status_code == 200
    with TestClient(
        make_app(tmp_path, password="secret", desktop=True),
        follow_redirects=False,
    ) as other:
        wrong = other.get("/?password=nope")
        assert wrong.status_code == 200
        assert "password-protected" in wrong.text


def test_generate_download_save_again_delete(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.post(
            "/api/generate",
            json={
                "mode": "lyrics",
                "text": "[Verse]\nMorning light",
                "genre": "folk",
                "duration": 30,
            },
        )
        assert response.status_code == 200
        job = wait_for_job(client, response.json()["job_id"])
        assert job["status"] == "done"
        assert len(job["songs"]) == 1
        song = job["songs"][0]

        audio = client.get(f"/api/songs/{song['id']}")
        assert audio.status_code == 200
        assert audio.content == b"ID3fake-audio"

        ranged = client.get(
            f"/api/songs/{song['id']}", headers={"Range": "bytes=0-2"}
        )
        assert ranged.status_code == 206
        assert ranged.content == b"ID3"

        download = client.get(f"/api/songs/{song['id']}?download=1")
        assert "attachment" in download.headers["content-disposition"]

        saved = client.post(
            f"/api/songs/{song['id']}/save", json={"filename": "mine.mp3"}
        )
        assert saved.status_code == 200
        assert Path(saved.json()["path"]).exists()
        assert Path(saved.json()["metadata"]).exists()

        again = client.post(f"/api/songs/{song['id']}/again")
        assert again.status_code == 200
        assert wait_for_job(client, again.json()["job_id"])["status"] == "done"

        assert client.delete(f"/api/songs/{song['id']}").status_code == 200
        assert client.get(f"/api/songs/{song['id']}").status_code == 404


def test_topic_job_uses_ollama_lyrics(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.post(
            "/api/generate",
            json={
                "mode": "topic",
                "text": "a song about rain",
                "genre": "folk",
                "duration": 45,
            },
        )
        job = wait_for_job(client, response.json()["job_id"])
        song = job["songs"][0]
        assert song["mode"] == "topic"
        assert song["text"] == "a song about rain"
        assert song["lyrics"] == "[Verse]\nollama words"
        assert song["duration"] == 45
        assert song["lyricist"] == "ollama"
        assert song["lyricist_model"] == "qwen3.5:4b"


def test_advanced_generate_and_lora_endpoints(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.post(
            "/api/generate",
            json={
                "mode": "lyrics",
                "text": "words",
                "genre": "folk",
                "duration": 30,
                "instrumental": True,
                "vocal_language": "es",
                "bpm": 90,
                "key_scale": "C major",
                "time_signature": "4/4",
                "seed": 42,
                "model": "acestep-v15-turbo",
                "inference_steps": 20,
                "guidance_scale": 6.5,
            },
        )
        job = wait_for_job(client, response.json()["job_id"])
        song = job["songs"][0]
        assert song["instrumental"] is True
        assert song["bpm"] == 90
        assert song["key_scale"] == "C major"
        assert song["time_signature"] == "4/4"
        assert song["seed"] == 42
        assert song["lyrics"] == "[Instrumental]"

        assert client.get("/api/models").json()["models"] == [
            "acestep-v15-turbo"
        ]
        assert client.get("/api/lora").json()["status"]["lora_loaded"] is True
        assert client.post(
            "/api/lora/load", json={"path": "/loras/a", "name": "a"}
        ).status_code == 200
        assert client.post(
            "/api/lora/toggle", json={"use_lora": False}
        ).json()["result"]["use_lora"] is False
        assert client.post(
            "/api/lora/scale", json={"scale": 0.6}
        ).json()["result"]["scale"] == 0.6
        assert client.post("/api/lora/unload").status_code == 200


def test_preview_lyrics_job(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.post(
            "/api/lyrics",
            json={
                "topic": "a song about rain",
                "genre": "folk",
                "duration": 30,
                "lyricist": "openai-compatible",
            },
        )
        assert response.status_code == 200
        job = wait_for_job(client, response.json()["job_id"])
        assert job["status"] == "done"
        assert job["lyrics"]["lyrics"] == "[Verse]\npreview words"
        assert job["lyrics"]["provider"] == "openai-compatible"


def test_describe_job_and_invalid_duration(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.post(
            "/api/generate",
            json={
                "mode": "describe",
                "text": "a song about rain",
                "genre": "indie",
                "duration": 45,
            },
        )
        job = wait_for_job(client, response.json()["job_id"])
        assert job["songs"][0]["mode"] == "describe"
        assert job["songs"][0]["duration"] == 45

        bad = client.post(
            "/api/generate",
            json={
                "mode": "lyrics",
                "text": "words",
                "genre": "folk",
                "duration": 5,
            },
        )
        assert bad.status_code == 422

        no_genre = client.post(
            "/api/generate",
            json={
                "mode": "lyrics",
                "text": "words",
                "genre": "",
                "duration": 30,
            },
        )
        assert no_genre.status_code == 422


def test_save_without_filename_uses_out_dir(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.post(
            "/api/generate",
            json={
                "mode": "describe",
                "text": "a song about rain",
                "genre": "indie",
                "duration": 30,
            },
        )
        job = wait_for_job(client, response.json()["job_id"])
        song_id = job["songs"][0]["id"]
        saved = client.post(f"/api/songs/{song_id}/save", json={})
        assert saved.status_code == 200
        path = Path(saved.json()["path"])
        assert path.parent == tmp_path
        assert path.exists()
