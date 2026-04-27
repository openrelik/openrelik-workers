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
from unittest.mock import MagicMock, Mock, patch

from src import archives


@pytest.fixture
def mock_dependencies():
    """Mocks dependencies for extract_archive_task."""
    with (
        patch("src.archives.get_input_files") as mock_get_input_files,
        patch("src.archives.create_output_file") as mock_create_output_file,
        patch("src.archives.extract_archive") as mock_extract_archive,
        patch("src.archives.create_task_result") as mock_create_task_result,
        patch("src.archives.shutil.rmtree") as mock_rmtree,
        patch("src.archives.os.rename") as mock_rename,
        patch("src.archives.Path") as mock_path,
        patch("src.archives.telemetry") as mock_telemetry,
    ):
        yield {
            "get_input_files": mock_get_input_files,
            "create_output_file": mock_create_output_file,
            "extract_archive": mock_extract_archive,
            "create_task_result": mock_create_task_result,
            "rmtree": mock_rmtree,
            "rename": mock_rename,
            "path": mock_path,
            "telemetry": mock_telemetry,
        }


@pytest.fixture
def mock_celery_task():
    """Mock the Celery task instance (self)."""
    task = MagicMock()
    task.send_event = MagicMock()
    return task


def test_extract_archive_task_success(mock_celery_task, mock_dependencies):
    """Test successful execution of extract_archive_task."""
    # Setup mocks
    mock_dependencies["get_input_files"].return_value = [
        {"id": "file1", "display_name": "archive.zip", "path": "/path/to/archive.zip"}
    ]

    mock_log_file = Mock()
    mock_log_file.path = "/tmp/output/extract.log"
    mock_log_file.to_dict.return_value = {"id": "log1", "display_name": "extract.log"}

    # create_output_file is called twice: once for log file, once for extracted file
    output_file_side_effect = [
        mock_log_file,  # Log file
        Mock(
            path="/tmp/output/extracted_file.txt",
            to_dict=lambda: {"id": "file2", "display_name": "extracted.txt"},
        ),  # Extracted file
    ]
    mock_dependencies["create_output_file"].side_effect = output_file_side_effect

    mock_dependencies["extract_archive"].return_value = (
        "extract_cmd",
        "/tmp/export_dir",
    )

    # Mock Path and glob
    mock_export_path_obj = Mock()
    mock_extracted_file = Mock()
    mock_extracted_file.is_file.return_value = True
    mock_extracted_file.name = "extracted.txt"
    mock_extracted_file.relative_to.return_value = "extracted.txt"
    # Ensure absolute() returns a mock that can be stringified if needed
    mock_extracted_file.absolute.return_value = "/tmp/export_dir/extracted.txt"

    mock_export_path_obj.glob.return_value = [mock_extracted_file]
    mock_dependencies["path"].return_value = mock_export_path_obj

    mock_dependencies["create_task_result"].return_value = "serialized_result"

    # Call the task using __class__.run mock_celery_task as self
    result = archives.extract_archive_task.__class__.run(
        mock_celery_task,
        pipe_result="pipe_res",
        input_files=None,
        output_path="/tmp/output",
        workflow_id="wf1",
        task_config={"file_filter": "*.txt", "archive_password": "pass"},
    )

    # Assertions
    assert result == "serialized_result"
    mock_dependencies["get_input_files"].assert_called_once_with("pipe_res", [])
    mock_dependencies["create_output_file"].assert_any_call(
        "/tmp/output", display_name="extract_archives_archive.zip.log"
    )
    mock_dependencies["extract_archive"].assert_called_once_with(
        {"id": "file1", "display_name": "archive.zip", "path": "/path/to/archive.zip"},
        "/tmp/output",
        "/tmp/output/extract.log",
        ["*.txt"],
        "pass",
        True,
    )
    mock_dependencies["rename"].assert_called_once()
    mock_dependencies["rmtree"].assert_called_once_with("/tmp/export_dir")
    mock_dependencies["create_task_result"].assert_called_once()

    # Check that task_progress event was sent
    mock_celery_task.send_event.assert_called_with("task-progress")


def test_extract_archive_task_no_input_files(mock_celery_task, mock_dependencies):
    """Test extract_archive_task with no input files."""
    mock_dependencies["get_input_files"].return_value = []
    mock_dependencies["create_task_result"].return_value = "empty_result"

    result = archives.extract_archive_task.__class__.run(
        mock_celery_task,
        pipe_result=None,
        input_files=[],
        output_path="/tmp/output",
        workflow_id="wf1",
        task_config={},
    )

    assert result == "empty_result"
    mock_dependencies["create_task_result"].assert_called_once_with(
        output_files=[], task_files=[], workflow_id="wf1", command=""
    )


