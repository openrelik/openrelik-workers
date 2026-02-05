# Copyright 2024-2025 Google LLC
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
from unittest.mock import mock_open, patch

from openrelik_worker_common.reporting import Priority, Report

from src.analyzers.jenkins_analyzer import (
    _extract_jenkins_credentials,
    _extract_jenkins_version,
    analyze_config,
)


class JenkinsTest(unittest.TestCase):
    """Test the Jenkins analyzer functions."""

    def test_jenkins_extract_versions(self):
        """Test Jenkins version extraction."""
        config = "<version>1.29.2</version>"
        result = _extract_jenkins_version(config)
        expected = "1.29.2"
        self.assertEqual(result, expected)

    def test_jenkins_extract_credentials(self):
        """Test Jenkins credential extraction."""
        config = (
            """<fullName>Ramses de Beer</fullName>"""
            """<passwordHash>#jbcrypt:$2a$10$razd3L1aXndFfBNHO95aj.IVrFydsxkcQCcLmujmFQzll3hcUrY7S</passwordHash>"""
        )
        result = _extract_jenkins_credentials(config)
        expected = [
            (
                "Ramses de Beer",
                "$2a$10$razd3L1aXndFfBNHO95aj.IVrFydsxkcQCcLmujmFQzll3hcUrY7S",
            )
        ]
        self.assertEqual(result, expected)

    @patch("src.analyzers.jenkins_analyzer.bruteforce_password_hashes")
    def test_analyze_config(self, bruteforce):
        """Test Jenkins config analysis."""
        bruteforce.return_value = [
            ("$2a$10$razd3L1aXndFfBNHO95aj.IVrFydsxkcQCcLmujmFQzll3hcUrY7S", "test")
        ]
        config = (
            """<version>1.29.2</version>"""
            """<fullName>Ramses de Beer</fullName>"""
            """<passwordHash>#jbcrypt:$2a$10$razd3L1aXndFfBNHO95aj.IVrFydsxkcQCcLmujmFQzll3hcUrY7S</passwordHash>"""
        )
        jenkins_config_report_expected = (
            """\n"""
            """* Jenkins version: 1.29.2\n"""
            """* 1 weak password(s) found:\n"""
            """    * User "Ramses de Beer" with password \"test\""""
        )
        jenkins_config_summary_expected = "Jenkins analysis found potential issues"
        input_file = {"path": "/dummy/path"}

        with patch("builtins.open", mock_open(read_data=config)):
            result = analyze_config(input_file, {})
        self.assertIsInstance(result, Report)
        self.assertEqual(result.priority, Priority.CRITICAL)
        self.assertEqual(result.summary, jenkins_config_summary_expected)
        self.assertEqual(result.to_markdown(), jenkins_config_report_expected)


if __name__ == "__main__":
    unittest.main()
