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

"""Tests Google Cloud log processor."""

# Note: Use pytest for writing tests!
import base64
import json
import os
import tempfile

from unittest import mock

import pytest

with mock.patch.dict(os.environ, {"REDIS_URL": "redis://"}, clear=True):
    from src.gcp import command


def test_command_no_output_files_error():
    """Test command without valid input and output."""
    input_files = []
    output_path = "/data/fake/output_path"
    workflow_id = "test_workflow_id"
    task_config = {
        "request_field": "request1,request2",
        "response_field": "response1,response2",
    }

    with pytest.raises(RuntimeError, match="No supported input files"):
        command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id=workflow_id,
            task_config=task_config,
        )


def test_command_success():
    """Test the command function with successful execution."""
    input_files = [
        {
            "display_name": "sample_gcp_log.jsonl",
            "path": "./test_data/sample_gcp_log.jsonl",
        }
    ]
    workflow_id = "test_workflow_id"
    task_config = {
        "request_field": "all",
        "response_field": "all",
    }

    with tempfile.TemporaryDirectory() as output_path:
        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path=output_path,
            workflow_id=workflow_id,
            task_config=task_config,
        )

    decoded_result = base64.b64decode(result)
    json_result = json.loads(decoded_result)

    assert json_result.get("workflow_id") == "test_workflow_id"

    display_names = []
    for output_file in json_result.get("output_files", []):
        display_name = output_file.get("display_name")
        if display_name:
            display_names.append(display_name)

    assert "sample_gcp_log_output.jsonl" in display_names
    assert "sample_gcp_log_report.md" in display_names