def test_extract_archive_task_exception(mock_celery_task, mock_dependencies):
    """Test extract_archive_task when extract_archive raises an exception."""
    mock_dependencies["get_input_files"].return_value = [{"id": "file1"}]
    mock_log_file = Mock()
    mock_log_file.path = "/tmp/log"
    mock_dependencies["create_output_file"].return_value = mock_log_file

    mock_dependencies["extract_archive"].side_effect = Exception("Extraction failed")

    with pytest.raises(Exception, match="Extraction failed"):
        archives.extract_archive_task.__class__.run(
            mock_celery_task,
            pipe_result=None,
            input_files=[{"id": "file1"}],
            output_path="/tmp/output",
            workflow_id="wf1",
            task_config={},
        )


def test_extract_archive_task_file_filter_list(mock_celery_task, mock_dependencies):
    """Test that file filters are correctly parsed."""
    mock_dependencies["get_input_files"].return_value = [
        {"id": "file1", "display_name": "archive.zip"}
    ]
    mock_dependencies["create_output_file"].return_value = Mock(
        path="/tmp/log", to_dict=lambda: {}
    )
    mock_dependencies["extract_archive"].return_value = ("cmd", "/tmp/export")
    mock_dependencies["path"].return_value.glob.return_value = []
    mock_dependencies["create_task_result"].return_value = "res"

    archives.extract_archive_task.__class__.run(
        mock_celery_task,
        input_files=None,
        output_path="/tmp/output",
        workflow_id="wf1",
        task_config={"file_filter": "*.txt,*.log"},
    )

    # Access the call args to verify file_filter list
    args, _ = mock_dependencies["extract_archive"].call_args
    assert args[3] == ["*.txt", "*.log"]


def test_extract_archive_task_ignore_prompts_default(
    mock_celery_task, mock_dependencies
):
    """Test that ignore_prompts defaults to True when not in task_config."""
    mock_dependencies["get_input_files"].return_value = [
        {"id": "file1", "display_name": "archive.zip"}
    ]
    mock_dependencies["create_output_file"].return_value = Mock(
        path="/tmp/log", to_dict=lambda: {}
    )
    mock_dependencies["extract_archive"].return_value = ("cmd", "/tmp/export")
    mock_dependencies["path"].return_value.glob.return_value = []
    mock_dependencies["create_task_result"].return_value = "res"

    archives.extract_archive_task.__class__.run(
        mock_celery_task,
        input_files=None,
        output_path="/tmp/output",
        workflow_id="wf1",
        task_config={},
    )

    args, _ = mock_dependencies["extract_archive"].call_args
    assert args[5] is True


def test_extract_archive_task_ignore_prompts_true(mock_celery_task, mock_dependencies):
    """Test that ignore_prompts is forwarded when explicitly set to True."""
    mock_dependencies["get_input_files"].return_value = [
        {"id": "file1", "display_name": "archive.zip"}
    ]
    mock_dependencies["create_output_file"].return_value = Mock(
        path="/tmp/log", to_dict=lambda: {}
    )
    mock_dependencies["extract_archive"].return_value = ("cmd", "/tmp/export")
    mock_dependencies["path"].return_value.glob.return_value = []
    mock_dependencies["create_task_result"].return_value = "res"

    archives.extract_archive_task.__class__.run(
        mock_celery_task,
        input_files=None,
        output_path="/tmp/output",
        workflow_id="wf1",
        task_config={"ignore_prompts": True},
    )

    args, _ = mock_dependencies["extract_archive"].call_args
    assert args[5] is True


def test_extract_archive_task_ignore_prompts_false(mock_celery_task, mock_dependencies):
    """Test that ignore_prompts is forwarded when explicitly set to False."""
    mock_dependencies["get_input_files"].return_value = [
        {"id": "file1", "display_name": "archive.zip"}
    ]
    mock_dependencies["create_output_file"].return_value = Mock(
        path="/tmp/log", to_dict=lambda: {}
    )
    mock_dependencies["extract_archive"].return_value = ("cmd", "/tmp/export")
    mock_dependencies["path"].return_value.glob.return_value = []
    mock_dependencies["create_task_result"].return_value = "res"

    archives.extract_archive_task.__class__.run(
        mock_celery_task,
        input_files=None,
        output_path="/tmp/output",
        workflow_id="wf1",
        task_config={"ignore_prompts": False},
    )

    args, _ = mock_dependencies["extract_archive"].call_args
    assert args[5] is False
