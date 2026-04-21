import json
import os
import pytest
import shutil
from unittest.mock import MagicMock, patch, mock_open
from src.tasks import cleanup_fraken_output_log, command


@pytest.fixture
def mock_logfile(tmp_path):
    """
    Copies the real test data to a temp directory to protect the source file
    from the function's overwrite.
    """
    source_file = "test_data/fraken_out.jsonl"
    temp_file = tmp_path / "fraken_out_temp.jsonl"

    shutil.copy(source_file, temp_file)

    logfile = MagicMock()
    logfile.path = str(temp_file)
    return logfile


@pytest.fixture
def mock_logger():
    """Patches the logger specifically in the src.tasks module."""
    with patch("src.tasks.logger") as mock:
        yield mock


def test_cleanup_successful(mock_logfile):
    """Verifies that the file is correctly flattened and written."""
    cleanup_fraken_output_log(mock_logfile)

    with open(mock_logfile.path, "r") as f:
        lines = f.readlines()

    # Verify the first entry's content
    assert (
        "2aab6dc411baf0605a1b284128323709e38b0f1d147d09cfbc24997acb9527eb" in lines[0]
    )
    # Verify it is no longer wrapped in a list (starts with { not [)
    assert lines[0].startswith("[{")


def test_cleanup_file_not_found(mock_logger):
    """Verifies error handling when the path is invalid."""
    logfile = MagicMock()
    logfile.path = "non_existent.jsonl"

    cleanup_fraken_output_log(logfile)

    mock_logger.warning.assert_called_with("Could not find fraken-x outputfile.")


def test_cleanup_corrupt_json(mock_logfile, mock_logger):
    """Verifies that bad JSON lines are logged and skipped."""
    with open(mock_logfile.path, "a") as f:
        f.write("invalid json line\n")

    cleanup_fraken_output_log(mock_logfile)

    assert mock_logger.warning.called
    assert any(
        "could not parse" in str(call) for call in mock_logger.warning.call_args_list
    )


def test_cleanup_no_valid_data(tmp_path):
    """Verifies that if only empty lists exist, the returned file is empty."""
    # Create a file with only empty lists
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("[]\n[]\n")

    logfile = MagicMock()
    logfile.path = str(empty_file)

    cleanup_fraken_output_log(logfile)

    assert empty_file.read_text() == "[]"


def test_final_output_is_valid_json_array(mock_logfile):
    """
    Verifies the output is a single valid JSON array that can be
    loaded entirely using json.load().
    """
    cleanup_fraken_output_log(mock_logfile)

    with open(mock_logfile.path, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Failed to load output file as a single JSON object: {e}")

    assert isinstance(data, list), "Output should be a JSON array (list)."
    assert len(data) == 2, "Should contain exactly two extracted entries."
    assert data[0]["ImagePath"].endswith("test_input.txt")


def test_command_no_rules_provided():
    """Test that RuntimeError is raised when no rules are provided in config or env."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(
            RuntimeError,
            match="At least one of Environment, Global or Manual Yara rules must be provided",
        ):
            command.run(None, task_config={}, input_files=[], output_path="/tmp")


def test_command_empty_rules_collected():
    """Test that ValueError is raised when rules are provided but none are successfully read."""
    # Mock os.path.isfile and os.path.isdir to return False for everything
    with patch("os.path.isfile", return_value=False), patch(
        "os.path.isdir", return_value=False
    ):

        task_config = {"Global Yara rules": "/non/existent/path"}
        with pytest.raises(ValueError, match="No Yara rules were collected"):
            command.run(
                None,
                task_config=task_config,
                input_files=[],
                output_path="/tmp",
            )
