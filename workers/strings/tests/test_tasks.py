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
from unittest import mock

from src import tasks


def test_strings_encoding_enum():
    """Test StringsEncoding enum."""
    assert tasks.StringsEncoding.ASCII == "s"
    assert tasks.StringsEncoding.UTF16LE == "l"


@mock.patch("builtins.open", new_callable=mock.mock_open)
@mock.patch("src.tasks.telemetry")
@mock.patch("src.tasks.get_input_files")
@mock.patch("src.tasks.create_output_file")
@mock.patch("src.tasks.create_task_result")
@mock.patch("src.tasks.subprocess.Popen")
@mock.patch("src.tasks.count_file_lines")
@mock.patch("src.tasks.time.sleep")
def test_strings_task_success(
    mock_sleep,
    mock_count_lines,
    mock_popen,
    mock_create_result,
    mock_create_output,
    mock_get_input,
    mock_telemetry,
    mock_open,
):
    """Test the strings task with valid input and config."""
    # Setup mocks
    mock_get_input.return_value = [
        {"path": "/tmp/test_file.txt", "display_name": "test_file.txt"}
    ]

    mock_output_file = mock.Mock()
    mock_output_file.path = "/tmp/output/test_file.txt.s_strings"
    mock_output_file.to_dict.return_value = {
        "path": "/tmp/output/test_file.txt.s_strings"
    }
    mock_create_output.return_value = mock_output_file

    mock_process = mock.Mock()
    mock_process.poll.side_effect = [None, 0]  # Run once then finish
    mock_popen.return_value = mock_process

    mock_count_lines.return_value = 100

    # We need to mock send_event on the task instance itself
    with mock.patch.object(tasks.strings, "send_event") as mock_send_event:
        # Call the task
        tasks.strings.run(
            pipe_result="dummy_pipe",
            input_files=[{"path": "/tmp/test_file.txt"}],
            output_path="/tmp/output",
            workflow_id="workflow_123",
            task_config={"ASCII": True},
        )

        # Verify progress reporting
        mock_send_event.assert_called_with(
            "task-progress", data={"extracted_strings": 100, "rate": mock.ANY}
        )

    # Verifications
    mock_get_input.assert_called()
    mock_create_output.assert_called()
    mock_open.assert_called_with("/tmp/output/test_file.txt.s_strings", "w")

    # Verify command arguments
    expected_command = [
        "strings",
        "-a",
        "-t",
        "d",
        "--encoding",
        "s",
        "/tmp/test_file.txt",
    ]
    mock_popen.assert_called()
    args, _ = mock_popen.call_args
    assert args[0] == expected_command

    mock_create_result.assert_called()
    mock_telemetry.add_attribute_to_current_span.assert_called()


@mock.patch("src.tasks.get_input_files")
def test_strings_task_invalid_encoding(mock_get_input):
    """Test strict encoding validation."""
    mock_get_input.return_value = [{"path": "test"}]

    with pytest.raises(RuntimeError, match="INVALID_ENC is not a valid"):
        tasks.strings.run(input_files=[], task_config={"INVALID_ENC": True})


@mock.patch("src.tasks.get_input_files")
def test_strings_task_no_output(mock_get_input):
    """Test error when no output files are generated."""
    mock_get_input.return_value = []  # No input files

    with pytest.raises(RuntimeError, match="No strings extracted"):
        tasks.strings.run(input_files=[], task_config={"ASCII": True})
