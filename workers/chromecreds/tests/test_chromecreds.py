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


import unittest
import tempfile
import os
from unittest.mock import patch, MagicMock

from src.tasks import _extract_chrome_creds, generate_report, command

from openrelik_worker_common.reporting import Report, Priority


class TestChromeCredsAnalyser(unittest.TestCase):
    EXPECTED_CREDENTIALS = {"http://test.com": ["testuser"]}
    TWO_CREDENTIALS = {
        "http://test.com": ["testuser"],
        "http://example.com": ["exampleuser", "admin"],
    }
    TEST_SQL = "test_data/test_login_data.sqlite"
    CREDS_REPORT = """# Chrome Config Analyzer


2 saved credentials found in Chrome Login Data

* Credentials:
    * Site 'http://test.com' with users '['testuser']'
    * Site 'http://example.com' with users '['exampleuser', 'admin']'"""

    def test_extract_chrome_creds(self):
        """Tests the extract_chrome_creds method."""
        # pylint: disable=protected-access
        credentials = _extract_chrome_creds(self.TEST_SQL)
        self.assertEqual(credentials, self.EXPECTED_CREDENTIALS)

    def test_extract_chrome_creds_operational_error(self):
        """Tests operational error when file does not exist."""
        credentials = _extract_chrome_creds("non_existent_file.sqlite")
        self.assertEqual(credentials, {})

    def test_extract_chrome_creds_database_error(self):
        """Tests database error when file is not sqlite."""
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Not an sqlite database")
            tf.flush()
            credentials = _extract_chrome_creds(tf.name)
        os.remove(tf.name)
        self.assertEqual(credentials, {})

    def test_report(self):
        """Tests the summarise_creds method."""
        report = generate_report(self.TWO_CREDENTIALS)
        self.assertIsInstance(report, Report)
        self.assertEqual(report.to_markdown(), self.CREDS_REPORT)
        self.assertEqual(report.priority, Priority.MEDIUM)
        self.assertEqual(
            report.summary, "2 saved credentials found in Chrome Login Data"
        )

    def test_report_empty(self):
        """Tests the summarise_creds method with no creds."""
        report = generate_report({})
        self.assertIsInstance(report, Report)
        self.assertEqual(report.priority, Priority.LOW)
        self.assertEqual(
            report.summary, "0 saved credentials found in Chrome Login Data"
        )
        self.assertIn("No saved credentials found", report.to_markdown())

    @patch("src.tasks.create_output_file")
    def test_command(self, mock_create_output_file):
        """Tests the celery command."""
        import json
        import base64

        mock_output_file = MagicMock()
        mock_output_file.path = os.path.join(tempfile.gettempdir(), "test_report.dict")
        mock_output_file.to_dict.return_value = {"path": mock_output_file.path}
        mock_create_output_file.return_value = mock_output_file

        input_files = [
            {"path": self.TEST_SQL, "display_name": "test_login_data.sqlite"}
        ]

        result = command(
            pipe_result=None,
            input_files=input_files,
            output_path="/tmp",
            workflow_id="test_workflow",
        )

        decoded_result = json.loads(base64.b64decode(result).decode("utf-8"))

        self.assertTrue("output_files" in decoded_result)
        self.assertTrue("task_report" in decoded_result)
        self.assertEqual(len(decoded_result["output_files"]), 1)
        self.assertEqual(len(decoded_result["task_report"]), 1)

        # Clean up
        if os.path.exists(mock_output_file.path):
            os.remove(mock_output_file.path)
