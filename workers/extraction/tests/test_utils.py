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

import logging
import pytest
from unittest.mock import Mock, call

from src import utils


@pytest.fixture
def mock_logger():
    return Mock()


def test_process_plaso_cli_logs_standard(mock_logger):
    """Test processing standard log lines with known levels."""
    logs = (
        "[INFO] This is an info message\n"
        "[WARNING] This is a warning message\n"
        "[ERROR] This is an error message\n"
    )

    utils.process_plaso_cli_logs(logs, mock_logger)

    expected_calls = [
        call(logging.INFO, "This is an info message"),
        call(logging.WARNING, "This is a warning message"),
        call(logging.ERROR, "This is an error message"),
    ]
    mock_logger.log.assert_has_calls(expected_calls)


def test_process_plaso_cli_logs_multiline(mock_logger):
    """Test processing multi-line logs (e.g. tracebacks)."""
    logs = (
        "[ERROR] An error occurred\n"
        "Traceback (most recent call last):\n"
        '  File "script.py", line 10, in <module>\n'
        '    raise ValueError("oops")\n'
        "[INFO] Recovery successful"
    )

    utils.process_plaso_cli_logs(logs, mock_logger)

    expected_calls = [
        call(logging.ERROR, "An error occurred"),
        call(logging.ERROR, "Traceback (most recent call last):"),
        call(logging.ERROR, '  File "script.py", line 10, in <module>'),
        call(logging.ERROR, '    raise ValueError("oops")'),
        call(logging.INFO, "Recovery successful"),
    ]
    mock_logger.log.assert_has_calls(expected_calls)


def test_process_plaso_cli_logs_unknown_level(mock_logger):
    """Test processing lines with unknown log levels."""
    logs = (
        "[INFO] Start\n"
        "[UNKNOWN_LEVEL] This should be logged as INFO (previous level)\n"
        "[CRITICAL] Critical error\n"
        "[WEIRD] This should be logged as CRITICAL (previous level)"
    )

    utils.process_plaso_cli_logs(logs, mock_logger)

    expected_calls = [
        call(logging.INFO, "Start"),
        call(logging.INFO, "This should be logged as INFO (previous level)"),
        call(logging.CRITICAL, "Critical error"),
        call(logging.CRITICAL, "This should be logged as CRITICAL (previous level)"),
    ]
    mock_logger.log.assert_has_calls(expected_calls)


def test_process_plaso_cli_logs_empty(mock_logger):
    """Test processing empty lines and empty input."""
    logs = "[INFO] Line 1\n\n   \n[INFO] Line 2"

    utils.process_plaso_cli_logs(logs, mock_logger)

    expected_calls = [
        call(logging.INFO, "Line 1"),
        call(logging.INFO, "Line 2"),
    ]
    mock_logger.log.assert_has_calls(expected_calls)

    mock_logger.reset_mock()
    utils.process_plaso_cli_logs("", mock_logger)
    mock_logger.log.assert_not_called()
