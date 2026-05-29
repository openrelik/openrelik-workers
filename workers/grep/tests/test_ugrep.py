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
# limitations under the License.import pytest

"""Tests ugrep task."""

from src.task_ugrep import prepare_base_command

def test_prepare_base_command_basic():
    """Test prepare_base_command with just a pattern."""
    task_config = {
        "pattern": "my_pattern"
    }
    expected = ["ugrep", "my_pattern", "--"]
    assert prepare_base_command(task_config) == expected

def test_prepare_base_command_all_flags():
    """Test prepare_base_command with all flags enabled."""
    task_config = {
        "stats": True,
        "json_output": True,
        "decompress": True,
        "invert-match": True,
        "pattern": "test_pattern"
    }
    expected = [
        "ugrep",
        "--stats",
        "--json",
        "--decompress",
        "--invert-match",
        "test_pattern",
        "--"
    ]
    assert prepare_base_command(task_config) == expected

def test_prepare_base_command_some_flags():
    """Test prepare_base_command with a subset of flags enabled."""
    task_config = {
        "stats": False,
        "json_output": True,
        "decompress": False,
        "invert-match": True,
        "pattern": "another_pattern"
    }
    expected = [
        "ugrep",
        "--json",
        "--invert-match",
        "another_pattern",
        "--"
    ]
    assert prepare_base_command(task_config) == expected
