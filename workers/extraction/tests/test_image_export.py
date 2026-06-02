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

import json
import pytest
from unittest.mock import MagicMock, patch

from src.image_export import get_artifact_types, extract_task


def test_get_artifact_types_file_not_found(tmp_path):
    """Test get_artifact_types when artifacts_map.json does not exist."""
    original_path = "some/file.txt"
    types = get_artifact_types(tmp_path, original_path)
    assert types == []


def test_get_artifact_types_invalid_json(tmp_path):
    """Test get_artifact_types when artifacts_map.json is invalid JSON."""
    map_file = tmp_path / "artifacts_map.json"
    map_file.write_text("invalid json content")
    types = get_artifact_types(tmp_path, "some/file.txt")
    assert types == []


def test_get_artifact_types_io_error(tmp_path):
    """Test get_artifact_types when there is an IOError reading the file."""
    with patch("builtins.open", side_effect=IOError("Mocked IOError")):
        map_file = tmp_path / "artifacts_map.json"
        map_file.touch()
        types = get_artifact_types(tmp_path, "some/file.txt")
        assert types == []


def test_get_artifact_types_empty_json(tmp_path):
    """Test get_artifact_types when artifacts_map.json is empty."""
    map_file = tmp_path / "artifacts_map.json"
    map_file.write_text("{}")
    types = get_artifact_types(tmp_path, "some/file.txt")
    assert types == []


def test_get_artifact_types_found(tmp_path):
    """Test get_artifact_types when the file is in the map."""
    map_file = tmp_path / "artifacts_map.json"
    data = {
        "ArtifactA": ["path/to/file.txt"],
        "ArtifactB": ["other/file.txt", "path/to/file.txt"],
    }
    map_file.write_text(json.dumps(data))

    types = get_artifact_types(tmp_path, "path/to/file.txt")
    assert len(types) == 2
    assert "extraction:image_export:artifact:ArtifactA" in types
    assert "extraction:image_export:artifact:ArtifactB" in types


def test_get_artifact_types_not_found_in_valid_map(tmp_path):
    """Test get_artifact_types when the file is not in the map."""
    map_file = tmp_path / "artifacts_map.json"
    data = {"ArtifactA": ["other/file.txt"]}
    map_file.write_text(json.dumps(data))

    types = get_artifact_types(tmp_path, "path/to/file.txt")
    assert types == []


@pytest.fixture
def mock_dependencies():
    """Mocks dependencies for extract_task."""
    with (
        patch("src.image_export.get_input_files") as mock_get_input_files,
        patch("src.image_export.create_output_file") as mock_create_output_file,
        patch("src.image_export.create_task_result") as mock_create_task_result,
        patch("src.image_export.subprocess.Popen") as mock_popen,
        patch("src.image_export.shutil.rmtree") as mock_rmtree,
        patch("src.image_export.shutil.copy") as mock_copy,
        patch("src.image_export.os.mkdir") as mock_mkdir,
        patch("src.image_export.Path.glob") as mock_glob,
        patch("src.image_export.get_artifact_types") as mock_get_artifact_types,
    ):
        yield {
            "get_input_files": mock_get_input_files,
            "create_output_file": mock_create_output_file,
            "create_task_result": mock_create_task_result,
            "popen": mock_popen,
            "rmtree": mock_rmtree,
            "copy": mock_copy,
            "mkdir": mock_mkdir,
            "glob": mock_glob,
            "get_artifact_types": mock_get_artifact_types,
        }


@pytest.fixture
def mock_celery_task():
    """Mock the Celery task instance (self)."""
    task = MagicMock()
    task.send_event = MagicMock()
    return task


@patch("src.image_export.telemetry")
def test_extract_task_no_filters(mock_telemetry, mock_celery_task, mock_dependencies):
    """Test extract_task raises RuntimeError when no filters are provided."""
    mock_dependencies["get_input_files"].return_value = [{"path": "test.dd", "id": "1"}]

    task_config = {}

    with pytest.raises(RuntimeError, match="No filters were set"):
        # Use .__class__.run() to call the underlying function, passing mock self
        extract_task.__class__.run(
            mock_celery_task,
            pipe_result=None,
            input_files=None,
            output_path=None,
            workflow_id=None,
            task_config=task_config,
        )


