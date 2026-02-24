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

# Mock redis_client before importing tasks
import sys
mock_redis_client_global = MagicMock()
sys.modules["src.app"] = MagicMock(redis_client=mock_redis_client_global, celery=MagicMock())

from src.tasks import get_or_create_sketch


class TestGetOrCreateSketch:
    def test_get_or_create_sketch_by_id_success(self):
        """Tests retrieving an existing sketch by its ID."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_timesketch_client.get_sketch.return_value = mock_sketch

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis_client_global, sketch_id=123
        )

        mock_timesketch_client.get_sketch.assert_called_once_with(123)
        assert sketch == mock_sketch

    def test_get_or_create_sketch_by_id_not_found(self):
        """Tests handling the case where a sketch ID is not found."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.get_sketch.return_value = None

        with pytest.raises(ValueError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis_client_global, sketch_id=123
            )

        assert "Sketch with ID '123' not found." in str(excinfo.value)

    def test_get_or_create_sketch_by_id_api_error(self):
        """Tests handling an API error when retrieving by ID."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.get_sketch.side_effect = RuntimeError("API Error")

        with pytest.raises(RuntimeError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis_client_global, sketch_id=123
            )

        assert "Failed to retrieve sketch with ID '123': API Error" in str(excinfo.value)

    def test_get_or_create_sketch_by_name_success(self):
        """Tests creating a new sketch by a given name."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_timesketch_client.create_sketch.return_value = mock_sketch

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis_client_global, sketch_name="Test Sketch"
        )

        mock_timesketch_client.create_sketch.assert_called_once_with("Test Sketch")
        assert sketch == mock_sketch

    def test_get_or_create_sketch_by_name_failure(self):
        """Tests handling the failure of sketch creation by name."""
        mock_timesketch_client = MagicMock()
        mock_timesketch_client.create_sketch.return_value = None

        with pytest.raises(RuntimeError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis_client_global, sketch_name="Test Sketch"
            )

        assert "Failed to create sketch with name 'Test Sketch'" in str(excinfo.value)

    def test_get_or_create_sketch_default_name_existing(self):
        """Tests retrieving an existing sketch using the default naming convention."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_sketch.name = "openrelik-workflow-123"
        mock_timesketch_client.list_sketches.return_value = [mock_sketch]
        
        # Mocking the context manager for the lock
        mock_lock = MagicMock()
        mock_redis_client_global.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = MagicMock()

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis_client_global, workflow_id="123"
        )

        assert sketch == mock_sketch
        mock_redis_client_global.lock.assert_called_once_with(
            "openrelik-workflow-123", timeout=60, blocking_timeout=5
        )

    def test_get_or_create_sketch_default_name_new(self):
        """Tests creating a new sketch using the default naming convention."""
        mock_timesketch_client = MagicMock()
        mock_sketch = MagicMock()
        mock_sketch.name = "openrelik-workflow-123"
        mock_timesketch_client.list_sketches.return_value = []
        mock_timesketch_client.create_sketch.return_value = mock_sketch
        
        mock_lock = MagicMock()
        mock_redis_client_global.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = MagicMock()

        sketch = get_or_create_sketch(
            mock_timesketch_client, mock_redis_client_global, workflow_id="123"
        )
        assert sketch == mock_sketch

    def test_get_or_create_sketch_missing_workflow_id(self):
        """Tests that ValueError is raised if no identification is provided and workflow_id is missing."""
        mock_timesketch_client = MagicMock()

        with pytest.raises(ValueError) as excinfo:
            get_or_create_sketch(
                mock_timesketch_client, mock_redis_client_global
            )

        assert "workflow_id is required" in str(excinfo.value)
