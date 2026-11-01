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

"""Tests for grep task."""

import base64
import datetime
import json
import tempfile
from unittest import mock

import pytest

from src.task_grep import command


def test_grep_command_empty_output_files_raises():
    """Test grep command raises RuntimeError when no files are processed."""
    with pytest.raises(RuntimeError, match="Grep task yielded no results"):
        command(
            pipe_result=None,
            input_files=[],
            output_path="/tmp",
            workflow_id="wf-1",
            task_config={"regex": "abc"},
        )


def test_grep_command_success():
    """Test grep command execution with input files and progress events."""
    with (
        tempfile.TemporaryDirectory() as output_path,
        mock.patch("subprocess.Popen") as mock_popen,
        mock.patch.object(command, "send_event") as mock_send_event,
        mock.patch("time.sleep") as mock_sleep,
        mock.patch("src.task_grep.count_file_lines", return_value=20),
        mock.patch("src.task_grep.datetime") as mock_dt,
    ):
        mock_proc = mock.MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        now1 = datetime.datetime(2025, 1, 1, 12, 0, 0)
        now2 = datetime.datetime(2025, 1, 1, 12, 0, 4)
        mock_dt.datetime.now.side_effect = [now1, now2]

        input_files = [
            {"display_name": "data.txt", "path": "/fake/path/data.txt"}
        ]
        task_config = {"regex": "[0-9]+"}

        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id="wf-grep",
            task_config=task_config,
        )

        mock_send_event.assert_called_once_with(
            "task-progress", data={"extracted_strings": 20, "rate": 5}
        )
        mock_sleep.assert_called_once_with(3)

        decoded = json.loads(base64.b64decode(result))
        assert decoded["workflow_id"] == "wf-grep"
        assert len(decoded["output_files"]) == 1
        assert decoded["output_files"][0]["display_name"] == "data.txt.grep"
        assert decoded["command"] == "grep -Ei [0-9]+"


def test_grep_command_rate_zero_when_duration_zero():
    """Test grep command rate calculation when duration is 0."""
    with (
        tempfile.TemporaryDirectory() as output_path,
        mock.patch("subprocess.Popen") as mock_popen,
        mock.patch.object(command, "send_event") as mock_send_event,
        mock.patch("time.sleep"),
        mock.patch("src.task_grep.count_file_lines", return_value=15),
        mock.patch("src.task_grep.datetime") as mock_dt,
    ):
        mock_proc = mock.MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        same_time = datetime.datetime(2025, 1, 1, 12, 0, 0)
        mock_dt.datetime.now.side_effect = [same_time, same_time]

        input_files = [
            {"display_name": "data.txt", "path": "/fake/path/data.txt"}
        ]
        task_config = {"regex": "[a-z]+"}

        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id="wf-grep-zero",
            task_config=task_config,
        )

        mock_send_event.assert_called_once_with(
            "task-progress", data={"extracted_strings": 15, "rate": 0}
        )
        decoded = json.loads(base64.b64decode(result))
        assert decoded["output_files"][0]["display_name"] == "data.txt.grep"