@patch("src.image_export.telemetry")
def test_extract_task_artifact_filter(
    mock_telemetry, mock_celery_task, mock_dependencies
):
    """Test extract_task with artifact filters."""
    mock_dependencies["get_input_files"].return_value = [{"path": "test.dd", "id": "1"}]
    mock_dependencies["create_task_result"].return_value = "task_result"

    # Mock subprocess to finish immediately
    mock_process = MagicMock()
    mock_process.poll.side_effect = [
        None,
        0,
    ]  # Returns None once (running), then 0 (done)
    mock_process.stdout.read.return_value = "Process output"
    mock_process.stderr.read.return_value = ""
    mock_dependencies["popen"].return_value = mock_process

    # Mock file extraction
    mock_file = MagicMock()
    mock_file.is_file.return_value = True
    mock_file.name = "extracted_file.txt"
    mock_file.absolute.return_value.name = "extracted_file.txt"
    mock_file.relative_to.return_value = "relative/extracted_file.txt"

    mock_dependencies["glob"].return_value = [mock_file]

    mock_dependencies["get_artifact_types"].return_value = [
        "extraction:image_export:artifact:TestArtifact"
    ]

    task_config = {"artifacts": ["BrowserHistory"]}

    result = extract_task.__class__.run(
        mock_celery_task,
        task_config=task_config,
        output_path="/tmp/output",
        workflow_id="workflow-123",
    )

    assert result == "task_result"

    # Verify command
    mock_dependencies["popen"].assert_called()
    call_args = mock_dependencies["popen"].call_args[0][0]
    assert "image_export.py" in call_args
    assert "--artifact_filters" in call_args
    assert "BrowserHistory" in call_args
    assert "test.dd" in call_args


@patch("src.image_export.telemetry")
def test_extract_task_file_filters(mock_telemetry, mock_celery_task, mock_dependencies):
    """Test extract_task with filename and extension filters."""
    mock_dependencies["get_input_files"].return_value = [{"path": "test.dd", "id": "1"}]
    mock_dependencies["create_task_result"].return_value = "task_result"

    mock_process = MagicMock()
    mock_process.poll.return_value = 0
    mock_process.stdout.read.return_value = "Process output"
    mock_process.stderr.read.return_value = ""
    mock_dependencies["popen"].return_value = mock_process

    mock_dependencies["glob"].return_value = []  # No files extracted

    task_config = {
        "filenames": "evil.exe",
        "file_extensions": "exe,dll",
        "file_signatures": ["exe_mz"],
    }

    extract_task.__class__.run(
        mock_celery_task,
        task_config=task_config,
        output_path="/tmp/output",
        workflow_id="workflow-123",
    )

    # Verify command
    mock_dependencies["popen"].assert_called()
    call_args = mock_dependencies["popen"].call_args[0][0]
    assert "--names" in call_args
    assert "evil.exe" in call_args
    assert "--extensions" in call_args
    assert "exe,dll" in call_args
    assert "--signatures" in call_args
    assert "exe_mz" in call_args


@patch("src.image_export.telemetry")
def test_extract_task_combined_filters(
    mock_telemetry, mock_celery_task, mock_dependencies
):
    """Test extract_task runs separate commands for artifact and file filters."""
    mock_dependencies["get_input_files"].return_value = [{"path": "test.dd", "id": "1"}]
    mock_dependencies["create_task_result"].return_value = "task_result"

    mock_process = MagicMock()
    mock_process.poll.return_value = 0
    mock_process.stdout.read.return_value = ""
    mock_process.stderr.read.return_value = ""
    mock_dependencies["popen"].return_value = mock_process
    mock_dependencies["glob"].return_value = []

    task_config = {"artifacts": ["BrowserHistory"], "filenames": "evil.exe"}

    extract_task.__class__.run(
        mock_celery_task,
        task_config=task_config,
        output_path="/tmp/output",
        workflow_id="workflow-123",
    )

    # Should be called twice
    assert mock_dependencies["popen"].call_count == 2

    # Inspect calls...
    calls = mock_dependencies["popen"].call_args_list
    args1 = calls[0][0][0]
    args2 = calls[1][0][0]

    def cmd_list_to_str(cmd_list):
        return " ".join(str(x) for x in cmd_list)

    cmd1 = cmd_list_to_str(args1)
    cmd2 = cmd_list_to_str(args2)

    assert ("--artifact_filters" in cmd1 and "--names" in cmd2) or (
        "--artifact_filters" in cmd2 and "--names" in cmd1
    )


