# Copyright 2025 Google LLC
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
"""Tests tasks."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from src.tasks import command


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.run")
@patch("src.tasks.create_output_file")
@patch("src.tasks.create_task_result")
def test_command_with_actual_file_input(
    mock_create_task_result,
    mock_create_output_file,
    mock_subprocess_run,
    mock_get_input_files,
    tmp_path,
):
    """
    Test the command task with an actual input file from test_data,
    mocking the ssdeep execution and verifying the consolidated outputs.
    """
    project_root = Path(__file__).parent.parent
    actual_input_file_path = project_root / "test_data" / "test.txt"
    assert actual_input_file_path.exists()

    workflow_id = "test-workflow"
    output_path_val = str(tmp_path)

    mock_input_file_dict = {
        "path": str(actual_input_file_path),
        "display_name": "test.txt",
    }
    mock_get_input_files.return_value = [mock_input_file_dict]

    # Mock subprocess.run
    mock_ssdeep_process = MagicMock()
    mock_ssdeep_process.returncode = 0
    expected_hash = "3:mockedHash"
    mock_ssdeep_process.stdout = f'{expected_hash},"{actual_input_file_path.name}"'
    mock_subprocess_run.return_value = mock_ssdeep_process

    # Mock create_output_file for JSON and MD
    mock_json_file = MagicMock()
    mock_json_file.path = str(tmp_path / "ssdeep_results.json")
    mock_json_file.to_dict.return_value = {"display_name": "ssdeep_results.json"}

    mock_md_file = MagicMock()
    mock_md_file.path = str(tmp_path / "ssdeep_results.md")
    mock_md_file.to_dict.return_value = {"display_name": "ssdeep_results.md"}

    mock_create_output_file.side_effect = [mock_json_file, mock_md_file]
    mock_create_task_result.return_value = "mocked_result"

    # Mock send_event on the task instance
    command.send_event = MagicMock()

    # --- Call the task ---
    result = command.run(
        pipe_result=None,
        input_files=[mock_input_file_dict],
        output_path=output_path_val,
        workflow_id=workflow_id,
        task_config=None,
    )

    # --- Assertions ---
    mock_subprocess_run.assert_called_once_with(
        ["/usr/bin/ssdeep", "-s", "-b", str(actual_input_file_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    # Check progress event
    command.send_event.assert_called_with(
        "task-progress",
        data={"status": "Processing file 1 of 1 with ssdeep..."}
    )

    # Check output file creation calls
    mock_create_output_file.assert_has_calls([
        call(output_path_val, display_name="ssdeep_results", extension="json", data_type="application/json"),
        call(output_path_val, display_name="ssdeep_results", extension="md", data_type="text/markdown"),
    ])

    # Verify JSON content
    with open(mock_json_file.path, "r") as f:
        json_data = json.load(f)
        assert json_data == [{"filename": "test.txt", "ssdeep": expected_hash}]

    # Verify MD content
    with open(mock_md_file.path, "r") as f:
        md_data = f.read()
        assert "| test.txt | 3:mockedHash |" in md_data

    assert result == "mocked_result"


@patch("src.tasks.get_input_files")
@patch("src.tasks.create_task_result")
def test_command_no_input_files(mock_create_task_result, mock_get_input_files):
    """Test the command task when no input files are provided."""
    mock_get_input_files.return_value = []
    mock_create_task_result.return_value = "no_files_result"

    result = command.run(input_files=[])

    assert result == "no_files_result"
    mock_create_task_result.assert_called_once()
    args, kwargs = mock_create_task_result.call_args
    assert kwargs["meta"]["message"] == "No input files provided to calculate SSDeep hash."


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.run")
@patch("src.tasks.create_output_file")
@patch("src.tasks.create_task_result")
def test_command_with_error_and_notice(
    mock_create_task_result,
    mock_create_output_file,
    mock_subprocess_run,
    mock_get_input_files,
    tmp_path,
):
    """Test the command task with one failing file and one notice file."""
    mock_input_files = [
        {"path": "/path/to/error.txt", "display_name": "error.txt"},
        {"path": "/path/to/small.txt", "display_name": "small.txt"},
    ]
    mock_get_input_files.return_value = mock_input_files

    # Mock subprocess.run side effects
    mock_error_process = MagicMock()
    mock_error_process.returncode = 1
    mock_error_process.stderr = "Permission denied"
    mock_error_process.stdout = ""

    mock_notice_process = MagicMock()
    mock_notice_process.returncode = 0
    mock_notice_process.stdout = "File too small"

    mock_subprocess_run.side_effect = [mock_error_process, mock_notice_process]

    # Mock output files
    mock_json_file = MagicMock()
    mock_json_file.path = str(tmp_path / "results.json")
    mock_json_file.to_dict.return_value = {"display_name": "results.json"}
    mock_md_file = MagicMock()
    mock_md_file.path = str(tmp_path / "results.md")
    mock_md_file.to_dict.return_value = {"display_name": "results.md"}
    mock_create_output_file.side_effect = [mock_json_file, mock_md_file]

    command.send_event = MagicMock()

    command.run(
        input_files=mock_input_files,
        output_path=str(tmp_path)
    )

    # Verify JSON content for error and notice
    with open(mock_json_file.path, "r") as f:
        json_data = json.load(f)
        assert json_data[0]["ssdeep"].startswith("Error running ssdeep")
        assert "Permission denied" in json_data[0]["ssdeep"]
        assert json_data[1]["ssdeep"] == "SSDeep notice: File too small"


@patch("src.tasks.get_input_files")
@patch("src.tasks.create_task_result")
def test_command_missing_file_path(mock_create_task_result, mock_get_input_files):
    """Test the command task with a file entry that has no path."""
    mock_input_files = [{"display_name": "missing_path.txt"}]  # No 'path' key
    mock_get_input_files.return_value = mock_input_files
    mock_create_task_result.return_value = "no_output_result"

    command.send_event = MagicMock()

    result = command.run(input_files=mock_input_files)

    assert result == "no_output_result"
    # Verify no output files were generated (results list remained empty)
    mock_create_task_result.assert_called_once()
    args, kwargs = mock_create_task_result.call_args
    assert kwargs["output_files"] == []
