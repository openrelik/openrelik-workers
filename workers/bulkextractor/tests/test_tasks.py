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
"""Tests tasks."""

import pytest
from unittest.mock import patch, MagicMock

from src.tasks import command


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.Popen")
@patch("src.tasks.create_output_file")
@patch("src.tasks.generate_summary_report")
@patch("src.tasks.extract_non_empty_files")
@patch("src.tasks.serialize_file_report")
@patch("src.tasks.create_task_result")
@patch("src.tasks.os.path.exists")
@patch("src.tasks.shutil.rmtree")
def test_command_without_options(
    mock_rmtree,
    mock_exists,
    mock_create_task_result,
    mock_serialize_file_report,
    mock_extract_non_empty_files,
    mock_generate_summary_report,
    mock_create_output_file,
    mock_popen,
    mock_get_input_files,
):
    """Test the command task without custom command line options."""
    input_files = [{"path": "/tmp/test.txt", "display_name": "test.txt"}]
    mock_get_input_files.return_value = input_files

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    mock_report_file = MagicMock()
    mock_report_file.path = "/tmp/output/Report_test.txt.html"
    mock_report_file.to_dict.return_value = {"display_name": "Report_test.txt.html"}
    mock_create_output_file.return_value = mock_report_file

    mock_report = MagicMock()
    mock_report.to_markdown.return_value = "# Summary"
    mock_generate_summary_report.return_value = mock_report

    mock_extract_non_empty_files.return_value = [{"display_name": "email.txt"}]
    mock_serialize_file_report.return_value = {"report_serialized": True}

    mock_exists.return_value = True

    mock_create_task_result.return_value = "task_result_success"

    # Call
    with patch("src.tasks.open", create=True) as mock_open:
        mock_fh = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_fh

        result = command.run(
            pipe_result=None,
            input_files=input_files,
            output_path="/tmp/output",
            workflow_id="workflow-123",
            task_config=None,
        )

    # Assertions
    assert result == "task_result_success"

    # Check that subprocess Popen was called with the default command list
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    cmd_list = args[0]
    assert cmd_list[0] == "bulk_extractor"
    assert "-o" in cmd_list
    assert cmd_list[-1] == "/tmp/test.txt"
    # Ensure options from task_config were NOT injected
    assert len(cmd_list) == 4  # ["bulk_extractor", "-o", tmp_dir, "/tmp/test.txt"]

    # Verify that the output files were written
    mock_open.assert_called_once_with(mock_report_file.path, "w")
    mock_fh.write.assert_called_once_with("# Summary")


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.Popen")
@patch("src.tasks.create_output_file")
@patch("src.tasks.generate_summary_report")
@patch("src.tasks.extract_non_empty_files")
@patch("src.tasks.serialize_file_report")
@patch("src.tasks.create_task_result")
@patch("src.tasks.os.path.exists")
@patch("src.tasks.shutil.rmtree")
def test_command_with_options(
    mock_rmtree,
    mock_exists,
    mock_create_task_result,
    mock_serialize_file_report,
    mock_extract_non_empty_files,
    mock_generate_summary_report,
    mock_create_output_file,
    mock_popen,
    mock_get_input_files,
):
    """Test the command task with simple custom command line options."""
    input_files = [{"path": "/tmp/test.txt", "display_name": "test.txt"}]
    mock_get_input_files.return_value = input_files

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    mock_report_file = MagicMock()
    mock_report_file.path = "/tmp/output/Report_test.txt.html"
    mock_report_file.to_dict.return_value = {"display_name": "Report_test.txt.html"}
    mock_create_output_file.return_value = mock_report_file

    mock_report = MagicMock()
    mock_report.to_markdown.return_value = "# Summary"
    mock_generate_summary_report.return_value = mock_report

    mock_extract_non_empty_files.return_value = []
    mock_exists.return_value = True
    mock_create_task_result.return_value = "task_result_success"

    # Call
    task_config = {"options": "-x all -e wordlist"}
    with patch("src.tasks.open", create=True) as mock_open:
        mock_fh = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_fh

        result = command.run(
            pipe_result=None,
            input_files=input_files,
            output_path="/tmp/output",
            workflow_id="workflow-123",
            task_config=task_config,
        )

    # Assertions
    assert result == "task_result_success"

    # Check that subprocess Popen was called with the injected options
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    cmd_list = args[0]
    assert cmd_list[0] == "bulk_extractor"

    # Check that the options are inside cmd_list
    assert cmd_list[1:5] == ["-x", "all", "-e", "wordlist"]
    assert "-o" in cmd_list
    assert cmd_list[-1] == "/tmp/test.txt"


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.Popen")
@patch("src.tasks.create_output_file")
@patch("src.tasks.generate_summary_report")
@patch("src.tasks.extract_non_empty_files")
@patch("src.tasks.serialize_file_report")
@patch("src.tasks.create_task_result")
@patch("src.tasks.os.path.exists")
@patch("src.tasks.shutil.rmtree")
def test_command_with_complex_quoted_options(
    mock_rmtree,
    mock_exists,
    mock_create_task_result,
    mock_serialize_file_report,
    mock_extract_non_empty_files,
    mock_generate_summary_report,
    mock_create_output_file,
    mock_popen,
    mock_get_input_files,
):
    """Test that quoted options are correctly split without breaking strings."""
    input_files = [{"path": "/tmp/test.txt", "display_name": "test.txt"}]
    mock_get_input_files.return_value = input_files

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    mock_report_file = MagicMock()
    mock_report_file.path = "/tmp/output/Report_test.txt.html"
    mock_report_file.to_dict.return_value = {"display_name": "Report_test.txt.html"}
    mock_create_output_file.return_value = mock_report_file

    mock_report = MagicMock()
    mock_report.to_markdown.return_value = "# Summary"
    mock_generate_summary_report.return_value = mock_report

    mock_extract_non_empty_files.return_value = []
    mock_exists.return_value = True
    mock_create_task_result.return_value = "task_result_success"

    # Call
    task_config = {"options": "-x 'all scanners'  -e  \"word list\""}
    with patch("src.tasks.open", create=True) as mock_open:
        mock_fh = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_fh

        result = command.run(
            pipe_result=None,
            input_files=input_files,
            output_path="/tmp/output",
            workflow_id="workflow-123",
            task_config=task_config,
        )

    # Assertions
    assert result == "task_result_success"

    # Check that subprocess Popen was called with the correctly parsed options
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    cmd_list = args[0]
    assert cmd_list[0] == "bulk_extractor"

    # Check that the options are split properly (preserving spaces within quotes)
    assert cmd_list[1:5] == ["-x", "all scanners", "-e", "word list"]


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.Popen")
@patch("src.tasks.os.path.exists")
def test_command_failure_return_code(
    mock_exists,
    mock_popen,
    mock_get_input_files,
):
    """Test that RuntimeError is raised when the subprocess returns non-zero."""
    input_files = [{"path": "/tmp/test.txt", "display_name": "test.txt"}]
    mock_get_input_files.return_value = input_files

    mock_process = MagicMock()
    mock_process.returncode = 1
    mock_popen.return_value = mock_process

    # Call and Assert
    with pytest.raises(RuntimeError, match="Bulk Extractor failed with exit code 1."):
        command.run(
            pipe_result=None,
            input_files=input_files,
            output_path="/tmp/output",
            workflow_id="workflow-123",
            task_config=None,
        )


@patch("src.tasks.get_input_files")
@patch("src.tasks.subprocess.Popen")
@patch("src.tasks.os.path.exists")
def test_command_failure_output_dir_missing(
    mock_exists,
    mock_popen,
    mock_get_input_files,
):
    """Test that RuntimeError is raised when the expected output directory is not created."""
    input_files = [{"path": "/tmp/test.txt", "display_name": "test.txt"}]
    mock_get_input_files.return_value = input_files

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    # The output directory was not created
    mock_exists.return_value = False

    # Call and Assert
    with pytest.raises(
        RuntimeError, match="successful but output directory .* was not created"
    ):
        command.run(
            pipe_result=None,
            input_files=input_files,
            output_path="/tmp/output",
            workflow_id="workflow-123",
            task_config=None,
        )
