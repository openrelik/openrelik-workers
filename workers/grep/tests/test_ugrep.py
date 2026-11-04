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

"""Tests ugrep task."""

import base64
import datetime
import json
import tempfile
from collections import namedtuple
from unittest import mock

from src.task_ugrep import command, on_task_prerun, prepare_base_command


def test_prepare_base_command_basic():
    """Test prepare_base_command with just a pattern."""
    task_config = {"pattern": "my_pattern"}
    expected = ["ugrep", "my_pattern", "--"]
    assert prepare_base_command(task_config) == expected


def test_prepare_base_command_all_flags():
    """Test prepare_base_command with all flags enabled."""
    task_config = {
        "stats": True,
        "json_output": True,
        "decompress": True,
        "invert-match": True,
        "pattern": "test_pattern",
    }
    expected = [
        "ugrep",
        "--stats",
        "--json",
        "--decompress",
        "--invert-match",
        "test_pattern",
        "--",
    ]
    assert prepare_base_command(task_config) == expected


def test_prepare_base_command_some_flags():
    """Test prepare_base_command with a subset of flags enabled."""
    task_config = {
        "stats": False,
        "json_output": True,
        "decompress": False,
        "invert-match": True,
        "pattern": "another_pattern",
    }
    expected = ["ugrep", "--json", "--invert-match", "another_pattern", "--"]
    assert prepare_base_command(task_config) == expected


def test_on_task_prerun():
    """Test on_task_prerun signal handler."""
    task_cls = namedtuple("Task", ["name"])
    task = task_cls(name="openrelik-worker-grep.tasks.ugrep")
    on_task_prerun(
        sender=None,
        task_id="task-123",
        task=task,
        args=[],
        kwargs={},
    )


def test_ugrep_command_empty_input_files():
    """Test ugrep command with no input files."""
    with tempfile.TemporaryDirectory() as output_path:
        result = command(
            pipe_result=None,
            input_files=[],
            output_path=output_path,
            workflow_id="wf-123",
            task_config={"pattern": "abc"},
        )
        decoded = json.loads(base64.b64decode(result))
        assert decoded["workflow_id"] == "wf-123"
        assert decoded["output_files"] == []


def test_ugrep_command_success():
    """Test ugrep command with input files and progress events."""
    with (
        tempfile.TemporaryDirectory() as output_path,
        mock.patch("subprocess.Popen") as mock_popen,
        mock.patch.object(command, "send_event") as mock_send_event,
        mock.patch("time.sleep") as mock_sleep,
        mock.patch("src.task_ugrep.count_file_lines", return_value=10),
        mock.patch("src.task_ugrep.datetime") as mock_dt,
    ):
        mock_proc = mock.MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        now1 = datetime.datetime(2025, 1, 1, 12, 0, 0)
        now2 = datetime.datetime(2025, 1, 1, 12, 0, 2)
        mock_dt.datetime.now.side_effect = [now1, now2]

        input_files = [
            {"display_name": "sample.log", "path": "/fake/path/sample.log"}
        ]
        task_config = {
            "pattern": "ERROR",
            "stats": True,
            "json_output": True,
        }

        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id="wf-123",
            task_config=task_config,
        )

        mock_send_event.assert_called_once_with(
            "task-progress", data={"extracted_strings": 10, "rate": 5}
        )
        mock_sleep.assert_called_once_with(3)

        decoded = json.loads(base64.b64decode(result))
        assert decoded["workflow_id"] == "wf-123"
        assert len(decoded["output_files"]) == 1
        assert decoded["output_files"][0]["display_name"] == "sample.log.ugrep.json"


def test_ugrep_command_rate_zero_when_duration_zero():
    """Test ugrep command rate calculation when duration is 0."""
    with (
        tempfile.TemporaryDirectory() as output_path,
        mock.patch("subprocess.Popen") as mock_popen,
        mock.patch.object(command, "send_event") as mock_send_event,
        mock.patch("time.sleep"),
        mock.patch("src.task_ugrep.count_file_lines", return_value=5),
        mock.patch("src.task_ugrep.datetime") as mock_dt,
    ):
        mock_proc = mock.MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        same_time = datetime.datetime(2025, 1, 1, 12, 0, 0)
        mock_dt.datetime.now.side_effect = [same_time, same_time]

        input_files = [
            {"display_name": "sample.log", "path": "/fake/path/sample.log"}
        ]
        task_config = {
            "pattern": "WARN",
            "json_output": False,
        }

        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id="wf-456",
            task_config=task_config,
        )

        mock_send_event.assert_called_once_with(
            "task-progress", data={"extracted_strings": 5, "rate": 0}
        )
        decoded = json.loads(base64.b64decode(result))
        assert decoded["output_files"][0]["display_name"] == "sample.log.ugrep"
