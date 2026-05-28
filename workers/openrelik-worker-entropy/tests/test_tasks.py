"""Tests Entropy tasks."""

import base64
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

from src.tasks import calculate_entropy, HIGH_ENTROPY_THRESHOLD, run_entropy_task


class TestEntropyTask:
    """Tests for the Entropy task."""

    def test_empty_data_entropy(self):
        entropy = calculate_entropy(b'')
        assert (entropy == 0.0)

    def test_random_entropy(self):
        with open('test_data/random.1k', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy > 7.8)

    def test_zero_entropy(self):
        with open('test_data/zero.1k', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy == 0.0)

    def test_log_entropy(self):
        with open('test_data/syslog', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy == 5.129738750791151)

    def test_binary_low_entropy(self):
        with open('test_data/hello.bin', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy > 0 )
            assert (entropy < HIGH_ENTROPY_THRESHOLD)

    def test_binary_high_entropy(self):
        with open('test_data/hello-upx.bin', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy > HIGH_ENTROPY_THRESHOLD)

    @patch("src.tasks.create_output_file")
    @patch("src.tasks.get_input_files")
    def test_run_entropy_task(self, mock_get_input_files, mock_create_output_file):
        mock_get_input_files.return_value = [
            {"path": "test_data/random.1k", "display_name": "random.1k"},
            {"path": "test_data/hello.bin", "display_name": "hello.bin"},
        ]
        
        mock_output_file = MagicMock()
        mock_output_file.path = tempfile.mktemp()
        mock_output_file.to_dict.return_value = {"path": mock_output_file.path}
        mock_create_output_file.return_value = mock_output_file
        
        result = run_entropy_task(
            pipe_result=None,
            input_files=[],
            output_path="/tmp",
            workflow_id="test_workflow",
            task_config={"entropy-threshold": 7.0, "max-filesize": 100},
        )
        
        assert mock_get_input_files.called
        assert mock_create_output_file.called
        
        # Verify the CSV was written
        assert os.path.exists(mock_output_file.path)
        with open(mock_output_file.path, "r") as f:
            content = f.read()
            assert "random.1k" in content
            assert "hello.bin" in content
            
        os.remove(mock_output_file.path)
        
        # Verify task report
        result_decoded = json.loads(base64.b64decode(result).decode("utf-8"))
        assert "task_report" in result_decoded
        assert "Found 1 files" in result_decoded["task_report"]["summary"]

    @patch("src.tasks.create_output_file")
    @patch("src.tasks.get_input_files")
    def test_run_entropy_task_skipped_files(self, mock_get_input_files, mock_create_output_file):
        mock_get_input_files.return_value = [
            {"path": "test_data/random.1k", "display_name": "random.1k"},
        ]
        
        mock_output_file = MagicMock()
        mock_output_file.path = tempfile.mktemp()
        mock_output_file.to_dict.return_value = {"path": mock_output_file.path}
        mock_create_output_file.return_value = mock_output_file
        
        result = run_entropy_task(
            pipe_result=None,
            input_files=[],
            output_path="/tmp",
            workflow_id="test_workflow",
            task_config={"entropy-threshold": 7.0, "max-filesize": -1},
        )
        
        # Verify task report
        result_decoded = json.loads(base64.b64decode(result).decode("utf-8"))
        assert "task_report" in result_decoded
        assert "Skipped 1 files because their size is over the -1MB limit" in result_decoded["task_report"]["summary"]
        os.remove(mock_output_file.path)

