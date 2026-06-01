# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the export-splunk worker."""

import asyncio
import base64
import json

import pytest

from src import hec_uploader, tasks
from src.hec_uploader import HECUploader, UploadResult


@pytest.fixture(autouse=True)
def _silence_celery_events(monkeypatch):
    """Stop ``self.send_event`` from trying to publish to a real broker."""
    monkeypatch.setattr(
        tasks.upload, "send_event", lambda *args, **kwargs: None, raising=False
    )


class _FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in for tests."""

    def __init__(self, responses):
        # responses: list of (status, text) tuples, consumed in order; the last
        # tuple is reused forever once we run off the end.
        self._responses = list(responses)
        self.posts: list[dict] = []

    def post(self, url, data, headers):
        self.posts.append({"url": url, "data": data, "headers": headers})
        status, text = self._responses[0] if len(self._responses) == 1 else self._responses.pop(0)
        return _FakeResponse(status, text)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _write_jsonl(tmp_path, lines: list[dict]) -> str:
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return str(path)


def test_wrap_event_builds_envelope():
    uploader = HECUploader(
        file_path="/dev/null",
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        sourcetype="st",
        host="h",
        source="s",
        endpoint="event",
    )
    encoded = uploader._wrap_event('{"a": 1}')
    envelope = json.loads(encoded.decode("utf-8"))
    assert envelope == {
        "event": {"a": 1},
        "index": "idx",
        "sourcetype": "st",
        "host": "h",
        "source": "s",
    }


def test_wrap_event_preserves_non_json_line():
    uploader = HECUploader(
        file_path="/dev/null",
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    envelope = json.loads(uploader._wrap_event("not json").decode("utf-8"))
    assert envelope["event"] == "not json"


def test_raw_url_includes_metadata_params():
    uploader = HECUploader(
        file_path="/dev/null",
        hec_url="https://hec.example.com/",
        token="tok",
        index="idx",
        sourcetype="st",
        host="h",
        source="s",
        endpoint="raw",
    )
    url = uploader._post_url
    assert url.startswith("https://hec.example.com/services/collector/raw?")
    assert "index=idx" in url
    assert "sourcetype=st" in url
    assert "host=h" in url
    assert "source=s" in url


def test_uploader_batches_and_reports_success(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": i} for i in range(3)])
    fake_session = _FakeSession([(200, "")])

    monkeypatch.setattr(
        hec_uploader.aiohttp, "ClientSession", lambda connector=None: fake_session
    )
    monkeypatch.setattr(hec_uploader.aiohttp, "TCPConnector", lambda **kw: None)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.success_count == 3
    assert result.failed_count == 0
    assert len(fake_session.posts) == 1
    # Payload is three newline-delimited envelopes.
    assert fake_session.posts[0]["data"].count(b"\n") == 3
    assert fake_session.posts[0]["headers"]["Authorization"] == "Splunk tok"


def test_uploader_retries_then_fails(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": 1}])
    # Always 500 — should retry MAX_RETRIES times and mark the batch failed.
    fake_session = _FakeSession([(500, "boom")])

    monkeypatch.setattr(
        hec_uploader.aiohttp, "ClientSession", lambda connector=None: fake_session
    )
    monkeypatch.setattr(hec_uploader.aiohttp, "TCPConnector", lambda **kw: None)
    monkeypatch.setattr(hec_uploader, "RETRY_BACKOFF_SECONDS", 0)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.success_count == 0
    assert result.failed_count == 1
    assert any(key.startswith("500_") for key in result.error_dict)
    assert len(fake_session.posts) == hec_uploader.MAX_RETRIES
    assert result.permanent_error is None


def _install_fake_session(monkeypatch, fake_session):
    monkeypatch.setattr(
        hec_uploader.aiohttp, "ClientSession", lambda connector=None: fake_session
    )
    monkeypatch.setattr(hec_uploader.aiohttp, "TCPConnector", lambda **kw: None)
    monkeypatch.setattr(hec_uploader, "RETRY_BACKOFF_SECONDS", 0)


def test_uploader_fails_fast_on_invalid_index(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(400, '{"text":"Incorrect index","code":7}')])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="missing_index",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.failed_count == 1
    assert result.success_count == 0
    assert len(fake_session.posts) == 1  # no retries
    assert result.permanent_error is not None
    assert "code 7" in result.permanent_error
    assert "Incorrect index" in result.permanent_error


def test_uploader_fails_fast_on_invalid_token(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(401, '{"text":"Invalid token","code":4}')])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="bad",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.failed_count == 1
    assert len(fake_session.posts) == 1
    assert "code 4" in result.permanent_error


def test_uploader_fails_fast_on_403(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(403, "forbidden")])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.failed_count == 1
    assert len(fake_session.posts) == 1
    assert result.permanent_error is not None
    assert "HTTP 403" in result.permanent_error


def test_uploader_retries_400_for_per_event_failures(tmp_path, monkeypatch):
    # Splunk returns 400 with code 6 (invalid data format) for a malformed
    # event — that's per-event, not run-wide, so we should retry (not abort
    # the whole file).
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(400, '{"text":"Invalid data format","code":6}')])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.failed_count == 1
    assert result.permanent_error is None
    assert len(fake_session.posts) == hec_uploader.MAX_RETRIES


def test_uploader_fails_fast_on_400_with_unparseable_body(tmp_path, monkeypatch):
    # HTTP 400 with a non-JSON body (e.g. proxy/firewall HTML page) — no
    # Splunk retryable code (5 or 6) is present, so treat as permanent.
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(400, "<html>gateway</html>")])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.failed_count == 1
    assert len(fake_session.posts) == 1
    assert result.permanent_error is not None
    assert "HTTP 400" in result.permanent_error


def test_uploader_permanent_error_stops_producer(tmp_path, monkeypatch):
    # 200 events at 1 per batch = 200 batches; without early-cancel the
    # producer would enqueue and workers would POST all of them.
    path = _write_jsonl(tmp_path, [{"n": i} for i in range(200)])
    fake_session = _FakeSession([(400, '{"text":"Incorrect index","code":7}')])
    _install_fake_session(monkeypatch, fake_session)
    monkeypatch.setattr(hec_uploader, "EVENTS_PER_BATCH", 1)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.permanent_error is not None
    # Bounded by in-flight worker concurrency rather than total batch count.
    assert len(fake_session.posts) <= hec_uploader.CONCURRENCY_LIMIT


def test_uploader_producer_exception_does_not_hang(tmp_path, monkeypatch):
    # If the producer raises (e.g. FileNotFoundError, decode error), the run
    # must re-raise cleanly rather than deadlocking on queue.join().
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(200, "")])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )

    async def _boom(self):
        raise RuntimeError("simulated producer failure")

    monkeypatch.setattr(HECUploader, "_enqueue_lines", _boom)

    async def _runner():
        return await asyncio.wait_for(uploader.run(), timeout=2.0)

    with pytest.raises(RuntimeError, match="simulated producer failure"):
        asyncio.run(_runner())


def test_uploader_skips_oversized_event(tmp_path, monkeypatch):
    # One small event + one oversized event in the same file. The oversized
    # one must be skipped (not POSTed) while the small one still uploads
    # successfully.
    oversized = {"blob": "x" * 200}  # >100 bytes once encoded as an envelope
    small = {"n": 1}
    path = _write_jsonl(tmp_path, [small, oversized])

    fake_session = _FakeSession([(200, "")])
    _install_fake_session(monkeypatch, fake_session)
    monkeypatch.setattr(hec_uploader, "MAX_BATCH_SIZE_BYTES", 100)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.skipped_count == 1
    assert result.success_count == 1
    assert result.failed_count == 0
    # Only one POST — the small event. The oversized event never hit the wire.
    assert len(fake_session.posts) == 1


def test_uploader_still_retries_on_429(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": 1}])
    fake_session = _FakeSession([(429, "slow down")])
    _install_fake_session(monkeypatch, fake_session)

    uploader = HECUploader(
        file_path=path,
        hec_url="https://hec.example.com",
        token="tok",
        index="idx",
        endpoint="event",
    )
    result = asyncio.run(uploader.run())

    assert result.failed_count == 1
    assert len(fake_session.posts) == hec_uploader.MAX_RETRIES
    assert result.permanent_error is None


def test_upload_requires_env_vars(monkeypatch):
    monkeypatch.delenv("SPLUNK_HEC_URL", raising=False)
    monkeypatch.delenv("SPLUNK_HEC_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="SPLUNK_HEC_URL"):
        tasks.upload.run(
            pipe_result=None,
            input_files=[{"path": "/tmp/x.jsonl", "display_name": "x.jsonl"}],
            output_path="/tmp",
            workflow_id="wf",
            task_config={"index": "idx"},
        )


def test_upload_requires_index(monkeypatch):
    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    with pytest.raises(ValueError, match="index"):
        tasks.upload.run(
            pipe_result=None,
            input_files=[{"path": "/tmp/x.jsonl", "display_name": "x.jsonl"}],
            output_path="/tmp",
            workflow_id="wf",
            task_config={},
        )


def test_upload_happy_path(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": i} for i in range(5)])

    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    stub_result = UploadResult(success_count=5, failed_count=0)

    class _StubUploader:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            return stub_result

    monkeypatch.setattr(tasks, "HECUploader", _StubUploader)

    encoded = tasks.upload.run(
        pipe_result=None,
        input_files=[{"path": path, "display_name": "events.jsonl"}],
        output_path=str(tmp_path),
        workflow_id="wf",
        task_config={"index": "idx"},
    )
    payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    assert payload["meta"]["success_events"] == 5
    assert payload["meta"]["failed_events"] == 0
    assert payload["meta"]["skipped_events"] == 0
    assert payload["output_files"] == []


def test_upload_reports_transient_failures_in_meta(tmp_path, monkeypatch):
    # A batch that exhausts retries (no permanent_error) should NOT fail the
    # Celery task — the counts just show up in the meta.
    path = _write_jsonl(tmp_path, [{"n": 1}])

    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    stub_result = UploadResult(
        success_count=4,
        failed_count=1,
        skipped_count=2,
        error_dict={"500_boom": 5},
    )

    class _StubUploader:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            return stub_result

    monkeypatch.setattr(tasks, "HECUploader", _StubUploader)

    encoded = tasks.upload.run(
        pipe_result=None,
        input_files=[{"path": path, "display_name": "events.jsonl"}],
        output_path=str(tmp_path),
        workflow_id="wf",
        task_config={"index": "idx"},
    )
    payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    assert payload["meta"]["success_events"] == 4
    assert payload["meta"]["failed_events"] == 1
    assert payload["meta"]["skipped_events"] == 2
    assert payload["meta"]["per_file"][0]["failed_events"] == 1
    assert payload["meta"]["per_file"][0]["skipped_events"] == 2
    assert payload["meta"]["per_file"][0]["error_codes"] == {"500_boom": 5}


def test_upload_slice_select_latest_filters_inputs(tmp_path, monkeypatch):
    """slice_select='latest' must drop all but the slice-K-of-N where K==N
    before any uploads happen."""
    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    files_uploaded: list[str] = []

    class _StubUploader:
        def __init__(self, *args, **kwargs):
            files_uploaded.append(kwargs["file_path"])

        async def run(self):
            return UploadResult(success_count=1, failed_count=0)

    monkeypatch.setattr(tasks, "HECUploader", _StubUploader)

    inputs = [
        {
            "path": str(tmp_path / f"foo.plaso.slice-{k}-of-4.jsonl"),
            "display_name": f"foo.plaso.slice-{k}-of-4.jsonl",
        }
        for k in range(1, 5)
    ]

    tasks.upload.run(
        pipe_result=None,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf",
        task_config={"index": "idx", "slice_select": "latest"},
    )

    assert len(files_uploaded) == 1
    assert files_uploaded[0].endswith("foo.plaso.slice-4-of-4.jsonl")


def test_upload_slice_select_all_uploads_every_input(tmp_path, monkeypatch):
    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    files_uploaded: list[str] = []

    class _StubUploader:
        def __init__(self, *args, **kwargs):
            files_uploaded.append(kwargs["file_path"])

        async def run(self):
            return UploadResult(success_count=1, failed_count=0)

    monkeypatch.setattr(tasks, "HECUploader", _StubUploader)

    inputs = [
        {
            "path": str(tmp_path / f"foo.plaso.slice-{k}-of-4.jsonl"),
            "display_name": f"foo.plaso.slice-{k}-of-4.jsonl",
        }
        for k in range(1, 5)
    ]

    tasks.upload.run(
        pipe_result=None,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf",
        task_config={"index": "idx"},  # slice_select unset → "all"
    )

    assert len(files_uploaded) == 4


def test_upload_slice_select_index_picks_specific_slice(tmp_path, monkeypatch):
    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    files_uploaded: list[str] = []

    class _StubUploader:
        def __init__(self, *args, **kwargs):
            files_uploaded.append(kwargs["file_path"])

        async def run(self):
            return UploadResult(success_count=1, failed_count=0)

    monkeypatch.setattr(tasks, "HECUploader", _StubUploader)

    inputs = [
        {
            "path": str(tmp_path / f"foo.plaso.slice-{k}-of-4.jsonl"),
            "display_name": f"foo.plaso.slice-{k}-of-4.jsonl",
        }
        for k in range(1, 5)
    ]

    tasks.upload.run(
        pipe_result=None,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf",
        task_config={"index": "idx", "slice_select": "2"},
    )

    assert len(files_uploaded) == 1
    assert files_uploaded[0].endswith("foo.plaso.slice-2-of-4.jsonl")


def test_upload_raises_with_permanent_error_message(tmp_path, monkeypatch):
    path = _write_jsonl(tmp_path, [{"n": 1}])

    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "tok")

    stub_result = UploadResult(
        success_count=0,
        failed_count=1,
        error_dict={"400_incorrect_index": 1},
        permanent_error="HTTP 400 (Splunk code 7): Incorrect index",
    )

    class _StubUploader:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            return stub_result

    monkeypatch.setattr(tasks, "HECUploader", _StubUploader)

    with pytest.raises(RuntimeError) as excinfo:
        tasks.upload.run(
            pipe_result=None,
            input_files=[{"path": path, "display_name": "events.jsonl"}],
            output_path=str(tmp_path),
            workflow_id="wf",
            task_config={"index": "missing_index"},
        )
    message = str(excinfo.value)
    assert "code 7" in message
    assert "Incorrect index" in message
    assert "missing_index" in message
