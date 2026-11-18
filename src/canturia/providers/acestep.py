"""Thin ACE-Step 1.5 HTTP client: submit, poll, download.

The API is asynchronous and returns a small envelope around its payload::

    {"data": ..., "code": 200, "error": null, "timestamp": ...}

``/query_result`` nests another JSON string in ``data[0].result``. That string
decodes to a list with the generated file path, so it must be decoded a second
time. Paths are server-side paths; ``/v1/audio?path=`` wants them URL-encoded,
which ``requests`` does when passed through ``params``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

ProgressFn = Callable[[str], None]


class AceStepError(Exception):
    """Raised when ACE-Step cannot be reached or returns an error."""


@dataclass
class SongRequest:
    """One ACE-Step generation request."""

    prompt: str
    lyrics: str = ""
    duration: float = 30.0
    sample_query: str | None = None
    model: str | None = None
    batch_size: int = 1


@dataclass
class SongResult:
    """One generated audio file."""

    data: bytes
    file_path: str
    prompt: str
    lyrics: str
    metas: dict[str, Any] = field(default_factory=dict)
    remote_name: str = ""
    duration: float | None = None


@dataclass
class QueryResult:
    """One task's status from ``/query_result``."""

    task_id: str
    status: int
    items: list[dict[str, Any]] = field(default_factory=list)
    progress_text: str = ""
    error: str | None = None


