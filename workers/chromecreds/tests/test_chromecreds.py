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
from unittest.mock import patch

from src.tasks import _extract_chrome_creds, generate_report

from openrelik_worker_common.reporting import Report, Priority

class TestChromeCredsAnalyser(unittest.TestCase):
  EXPECTED_CREDENTIALS = {'http://test.com': ['testuser']}
  TWO_CREDENTIALS = {
      'http://test.com': ['testuser'],
      'http://example.com': ['exampleuser', 'admin']
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

  def test_report(self):
    """Tests the summarise_creds method."""
    report = generate_report(self.TWO_CREDENTIALS)
    self.assertIsInstance(report, Report)
    self.assertEqual(report.to_markdown(), self.CREDS_REPORT)
    self.assertEqual(report.priority, Priority.MEDIUM)
    self.assertEqual(report.summary, '2 saved credentials found in Chrome Login Data')