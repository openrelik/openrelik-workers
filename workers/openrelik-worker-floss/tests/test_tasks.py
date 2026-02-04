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

"""Tests tasks."""

from unittest.mock import MagicMock
import builtins
import subprocess
import pytest

from src.tasks import command

import src.tasks


class TestCommandTask:
    """Tests for the FLOSS task."""

    @pytest.fixture
    def mock_celery_self(self, mocker):
        """Fixture for a mock Celery task instance."""
        mock_self = MagicMock()
        mock_self.send_event = mocker.stub("send_event")
        return mock_self

    @pytest.fixture
    def mock_input_files(self):
        """Fixture for mock input file list."""
        return [{"path": "/fake/input/file1.bin", "display_name": "file1.bin"}]

    @pytest.fixture
    def mock_output_path(self):
        """Fixture for a mock output path."""
        return "/fake/output/dir"

    @pytest.fixture
    def mock_workflow_id(self):
        """Fixture for a mock workflow ID."""
        return "fake-workflow-123"

    @pytest.fixture
    def mock_task_config(self):
        """Fixture for a mock task config."""
        return {}  # Default empty config

    @pytest.fixture
    def mock_output_file_obj(self, mocker):
        """Fixture for a mock output file object returned by create_output_file."""
        mock_obj = MagicMock()
        mock_obj.path = "/fake/output/dir/output_file.strings"
        mock_obj.to_dict.return_value = {
            "path": mock_obj.path,
            "display_name": "file1.bin.strings",
            "extension": "strings",
            "data_type": "openrelik:floss:strings",
        }
        return mock_obj

    @pytest.fixture
    def mock_process(self, mocker):
        """Fixture for a mock subprocess.Popen return value."""
        mock_proc = MagicMock()
        # Simulate the process running for a few polls, then finishing
        mock_proc.poll.side_effect = [None, None, 0]  # Poll returns None twice, then 0
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read().decode.return_value = ""  # No stderr output
        return mock_proc

    @pytest.fixture
    def mock_open_file_handle(self, mocker):
        """Fixture for a mock file handle returned by open."""
        mock_fh = MagicMock()
        # We don't necessarily need to mock write on the handle itself
        # as subprocess.Popen writes to it directly.
        return mock_fh

    @pytest.fixture(autouse=True)
    def patch_dependencies(
        self, mocker, mock_output_file_obj, mock_open_file_handle
    ):  # Removed mock_process from parameters
        """Patch external dependencies."""
        mocker.patch("src.tasks.get_input_files")
        mocker.patch(
            "src.tasks.create_output_file",
            return_value=mock_output_file_obj,
        )
        mocker.patch("src.tasks.count_file_lines")  # Patch where it's used
        mocker.patch("src.tasks.create_task_result")  # Patch where it's used
        # Removed the incorrect patch using mock_process here

        def mock_process_factory(*args, **kwargs):
            # Creates a new mock process for each call to Popen
            proc = MagicMock()
            proc.poll.side_effect = [None, None, 0]  # Fresh iterator for poll
            proc.stderr = MagicMock()
            proc.stderr.read().decode.return_value = ""  # Default no stderr
            return proc

        mocker.patch("subprocess.Popen", side_effect=mock_process_factory)
        # Patch open to return our mock file handle when called with the output path
        mocker.patch("builtins.open", return_value=mock_open_file_handle)
        mocker.patch("time.sleep")  # Prevent actual sleeping

    def test_successful_run_with_pipe_result(
        self,
        mocker,
        mock_celery_self,
        mock_input_files,  # Even if empty list passed to command, get_input_files is mocked to return this
        mock_output_path,
        mock_workflow_id,
        mock_task_config,
        # mock_output_file_obj and mock_open_file_handle are patched by autouse fixture
    ):
        """Tests successful execution with pipe_result."""
        # Patch send_event on the actual command task object
        mocker.patch.object(command, "send_event", new=mock_celery_self.send_event)

        mock_pipe_result = "fake_base64_data"
        # Fixtures are now parameters

        # Configure mocks for this specific test case
        mocker.patch(
            "src.tasks.get_input_files",
            return_value=mock_input_files,
        )
        mocker.patch(
            "src.tasks.count_file_lines",
            side_effect=[
                10,
                25,
                50,
            ],  # For 1 file: 2 calls in loop + 1 final check = 3 calls.
        )
        mock_task_result = {"status": "success", "output_files": []}
        mocker.patch(
            "src.tasks.create_task_result",
            return_value=mock_task_result,
        )

        # Call the function
        result = command(
            pipe_result=mock_pipe_result,
            input_files=[],  # Should be ignored if pipe_result is present
            output_path=mock_output_path,
            workflow_id=mock_workflow_id,
            task_config=mock_task_config,
        )

        # Assertions
        src.tasks.get_input_files.assert_called_once_with(mock_pipe_result, [])

        # Rest of assertions are similar to test_successful_run_with_input_files
        assert src.tasks.create_output_file.call_count == len(mock_input_files)
        assert subprocess.Popen.call_count == len(mock_input_files)
        assert builtins.open.call_count == len(mock_input_files)

        src.tasks.create_task_result.assert_called_once_with(
            output_files=mocker.ANY,  # Check content in detail if needed
            workflow_id=mock_workflow_id,
            command="floss -q",
            meta={},
        )
        assert result == mock_task_result

    def test_run_with_min_length_config(
        self,
        mocker,
        mock_celery_self,
        mock_input_files,
        mock_output_path,
        mock_workflow_id,
        mock_open_file_handle,  # For Popen assertion
    ):
        """Tests execution with min_length task config."""
        # Patch send_event on the actual command task object
        mocker.patch.object(command, "send_event", new=mock_celery_self.send_event)

        mock_task_config = {"min_length": "10"}
        # Fixtures are now parameters

        # get_input_files is patched by autouse fixture, but we need to ensure it returns our mock_input_files
        mocker.patch(
            "src.tasks.get_input_files",
            return_value=mock_input_files,
        )
        mocker.patch("src.tasks.count_file_lines", return_value=50)
        mocker.patch("src.tasks.create_task_result", return_value={})

        # Call the function
        command(
            pipe_result=None,
            input_files=mock_input_files,
            output_path=mock_output_path,
            workflow_id=mock_workflow_id,
            task_config=mock_task_config,
        )

        # Assert subprocess.Popen was called with the correct command
        subprocess.Popen.assert_called_once_with(
            ["floss", "-q", "-n", "10", mock_input_files[0]["path"]],
            stdout=mock_open_file_handle.__enter__(),
            stderr=subprocess.PIPE,
        )

        # Assert create_task_result was called with the correct command string
        src.tasks.create_task_result.assert_called_once_with(
            output_files=mocker.ANY,
            workflow_id=mock_workflow_id,
            command="floss -q -n 10",
            meta={},
        )

    def test_subprocess_error(
        self,
        mocker,
        mock_celery_self,
        mock_input_files,
        mock_output_path,
        mock_workflow_id,
        mock_task_config,
        mock_process,  # For re-patching Popen
    ):
        """Tests handling of subprocess stderr."""
        # Patch send_event on the actual command task object
        mocker.patch.object(command, "send_event", new=mock_celery_self.send_event)

        mock_error_message = "FLOSS failed!"
        # Fixtures are now parameters

        # Configure mock process to return an error on stderr
        mock_process.poll.side_effect = [None, 1]  # Process fails after one poll
        mock_process.stderr.read().decode.return_value = mock_error_message
        mocker.patch(
            "subprocess.Popen", return_value=mock_process
        )  # Patch Popen with this specific mock

        mocker.patch(
            "src.tasks.get_input_files",
            return_value=mock_input_files,
        )
        mocker.patch(
            "src.tasks.count_file_lines", return_value=10
        )  # Doesn't matter much here
        mocker.patch("src.tasks.create_task_result")  # Should not be called

        # Call the function and assert it raises RuntimeError
        with pytest.raises(RuntimeError, match=mock_error_message):
            command(
                pipe_result=None,
                input_files=mock_input_files,
                output_path=mock_output_path,
                workflow_id=mock_workflow_id,
                task_config=mock_task_config,
            )

        # Assert create_task_result was NOT called
        src.tasks.create_task_result.assert_not_called()

    def test_no_output_files_error(
        self,
        mocker,
        mock_celery_self,
        mock_output_path,
        mock_workflow_id,
        mock_task_config,
    ):
        """Tests handling the case where no output files are generated (e.g., no input files)."""
        # Patch send_event on the actual command task object (though likely not called)
        mocker.patch.object(command, "send_event", new=mock_celery_self.send_event)

        # Fixtures are now parameters
        # Configure get_input_files to return an empty list
        mocker.patch("src.tasks.get_input_files", return_value=[])
        mocker.patch("src.tasks.create_output_file")  # Should not be called
        mocker.patch("src.tasks.count_file_lines")  # Should not be called
        mocker.patch("src.tasks.create_task_result")  # Should not be called
        mocker.patch("subprocess.Popen")  # Should not be called

        # Call the function and assert it raises RuntimeError
        with pytest.raises(
            RuntimeError, match="FLOSS found no strings."
        ):  # The error message is the same
            command(
                pipe_result=None,
                input_files=[],
                output_path=mock_output_path,
                workflow_id=mock_workflow_id,
                task_config=mock_task_config,
            )

        # Assert dependencies were NOT called
        src.tasks.create_output_file.assert_not_called()
        src.tasks.count_file_lines.assert_not_called()
        src.tasks.create_task_result.assert_not_called()
        subprocess.Popen.assert_not_called()
