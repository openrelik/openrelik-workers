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

import base64
import filecmp
import json
import os
import time
from threading import Thread
from unittest.mock import patch

from fakeredis import TcpFakeServer
from freezegun import freeze_time

from src.tasks import run_ssh_analyzer

_INPUT_FILES = [
    {
        "id": 1,
        "uuid": "445027ec76ef42f8a463fdbaf162d2b7",
        "display_name": "secure",
        "extension": "",
        "data_type": "file:generic",
        "path": "test_data/secure",
    }
]

_INPUT_FILES_SSH_EVENTS_NO_BRUTEFORCE = [
    {
        "id": 1,
        "uuid": "445027ec76ef42f8a463fdbaf162d2b9",
        "display_name": "secure.1",
        "extension": "",
        "data_type": "file:generic",
        "path": "test_data/secure.1",
    }
]

_INPUT_FILES_WITHOUT_SSH_EVENTS = [
    {
        "id": 1,
        "uuid": "445027ec76ef42f8a463fdbaf162d2b8",
        "display_name": "shadow",
        "extension": "",
        "data_type": "file:generic",
        "path": "test_data/shadow",
    }
]


# Start fake redis server for tests
server_address = ("127.0.0.1", 6379)
server = TcpFakeServer(server_address, server_type="redis")
server_thread = Thread(target=server.serve_forever, daemon=True)
server_thread.daemon = True
server_thread.start()
# Wait for the server thread to start
time.sleep(0.1)


def setUpModule():
    """Executed once before any tests in this module run."""
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()


def tearDownModule():
    """Optional: Restores the environment after all tests are finished."""
    if "TZ" in os.environ:
        del os.environ["TZ"]
    if hasattr(time, "tzset"):
        time.tzset()


class TestTasks:
    @freeze_time("2025-12-30 03:20:00")
    @patch("src.app.redis.Redis.from_url")
    def test_run_ssh_analyzer(self, mock_redisclient):
        """Test LinuxSSHAnalysis task run."""

        output = run_ssh_analyzer(
            input_files=_INPUT_FILES,
            output_path="/tmp",
            workflow_id="deadbeef",
            task_config={},
        )

        output_dict = json.loads(base64.b64decode(output))
        output_path = output_dict.get("output_files")[0].get("path")
        assert filecmp.cmp(
            output_path, "test_data/linux_ssh_analysis.md", shallow=False
        )

    @patch("src.app.redis.Redis.from_url")
    def test_run_ssh_analyzer_with_log_year(self, mock_redisclient):
        """Test LinuxSSHAnalysis task run."""

        output = run_ssh_analyzer(
            input_files=_INPUT_FILES,
            output_path="/tmp",
            workflow_id="deadbeef",
            task_config={"log_year": "2025"},
        )

        output_dict = json.loads(base64.b64decode(output))
        output_path = output_dict.get("output_files")[0].get("path")
        assert filecmp.cmp(
            output_path, "test_data/linux_ssh_analysis.md", shallow=False
        )

    @patch("src.app.redis.Redis.from_url")
    def test_task_report_no_ssh_events(self, mock_redisclient):
        """Test for proper task report summary."""

        output = run_ssh_analyzer(
            input_files=_INPUT_FILES_WITHOUT_SSH_EVENTS,
            output_path="/tmp",
            workflow_id="deadbeef",
            task_config={},
        )

        output_dict = json.loads(base64.b64decode(output))
        output_task_report_summary = output_dict.get("task_report").get("content")
        assert (
            "No SSH authentication events in input files." in output_task_report_summary
        )

    @patch("src.app.redis.Redis.from_url")
    def test_task_report_no_bruteforce(self, mock_redisclient):
        """Test for proper task report summary."""

        output = run_ssh_analyzer(
            input_files=_INPUT_FILES_SSH_EVENTS_NO_BRUTEFORCE,
            output_path="/tmp",
            workflow_id="deadbeef",
            task_config={},
        )

        output_dict = json.loads(base64.b64decode(output))
        output_task_report_summary = output_dict.get("task_report").get("content")
        assert (
            "# SSH log analyzer report\n\n\n##### Brute force analysis\n\n- No findings\n"
            in output_task_report_summary
        )
