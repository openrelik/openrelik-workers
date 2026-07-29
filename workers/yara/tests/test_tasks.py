import json
import os
import pytest
import shutil
from unittest.mock import MagicMock, patch
from src.tasks import (
    on_task_prerun,
    safe_list_get,
    generate_report_from_matches,
    YaraMatch,
)
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
    with (
        patch("os.path.isfile", return_value=False),
        patch("os.path.isdir", return_value=False),
    ):
        task_config = {"Global Yara rules": "/non/existent/path"}
        with pytest.raises(ValueError, match="No Yara rules were collected"):
            command.run(
                None,
                task_config=task_config,
                input_files=[],
                output_path="/tmp",
            )


def test_on_task_prerun():
    task = MagicMock()
    task.name = "test_task"
    with patch("src.tasks.log_root.bind") as mock_bind:
        on_task_prerun(None, "task123", task, None, None)
        mock_bind.assert_called_with(
            task_id="task123", task_name="test_task", worker_name="Yara scan"
        )


def test_safe_list_get():
    test_list = [1, 2, 3]
    assert safe_list_get(test_list, 1, 99) == 2
    assert safe_list_get(test_list, 5, 99) == 99


def test_generate_report_from_matches():
    matches = [
        YaraMatch(
            filepath="file1.txt",
            hash="hash1",
            rule="rule1",
            desc="desc1",
            ref="ref1",
            score=100,
        )
    ]
    report = generate_report_from_matches(matches)
    report_dict = report.to_dict()
    assert report_dict.get("title") == "Yara scan report"


@patch("src.tasks.command.send_event")
@patch("subprocess.run")
@patch("src.tasks.create_task_result")
@patch("src.tasks.create_output_file")
@patch("src.tasks.is_disk_image")
def test_command_success(
    mock_is_disk_image,
    mock_create_output_file,
    mock_create_task_result,
    mock_run,
    mock_send_event,
    tmp_path,
):
    mock_is_disk_image.return_value = False

    # Setup mock for create_output_file
    def side_effect_create_output_file(output_path, display_name, **kwargs):
        mock_file = MagicMock()
        mock_file.path = str(tmp_path / display_name)
        mock_file.to_dict.return_value = {"path": mock_file.path}
        # pre-create the fraken output with mock data to avoid file not found
        if display_name == "fraken_out.jsonl":
            with open(mock_file.path, "w") as f:
                f.write(
                    '[{"ImagePath": "file1.txt", "SHA256": "hash", "Signature": "rule", "Description": "desc", "Reference": "ref", "Score": 100}]\n'
                )
        return mock_file

    mock_create_output_file.side_effect = side_effect_create_output_file

    # Setup mock run
    mock_result = MagicMock()
    mock_result.stdout = b'[{"ImagePath": "file1.txt", "SHA256": "hash", "Signature": "rule", "Description": "desc", "Reference": "ref", "Score": 100}]\n'
    mock_result.stderr = b""
    mock_run.return_value = mock_result

    mock_create_task_result.return_value = "mock_result"

    # Create fake yara rule
    yara_rule_file = tmp_path / "test.yar"
    yara_rule_file.write_text("rule test {}")

    task_config = {"Global Yara rules": str(yara_rule_file), "mount_disk_images": False}

    input_files = [
        {"path": str(tmp_path / "test_input.txt"), "display_name": "test_input.txt"}
    ]

    result = command.run(
        None,
        input_files=input_files,
        output_path=str(tmp_path),
        workflow_id="workflow123",
        task_config=task_config,
    )

    assert result == "mock_result"
    mock_run.assert_called_once()
    mock_create_task_result.assert_called_once()


@patch("src.tasks.command.send_event")
@patch("subprocess.run")
@patch("src.tasks.create_task_result")
@patch("src.tasks.create_output_file")
@patch("src.tasks.BlockDevice")
@patch("src.tasks.is_disk_image")
def test_command_with_disk_image(
    mock_is_disk_image,
    mock_block_device,
    mock_create_output_file,
    mock_create_task_result,
    mock_run,
    mock_send_event,
    tmp_path,
):
    mock_is_disk_image.return_value = True

    # Setup mock for create_output_file
    def side_effect_create_output_file(output_path, display_name, **kwargs):
        mock_file = MagicMock()
        mock_file.path = str(tmp_path / display_name)
        mock_file.to_dict.return_value = {"path": mock_file.path}
        if display_name == "fraken_out.jsonl":
            with open(mock_file.path, "w") as f:
                f.write("[]\n")
        return mock_file

    mock_create_output_file.side_effect = side_effect_create_output_file

    # Setup mock BlockDevice
    mock_bd_instance = MagicMock()
    mock_bd_instance.mount.return_value = [str(tmp_path / "mount1")]
    mock_block_device.return_value = mock_bd_instance

    # Setup mock run
    mock_result = MagicMock()
    mock_result.stdout = b"[]\n"
    mock_result.stderr = b""
    mock_run.return_value = mock_result

    mock_create_task_result.return_value = "mock_result"

    task_config = {"Manual Yara rules": "rule test {}", "mount_disk_images": True}

    input_files = [{"path": str(tmp_path / "disk.img"), "display_name": "disk.img"}]

    with patch("os.getenv", return_value=""):
        result = command.run(
            None,
            input_files=input_files,
            output_path=str(tmp_path),
            workflow_id="workflow123",
            task_config=task_config,
        )

    assert result == "mock_result"
    mock_block_device.assert_called_once()
    mock_bd_instance.mount.assert_called_once()
    mock_bd_instance.umount.assert_called_once()


()
