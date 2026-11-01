# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for template tasks module."""

import base64
import json
import os
import tempfile
from unittest import mock

import pytest

with mock.patch.dict(os.environ, {"REDIS_URL": "redis://"}, clear=True):
    from src.tasks import command


def test_command_no_output_files():
    with pytest.raises(RuntimeError, match="<REPLACE_WITH_ERROR_STRING>"):
        command(
            pipe_result=None,
            input_files=[],
            output_path="/tmp",
            workflow_id="wf-1",
            task_config={},
        )


def test_command_success():
    with (
        tempfile.TemporaryDirectory() as output_path,
        mock.patch("subprocess.Popen") as mock_popen,
    ):
        mock_proc = mock.MagicMock()
        mock_popen.return_value = mock_proc

        input_files = [{"display_name": "input.txt", "path": "/tmp/input.txt"}]
        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id="wf-1",
            task_config={},
        )

        decoded = json.loads(base64.b64decode(result))
        assert decoded["workflow_id"] == "wf-1"
        assert len(decoded["output_files"]) == 1
        assert decoded["command"] == "<REPLACE_WITH_COMMAND>"
