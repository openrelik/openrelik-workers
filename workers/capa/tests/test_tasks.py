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

"""Tests tasks"""

import pytest
from unittest.mock import MagicMock, patch

from src import tasks


@pytest.fixture
def mock_celery_task():
    """Mock the Celery task instance (self)."""
    task = MagicMock()
    task.send_event = MagicMock()
    return task


@patch("src.tasks.get_input_files")
@patch("src.tasks.create_output_file")
@patch("src.tasks.create_task_result")
@patch("src.tasks.subprocess.Popen")
@patch("builtins.open")
def test_capa_task(
    mock_open,
    mock_popen,
    mock_create_task_result,
    mock_create_output_file,
    mock_get_input_files,
    mock_celery_task,
):
    """Test the capa task."""
    # Setup mocks
    mock_get_input_files.return_value = [
        {"display_name": "test_file.exe", "path": "/path/to/test_file.exe"}
    ]

    # Mock create_output_file to return a mock object with a .path attribute and .to_dict() method
    mock_output_file = MagicMock()
    mock_output_file.path = "/path/to/output.json"
    mock_output_file.to_dict.return_value = {"path": "/path/to/output.json"}
    mock_create_output_file.return_value = mock_output_file

    # Mock subprocess.Popen
    mock_process = MagicMock()
    mock_process.wait.return_value = None
    mock_popen.return_value = mock_process

    # Call the task
    tasks.capa.__class__.run(
        mock_celery_task,
        pipe_result="dummy_pipe_result",
        input_files=[
            {"display_name": "test_file.exe", "path": "/path/to/test_file.exe"}
        ],
        output_path="/tmp",
        workflow_id="workflow_123",
        task_config={},
    )

    # Verify assertions
    mock_get_input_files.assert_called_once()
    assert mock_create_output_file.call_count == 3  # json, summary, detailed
    assert mock_popen.call_count == 3
    mock_create_task_result.assert_called_once()
    mock_celery_task.send_event.assert_called()


@patch("src.tasks.get_input_files")
@patch("src.tasks.create_output_file")
@patch("src.tasks.create_task_result")
@patch("src.tasks.subprocess.Popen")
@patch("builtins.open")
def test_capa_task_no_files(
    mock_open,
    mock_popen,
    mock_create_task_result,
    mock_create_output_file,
    mock_get_input_files,
    mock_celery_task,
):
    """Test the capa task with no input files."""
    mock_get_input_files.return_value = []

    tasks.capa.__class__.run(
        mock_celery_task,
        pipe_result=None,
        input_files=[],
        output_path="/tmp",
        workflow_id="workflow_123",
        task_config={},
    )

    mock_popen.assert_not_called()
    mock_create_output_file.assert_not_called()
    mock_create_task_result.assert_called_once()
