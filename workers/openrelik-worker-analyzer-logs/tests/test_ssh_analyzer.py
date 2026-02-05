# -*- coding: utf-8 -*-
# Copyright 2025 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Task for Linux SSH analysis."""

import pytest
import datetime
import os
import shutil

import src.ssh_analyzer as ssh_analyzer


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


class TestLinuxSSHAnalysisTask:
    """Test for LinuxSSHAnalysisTask task."""

    def test_parse_log_data(self):
        """Test parsing SSH log file"""
        log_file = os.path.join("test_data", "secure")
        if not os.path.exists(log_file):
            raise FileNotFoundError(f"{log_file} does not exist.")

        with open(log_file, "r", encoding="utf-8") as fh:
            data = fh.read()
        a = ssh_analyzer.LinuxSSHAnalysisTask()
        ssh_records = a.parse_log_data(data, log_file, log_year=2022)
        assert len(ssh_records) == 27719

    def test_read_logs(self):
        """Test read_logs method."""
        analyzer = ssh_analyzer.LinuxSSHAnalysisTask()

        print("[+] Checking empty input_files")
        result = analyzer.read_logs(input_files="")
        assert result.empty

        print("[+] Checking test_data/secure as input_files")
        result = analyzer.read_logs(input_files=_INPUT_FILES)
        assert len(result) == 27719

    def test_read_logs_with_log_year(self):
        """Test read_logs method when log_year parameter is specified."""
        analyzer = ssh_analyzer.LinuxSSHAnalysisTask(log_year=2019)

        print("[+] Checking test_data/secure as input_files")
        result = analyzer.read_logs(input_files=_INPUT_FILES)
        assert str(result["date"].iloc[0]).startswith("2019")

    @pytest.mark.skipif(
        datetime.datetime.now().astimezone().tzname() != "UTC",
        reason="This test must be run on a UTC-configured machine",
    )
    def test_parse_message_datetime(self):
        """Test parsing message datetime fields."""
        analyzer = ssh_analyzer.LinuxSSHAnalysisTask()

        # Testing Feb 8 13:30:45 Debian/CentOS format
        output = analyzer.parse_message_datetime(
            message_datetime=["Feb", "8", "13:30:45"], log_year=2023
        )
        expected_output = datetime.datetime(
            2023, 2, 8, 13, 30, 45, tzinfo=datetime.timezone.utc
        )
        assert output == expected_output

        # Testing 2023-02-08T13:30:45.123456+11:00 OpenSUSE format
        output = analyzer.parse_message_datetime(
            message_datetime=["2023-02-08T13:30:45.123456+11:00"], log_year=0
        )
        expected_output = datetime.datetime(
            2023, 2, 8, 2, 30, 45, 123456, datetime.timezone.utc
        )
        assert output == expected_output

        # Invalid datetime 2023-13-10 22:10:10
        output = analyzer.parse_message_datetime(
            message_datetime=["2023-13-10 22:10:10"], log_year=0
        )
        assert output is None

        # Invalid datetime random
        output = analyzer.parse_message_datetime(["random"], log_year=0)
        assert output is None
