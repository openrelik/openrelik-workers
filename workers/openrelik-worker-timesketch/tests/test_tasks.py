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

import pytest
from unittest.mock import MagicMock, patch

# Patch src.app before importing tasks to avoid redis connection
with patch("redis.Redis.from_url") as mock_redis_from_url:
    with patch("celery.Celery") as mock_celery_init:
        from src.tasks import get_or_create_sketch, upload, _upload

import os
import requests


class TestGetOrCreateSketch:
    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_by_id_success(self, mock_redis):
        """Tests retrieving an existing sketch by its ID."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_timesketch_client.get_sketch.return_value = mock_sketch

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis, sketch_id=123
        )

        mock_timesketch_client.get_sketch.assert_called_once_with(123)
        assert sketch == mock_sketch

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_by_id_not_found(self, mock_redis):
        """Tests handling the case where a sketch ID is not found."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.get_sketch.return_value = None

        with pytest.raises(ValueError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis, sketch_id=123
            )

        assert "Sketch with ID '123' not found." in str(excinfo.value)

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_by_id_api_error(self, mock_redis):
        """Tests handling an API error when retrieving by ID."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.get_sketch.side_effect = RuntimeError("API Error")

        with pytest.raises(RuntimeError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis, sketch_id=123
            )

        assert "Failed to retrieve sketch with ID '123': API Error" in str(excinfo.value)

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_by_name_success(self, mock_redis):
        """Tests creating a new sketch by a given name."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_timesketch_client.create_sketch.return_value = mock_sketch

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis, sketch_name="Test Sketch"
        )

        mock_timesketch_client.create_sketch.assert_called_once_with("Test Sketch")
        assert sketch == mock_sketch

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_by_name_failure(self, mock_redis):
        """Tests handling the failure of sketch creation by name."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.create_sketch.return_value = None

        with pytest.raises(RuntimeError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis, sketch_name="Test Sketch"
            )

        assert "Failed to create sketch with name 'Test Sketch'" in str(excinfo.value)

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_default_name_existing(self, mock_redis):
        """Tests retrieving an existing sketch using the default naming convention."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_sketch.name = "openrelik-workflow-123"
        mock_timesketch_client.list_sketches.return_value = [mock_sketch]
        
        # Mocking the context manager for the lock
        mock_lock = MagicMock()
        mock_redis.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = MagicMock()

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis, workflow_id="123"
        )

        assert sketch == mock_sketch
        mock_redis.lock.assert_called_once_with(
            "openrelik-workflow-123", timeout=60, blocking_timeout=5
        )

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_default_name_new(self, mock_redis):
        """Tests creating a new sketch using the default naming convention."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_sketch.name = "openrelik-workflow-123"
        mock_timesketch_client.list_sketches.return_value = []
        mock_timesketch_client.create_sketch.return_value = mock_sketch
        
        mock_lock = MagicMock()
        mock_redis.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = MagicMock()

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis, workflow_id="123"
        )
        assert sketch == mock_sketch

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_default_name_create_failure(self, mock_redis):
        """Tests handling the failure of default sketch creation."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.list_sketches.return_value = []
        mock_timesketch_client.create_sketch.return_value = None
        
        mock_lock = MagicMock()
        mock_redis.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = MagicMock()

        with pytest.raises(RuntimeError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis, workflow_id="123"
            )
        assert "after acquiring lock" in str(excinfo.value)

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_default_name_list_error(self, mock_redis):
        """Tests handling an error when listing sketches for default name."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.list_sketches.side_effect = RuntimeError("List Error")
        
        mock_lock = MagicMock()
        mock_redis.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = MagicMock()

        with pytest.raises(RuntimeError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis, workflow_id="123"
            )
        assert "Failed to retrieve or create default sketch" in str(excinfo.value)

    @patch("src.tasks.redis_client")
    def test_get_or_create_sketch_missing_workflow_id(self, mock_redis):
        """Tests that ValueError is raised if no identification is provided and workflow_id is missing."""
        mock_timesketch_client = MagicMock()

        with pytest.raises(ValueError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis
            )

        assert "workflow_id is required" in str(excinfo.value)


class TestUpload:
    @patch.dict(os.environ, {
        "TIMESKETCH_SERVER_URL": "http://localhost",
        "TIMESKETCH_SERVER_PUBLIC_URL": "http://public",
        "TIMESKETCH_USERNAME": "user",
        "TIMESKETCH_PASSWORD": "pass",
    })
    @patch("src.tasks.timesketch_client.TimesketchApi", autospec=True)
    @patch("src.tasks.get_input_files")
    @patch("src.tasks.importer.ImportStreamer", autospec=True)
    @patch("src.tasks.create_task_result")
    @patch("src.tasks.redis_client")
    def test_upload_success(
        self,
        mock_redis,
        mock_create_task_result,
        mock_import_streamer_class,
        mock_get_input_files,
        mock_timesketch_api_class,
    ):
        """Tests a successful upload task using the real get_or_create_sketch logic."""
        # Setup input files
        mock_get_input_files.return_value = [{"path": "/tmp/file", "display_name": "file"}]
        
        # Setup Timesketch client and sketch
        mock_ts_client = mock_timesketch_api_class.return_value
        mock_sketch = MagicMock()
        mock_sketch.id = 1
        mock_ts_client.get_sketch.return_value = mock_sketch
        
        # Setup mock for context manager importer.ImportStreamer()
        mock_streamer_instance = mock_import_streamer_class.return_value.__enter__.return_value

        # Call the helper function directly
        # By not mocking get_or_create_sketch, we test its integration
        _upload(
            pipe_result=None,
            input_files=[],
            output_path="/tmp",
            workflow_id="123",
            task_config={"sketch_id": "1", "make_sketch_public": True},
        )

        # Verify get_sketch was called (part of get_or_create_sketch logic)
        mock_ts_client.get_sketch.assert_called_once_with(1)
        mock_sketch.add_to_acl.assert_called_once_with(make_public=True)
        mock_streamer_instance.add_file.assert_called_once_with("/tmp/file")
        mock_create_task_result.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    def test_upload_missing_env(self):
        """Tests upload failure when environment variables are missing."""
        with pytest.raises(AssertionError):
            _upload(task_config={})

    @patch.dict(os.environ, {
        "TIMESKETCH_SERVER_URL": "http://localhost",
        "TIMESKETCH_SERVER_PUBLIC_URL": "http://public",
        "TIMESKETCH_USERNAME": "user",
        "TIMESKETCH_PASSWORD": "pass",
    })
    @patch("src.tasks.timesketch_client.TimesketchApi", autospec=True)
    @patch("src.tasks.get_input_files")
    def test_upload_acl_error(
        self,
        mock_get_input_files,
        mock_timesketch_api_class,
    ):
        """Tests upload failure when ACL update fails."""
        mock_get_input_files.return_value = []
        mock_ts_client = mock_timesketch_api_class.return_value
        mock_sketch = MagicMock()
        mock_sketch.id = 1
        mock_sketch.name = "test"
        mock_sketch.add_to_acl.side_effect = RuntimeError("ACL Error")
        mock_ts_client.get_sketch.return_value = mock_sketch

        with pytest.raises(RuntimeError) as excinfo:
            _upload(
                task_config={"sketch_id": "1", "make_sketch_public": True},
            )
        assert "Failed to make sketch 1 ('test') public" in str(excinfo.value)