def _detail(response: requests.Response) -> str:
    """Best-effort readable error from a failed HTTP response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error")
        if detail:
            return str(detail)
    return response.text.strip() or response.reason


def _decode_result(raw: Any) -> list[dict[str, Any]]:
    """``data[0].result`` is a JSON string containing a list of result dicts."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AceStepClient:
    """A small synchronous client for one ACE-Step server."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 900.0,
        request_timeout: float = 60.0,
        poll_interval: float = 2.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        self.username = username or None
        self.password = password or None
        self.timeout = float(timeout)
        self.request_timeout = float(request_timeout)
        self.poll_interval = float(poll_interval)
        self.session = session or requests.Session()

    def _auth(self) -> tuple[str, str] | None:
        if self.username and self.password:
            return (self.username, self.password)
        return None

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _request_url(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=self._headers(),
                auth=self._auth(),
                timeout=self.request_timeout,
            )
        except requests.RequestException as e:
            raise AceStepError(
                f"Could not reach ACE-Step at {self.base_url}: {e}"
            ) from e
        if response.status_code >= 400:
            raise AceStepError(
                f"ACE-Step returned {response.status_code}: {_detail(response)}"
            )
        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self._request_url(
            method,
            f"{self.base_url}{path}",
            json_body=json_body,
            params=params,
        )

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        """Open ACE-Step's ``{data, code, error, timestamp}`` envelope."""
        if isinstance(payload, dict) and "data" in payload and "code" in payload:
            code = payload.get("code")
            if code not in (None, 200):
                error = payload.get("error") or f"ACE-Step error code {code}"
                raise AceStepError(str(error))
            return payload.get("data")
        return payload

    @staticmethod
    def _task_id(data: Any) -> str:
        candidates: list[Any] = []
        if isinstance(data, dict):
            candidates.append(data)
        elif isinstance(data, list):
            candidates.extend(item for item in data if isinstance(item, dict))
        for item in candidates:
            task_id = item.get("task_id")
            if isinstance(task_id, str) and task_id:
                return task_id
        raise AceStepError("ACE-Step accepted the request but returned no task_id")

    def health(self) -> dict[str, Any]:
        """Return ``/health`` data (model and LM readiness, queue state)."""
        response = self._request("GET", "/health")
        data = self._unwrap(response.json())
        return data if isinstance(data, dict) else {}

    def submit(self, request: SongRequest) -> str:
        """Queue a generation and return its task id."""
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "audio_duration": float(request.duration),
            "batch_size": 1,
        }
        if request.sample_query:
            payload["sample_mode"] = True
            payload["sample_query"] = request.sample_query
        else:
            payload["lyrics"] = request.lyrics
        if request.model:
            payload["model"] = request.model

        response = self._request("POST", "/release_task", json_body=payload)
        return self._task_id(self._unwrap(response.json()))

    def query(self, task_id: str) -> QueryResult:
        """Fetch one task's current status and results."""
        response = self._request(
            "POST",
            "/query_result",
            json_body={"task_id_list": [task_id]},
        )
        data = self._unwrap(response.json())
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        else:
            items = []

        item = items[0] if items else {}
        status = int(item.get("status", 0) or 0)
        decoded = _decode_result(item.get("result"))
        error = None
        if status == 2 and decoded:
            error = decoded[0].get("error")
        if status == 2 and not error:
            # The API sometimes fails without a reason. Its progress_text is a
            # global log line (often stale), so never use it as the error.
            error = (
                "Generation failed. If this was Describe mode, the server's "
                "lyrics writer may be off; set resident: true in puente.yml "
                "and restart the service."
            )
        return QueryResult(
            task_id=task_id,
            status=status,
            items=decoded,
            progress_text=str(item.get("progress_text") or ""),
            error=str(error) if error else None,
        )

    def wait(
        self,
        task_id: str,
        *,
        on_progress: ProgressFn | None = None,
        timeout: float | None = None,
    ) -> QueryResult:
        """Poll until the task finishes, fails, or the client timeout expires."""
        deadline = time.monotonic() + (
            self.timeout if timeout is None else float(timeout)
        )
        last_message = ""
        while True:
            result = self.query(task_id)
            message = result.progress_text or (
                "queued" if result.status == 0 else ""
            )
            if on_progress and message and message != last_message:
                on_progress(message)
                last_message = message
            if result.status == 1:
                return result
            if result.status == 2:
                raise AceStepError(result.error or "Generation failed")
            if time.monotonic() > deadline:
                raise AceStepError(
                    "Timed out waiting for ACE-Step. The first cold request "
                    "can take several minutes while weights download; try "
                    "again or raise 'timeout' in the config."
                )
            time.sleep(self.poll_interval)

    @staticmethod
    def _remote_name(file_path: str) -> str:
        """Recover the filename from either a raw path or a /v1/audio URL."""
        parsed = urlparse(file_path)
        if parsed.path.endswith("/v1/audio"):
            encoded = parse_qs(parsed.query).get("path", [""])[0]
            return Path(encoded).name
        return Path(parsed.path or file_path).name

    def download(self, file_path: str) -> bytes:
        """Download one generated file.

        ACE-Step returns ``file`` as a ready-to-use relative URL such as
        ``/v1/audio?path=%2Fapp%2F...``. Older/hand-built payloads may return a
        raw server path instead; support both.
        """
        if not file_path:
            raise AceStepError("ACE-Step returned an empty file path")
        if file_path.startswith(("http://", "https://")):
            response = self._request_url("GET", file_path)
        elif file_path.startswith("/v1/audio"):
            response = self._request_url("GET", f"{self.base_url}{file_path}")
        else:
            response = self._request(
                "GET",
                "/v1/audio",
                params={"path": file_path},
            )
        if not response.content:
            raise AceStepError(f"ACE-Step returned an empty file for {file_path}")
        return response.content

    def generate(
        self,
        request: SongRequest,
        *,
        on_progress: ProgressFn | None = None,
    ) -> list[SongResult]:
        """Submit, wait, and download every file the task produced."""
        task_id = self.submit(request)
        result = self.wait(task_id, on_progress=on_progress)

        songs: list[SongResult] = []
        for item in result.items:
            file_path = str(item.get("file") or "")
            if not file_path:
                continue
            data = self.download(file_path)
            metas = item.get("metas")
            songs.append(
                SongResult(
                    data=data,
                    file_path=file_path,
                    prompt=str(item.get("prompt") or request.prompt),
                    lyrics=str(item.get("lyrics") or request.lyrics),
                    metas=metas if isinstance(metas, dict) else {},
                    remote_name=self._remote_name(file_path),
                    duration=_as_float(
                        (metas or {}).get("duration")
                        if isinstance(metas, dict)
                        else None
                    ),
                )
            )

        if not songs:
            raise AceStepError(
                "Generation finished but ACE-Step returned no audio file"
            )
        return songs
