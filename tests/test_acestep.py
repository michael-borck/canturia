from __future__ import annotations

import json
from typing import Any

import pytest

from canturia.providers.acestep import AceStepClient, AceStepError, SongRequest


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        content: bytes = b"",
        text: str = "",
        reason: str = "OK",
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.content = content
        self.text = text
        self.reason = reason

    def json(self) -> Any:
        if self.payload is None:
            raise ValueError("no json body")
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def envelope(data: Any, code: int = 200, error: Any = None) -> dict[str, Any]:
    return {"data": data, "code": code, "error": error, "timestamp": 0}


def test_submit_lyrics() -> None:
    session = FakeSession(
        [FakeResponse(payload=envelope({"task_id": "t1", "status": "queued"}))]
    )
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    task_id = client.submit(
        SongRequest(prompt="folk", lyrics="[Verse]\nhi", duration=30)
    )
    assert task_id == "t1"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://ace/release_task"
    body = kwargs["json"]
    assert body["prompt"] == "folk"
    assert body["lyrics"] == "[Verse]\nhi"
    assert body["audio_duration"] == 30.0
    assert body["batch_size"] == 1
    assert "sample_mode" not in body


def test_submit_describe_mode() -> None:
    session = FakeSession([FakeResponse(payload=envelope({"task_id": "t2"}))])
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    client.submit(
        SongRequest(prompt="folk", duration=60, sample_query="a song about rain")
    )
    body = session.calls[0][2]["json"]
    assert body["sample_mode"] is True
    assert body["sample_query"] == "a song about rain"
    assert "lyrics" not in body
    assert body["audio_duration"] == 60.0


def test_query_decodes_nested_result() -> None:
    result = json.dumps(
        [
            {
                "file": "/app/outputs/x.mp3",
                "prompt": "folk",
                "lyrics": "la",
                "metas": {"bpm": 96, "duration": 30},
            }
        ]
    )
    session = FakeSession(
        [
            FakeResponse(
                payload=envelope(
                    [
                        {
                            "task_id": "t1",
                            "status": 1,
                            "result": result,
                            "progress_text": "done",
                        }
                    ]
                )
            )
        ]
    )
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    query = client.query("t1")
    assert query.status == 1
    assert query.items[0]["file"] == "/app/outputs/x.mp3"
    assert query.items[0]["metas"]["bpm"] == 96


def test_query_running_and_failed() -> None:
    running = FakeSession(
        [
            FakeResponse(
                payload=envelope(
                    [{"task_id": "t1", "status": 0, "result": "[]"}]
                )
            )
        ]
    )
    client = AceStepClient("http://ace", session=running)  # type: ignore[arg-type]
    assert client.query("t1").status == 0

    failed_result = json.dumps([{"file": "", "error": "CUDA out of memory"}])
    failed = FakeSession(
        [
            FakeResponse(
                payload=envelope(
                    [{"task_id": "t1", "status": 2, "result": failed_result}]
                )
            )
        ]
    )
    client = AceStepClient("http://ace", session=failed)  # type: ignore[arg-type]
    query = client.query("t1")
    assert query.status == 2
    assert query.error == "CUDA out of memory"


def test_query_failed_without_reason_gets_a_useful_message() -> None:
    session = FakeSession(
        [
            FakeResponse(
                payload=envelope(
                    [
                        {
                            "task_id": "t1",
                            "status": 2,
                            "result": json.dumps([{"file": "", "status": 2}]),
                            "progress_text": "stale global log line",
                        }
                    ]
                )
            )
        ]
    )
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    query = client.query("t1")
    assert query.error is not None
    assert "Describe" in query.error


def test_wait_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    running = FakeResponse(
        payload=envelope([{"task_id": "t1", "status": 0, "result": "[]"}])
    )
    done = FakeResponse(
        payload=envelope(
            [
                {
                    "task_id": "t1",
                    "status": 1,
                    "result": json.dumps([{"file": "/app/x.mp3"}]),
                    "progress_text": "done",
                }
            ]
        )
    )
    session = FakeSession([running, done])
    monkeypatch.setattr("canturia.providers.acestep.time.sleep", lambda _: None)
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    result = client.wait("t1")
    assert result.status == 1


def test_wait_failed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = FakeResponse(
        payload=envelope(
            [
                {
                    "task_id": "t1",
                    "status": 2,
                    "result": json.dumps([{"error": "no GPU"}]),
                }
            ]
        )
    )
    monkeypatch.setattr("canturia.providers.acestep.time.sleep", lambda _: None)
    client = AceStepClient(
        "http://ace", session=FakeSession([failed])  # type: ignore[arg-type]
    )
    with pytest.raises(AceStepError, match="no GPU"):
        client.wait("t1")


def test_download_encodes_raw_path_as_params() -> None:
    session = FakeSession([FakeResponse(content=b"ID3audio")])
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    assert client.download("/app/outputs/a b.mp3") == b"ID3audio"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "http://ace/v1/audio"
    assert kwargs["params"] == {"path": "/app/outputs/a b.mp3"}


def test_download_accepts_ready_made_file_url() -> None:
    session = FakeSession([FakeResponse(content=b"ID3audio")])
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    ready = "/v1/audio?path=%2Fapp%2F.cache%2Fapi_audio%2Fx.mp3"
    assert client.download(ready) == b"ID3audio"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == f"http://ace{ready}"
    assert kwargs["params"] is None


def test_auth_headers_and_basic() -> None:
    bearer_session = FakeSession([FakeResponse(payload=envelope({}))])
    bearer = AceStepClient(
        "http://ace", api_key="tok", session=bearer_session  # type: ignore[arg-type]
    )
    bearer.health()
    assert bearer_session.calls[0][2]["headers"] == {
        "Authorization": "Bearer tok"
    }

    basic_session = FakeSession([FakeResponse(payload=envelope({}))])
    basic = AceStepClient(
        "http://ace",
        username="user",
        password="pass",
        session=basic_session,  # type: ignore[arg-type]
    )
    basic.health()
    assert basic_session.calls[0][2]["auth"] == ("user", "pass")


def test_generate_downloads_each_file() -> None:
    done_result = json.dumps(
        [
            {
                "file": "/v1/audio?path=%2Fapp%2Foutputs%2Fx.mp3",
                "prompt": "folk",
                "lyrics": "la",
                "metas": {"bpm": 90, "duration": 30},
            }
        ]
    )
    session = FakeSession(
        [
            FakeResponse(payload=envelope({"task_id": "t1"})),
            FakeResponse(
                payload=envelope(
                    [{"task_id": "t1", "status": 1, "result": done_result}]
                )
            ),
            FakeResponse(content=b"ID3audio"),
        ]
    )
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    songs = client.generate(
        SongRequest(prompt="folk", lyrics="la", duration=30)
    )
    assert len(songs) == 1
    assert songs[0].data == b"ID3audio"
    assert songs[0].remote_name == "x.mp3"
    assert songs[0].duration == 30.0


def test_error_envelope_raises() -> None:
    session = FakeSession(
        [FakeResponse(payload=envelope(None, code=500, error="bad things"))]
    )
    client = AceStepClient("http://ace", session=session)  # type: ignore[arg-type]
    with pytest.raises(AceStepError, match="bad things"):
        client.health()
