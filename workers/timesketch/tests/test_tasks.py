# Copyright 2024 Google LLC
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

"""Tests for Timesketch worker tasks."""

from unittest.mock import MagicMock, patch

with patch("redis.Redis.from_url"):
    from src.tasks import get_or_create_sketch, upload


class Sketch:
    """Minimal Timesketch sketch object for tests."""

    def __init__(self, name: str):
        self.name = name


def _mock_redis():
    redis_client = MagicMock()
    redis_client.lock.return_value = MagicMock()
    return redis_client


def test_get_or_create_sketch_creates_named_sketch_by_default():
    """Test sketch_name keeps the default behavior of creating a new sketch."""
    sketch = Sketch("Case-123")
    timesketch_api_client = MagicMock()
    timesketch_api_client.create_sketch.return_value = sketch
    redis_client = _mock_redis()

    result = get_or_create_sketch(
        timesketch_api_client,
        redis_client,
        sketch_name="Case-123",
    )

    assert result == sketch
    timesketch_api_client.create_sketch.assert_called_once_with("Case-123")
    timesketch_api_client.list_sketches.assert_not_called()
    redis_client.lock.assert_not_called()


def test_get_or_create_sketch_reuses_existing_named_sketch_when_enabled():
    """Test opt-in name reuse returns an existing Timesketch sketch."""
    sketch = Sketch("Case-123")
    timesketch_api_client = MagicMock()
    timesketch_api_client.list_sketches.return_value = [sketch]
    redis_client = _mock_redis()

    result = get_or_create_sketch(
        timesketch_api_client,
        redis_client,
        sketch_name="Case-123",
        reuse_existing_sketch=True,
    )

    assert result == sketch
    redis_client.lock.assert_called_once_with(
        "timesketch-sketch-name:Case-123",
        timeout=60,
        blocking_timeout=5,
    )
    timesketch_api_client.create_sketch.assert_not_called()


def test_get_or_create_sketch_creates_named_sketch_when_reuse_finds_none():
    """Test opt-in name reuse creates the sketch when no match exists."""
    sketch = Sketch("Case-123")
    timesketch_api_client = MagicMock()
    timesketch_api_client.list_sketches.return_value = []
    timesketch_api_client.create_sketch.return_value = sketch
    redis_client = _mock_redis()

    result = get_or_create_sketch(
        timesketch_api_client,
        redis_client,
        sketch_name="Case-123",
        reuse_existing_sketch=True,
    )

    assert result == sketch
    redis_client.lock.assert_called_once_with(
        "timesketch-sketch-name:Case-123",
        timeout=60,
        blocking_timeout=5,
    )
    timesketch_api_client.create_sketch.assert_called_once_with("Case-123")


def test_get_or_create_sketch_uses_id_before_name_reuse():
    """Test sketch_id remains the explicit lookup when multiple options are set."""
    sketch = Sketch("Case-123")
    timesketch_api_client = MagicMock()
    timesketch_api_client.get_sketch.return_value = sketch
    redis_client = _mock_redis()

    result = get_or_create_sketch(
        timesketch_api_client,
        redis_client,
        sketch_id="123",
        sketch_name="Case-123",
        reuse_existing_sketch=True,
    )

    assert result == sketch
    timesketch_api_client.get_sketch.assert_called_once_with(123)
    timesketch_api_client.list_sketches.assert_not_called()
    timesketch_api_client.create_sketch.assert_not_called()
    redis_client.lock.assert_not_called()


def test_upload_passes_reuse_existing_sketch_config():
    """Test upload parses and passes the name reuse checkbox config."""
    sketch = MagicMock()
    sketch.id = 123

    timeline = MagicMock()
    timeline.id = 456
    timeline.name = "Host-A"

    streamer = MagicMock()
    streamer.timeline = timeline
    streamer_context = MagicMock()
    streamer_context.__enter__.return_value = streamer

    with (
        patch.dict(
            "os.environ",
            {
                "TIMESKETCH_SERVER_URL": "http://timesketch-web:5000",
                "TIMESKETCH_SERVER_PUBLIC_URL": "http://127.0.0.1:5000",
                "TIMESKETCH_USERNAME": "admin",
                "TIMESKETCH_PASSWORD": "password",
            },
        ),
        patch(
            "src.tasks.get_input_files",
            return_value=[{"path": "/tmp/host-a.plaso", "display_name": "host-a.plaso"}],
        ),
        patch("src.tasks.timesketch_client.TimesketchApi"),
        patch("src.tasks.get_or_create_sketch", return_value=sketch) as get_sketch,
        patch("src.tasks.importer.ImportStreamer", return_value=streamer_context),
        patch("src.tasks.create_task_result", return_value="task-result"),
        patch.object(upload, "send_event"),
    ):
        result = upload.run(
            input_files=[],
            workflow_id="workflow-1",
            task_config={
                "sketch_name": "Case-123",
                "reuse_existing_sketch": "true",
                "timeline_name": "Host-A",
            },
        )

    assert result == "task-result"
    assert get_sketch.call_args.kwargs["reuse_existing_sketch"] is True