@patch("src.image_export.telemetry")
def test_extract_task_output_processing(
    mock_telemetry, mock_celery_task, mock_dependencies
):
    """Test output file processing and linking."""
    mock_dependencies["get_input_files"].return_value = [{"path": "test.dd", "id": "1"}]
    mock_dependencies["create_task_result"].return_value = "task_result"

    mock_process = MagicMock()
    mock_process.poll.return_value = 0
    mock_process.stdout.read.return_value = ""
    mock_process.stderr.read.return_value = ""
    mock_dependencies["popen"].return_value = mock_process

    # Mock extracted file
    mock_file = MagicMock()
    mock_file.is_file.return_value = True
    mock_file.name = "extracted.txt"
    mock_file.absolute.return_value.name = "extracted.txt"
    mock_file.relative_to.return_value = "relative/extracted.txt"

    # Mock artifacts map file which should be ignored
    mock_map_file = MagicMock()
    mock_map_file.is_file.return_value = True
    mock_map_file.absolute.return_value.name = "artifacts_map.json"

    # glob returns both
    mock_dependencies["glob"].return_value = [mock_file, mock_map_file]

    # Mock fallback to generic type
    mock_dependencies["get_artifact_types"].return_value = []

    # create_output_file should return an object that has .to_dict() and .path
    mock_out_file = MagicMock()
    mock_out_file.path = "/tmp/output/extracted.txt"
    mock_out_file.to_dict.return_value = {"path": "/tmp/output/extracted.txt"}
    mock_dependencies["create_output_file"].return_value = mock_out_file

    task_config = {"artifacts": ["Something"]}

    extract_task.__class__.run(
        mock_celery_task,
        task_config=task_config,
        output_path="/tmp/output",
        workflow_id="workflow-123",
    )

    # Verify create_output_file called with fallback type
    mock_dependencies["create_output_file"].assert_called()
    assert mock_dependencies["create_output_file"].call_count == 1

    _, kwargs = mock_dependencies["create_output_file"].call_args
    assert kwargs["data_type"] == "extraction:image_export:file"
    assert kwargs["display_name"] == "extracted.txt"
    assert kwargs["source_file_id"] == "1"


@patch("src.image_export.telemetry")
def test_extract_task_output_processing_with_artifact_types(
    mock_telemetry, mock_celery_task, mock_dependencies
):
    """Test output file processing with identified artifact types."""
    mock_dependencies["get_input_files"].return_value = [{"path": "test.dd", "id": "1"}]
    mock_dependencies["create_task_result"].return_value = "task_result"

    mock_process = MagicMock()
    mock_process.poll.return_value = 0
    mock_process.stdout.read.return_value = ""
    mock_process.stderr.read.return_value = ""
    mock_dependencies["popen"].return_value = mock_process

    mock_file = MagicMock()
    mock_file.is_file.return_value = True
    mock_file.name = "extracted.txt"
    mock_file.absolute.return_value.name = "extracted.txt"
    mock_file.relative_to.return_value = "relative/extracted.txt"

    mock_dependencies["glob"].return_value = [mock_file]

    mock_dependencies["get_artifact_types"].return_value = [
        "extraction:image_export:artifact:TypeA",
        "extraction:image_export:artifact:TypeB",
    ]

    mock_out_file = MagicMock()
    mock_out_file.path = "/tmp/output/extracted.txt"
    mock_out_file.to_dict.return_value = {"path": "/tmp/output/extracted.txt"}
    mock_dependencies["create_output_file"].return_value = mock_out_file

    task_config = {"artifacts": ["Something"]}

    extract_task.__class__.run(
        mock_celery_task,
        task_config=task_config,
        output_path="/tmp/output",
        workflow_id="workflow-123",
    )

    assert mock_dependencies["create_output_file"].call_count == 2
