import base64
import json
import os
import pytest
import shutil
from types import SimpleNamespace
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
    ), patch.object(command, "send_event"):

        task_config = {"Global Yara rules": "/non/existent/path"}
        with pytest.raises(ValueError, match="No Yara rules were collected"):
            command.run(
                None,
                task_config=task_config,
                input_files=[],
                output_path="/tmp",
            )


def test_command_fails_without_input_files(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')

    with patch.dict(os.environ, {}, clear=True), patch.object(command, "send_event"):
        with pytest.raises(RuntimeError, match="No input files"):
            command.run(
                None,
                task_config={"Global Yara rules": str(rule_file)},
                input_files=[],
                output_path=str(tmp_path),
            )


def test_command_refuses_root_input_path(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')

    with patch.dict(os.environ, {}, clear=True), patch.object(command, "send_event"):
        with pytest.raises(RuntimeError, match="Refusing to scan filesystem root"):
            command.run(
                None,
                task_config={"Global Yara rules": str(rule_file)},
                input_files=[{"path": "/", "display_name": "root"}],
                output_path=str(tmp_path),
            )


def _mock_output_file(path):
    output_file = MagicMock()
    output_file.path = str(path)
    output_file.to_dict.return_value = {"path": str(path)}
    return output_file


def test_command_writes_fraken_stderr_to_log_file(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')
    input_file = tmp_path / "input.txt"
    input_file.write_text("test")

    all_yara = _mock_output_file(tmp_path / "all.yara")
    fraken_output = _mock_output_file(tmp_path / "fraken_out.jsonl")
    fraken_stderr = _mock_output_file(tmp_path / "fraken_stderr.log")
    report_file = _mock_output_file(tmp_path / "yara-scan-report.md")

    with patch.dict(os.environ, {}, clear=True), patch(
        "src.tasks.create_output_file",
        side_effect=[all_yara, fraken_output, fraken_stderr, report_file],
    ), patch(
        "src.tasks.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ) as mock_run, patch.object(command, "send_event") as mock_send_event:
        result = command.run(
            None,
            task_config={"Global Yara rules": str(rule_file)},
            input_files=[
                {"path": str(input_file), "display_name": input_file.name},
            ],
            output_path=str(tmp_path),
        )

    _, kwargs = mock_run.call_args
    assert kwargs["stderr"].name == str(fraken_stderr.path)
    assert kwargs["stdout"].name == str(fraken_output.path)
    assert kwargs["stderr"].name != kwargs["stdout"].name
    decoded_result = json.loads(base64.b64decode(result).decode("utf-8"))
    assert decoded_result["output_files"] == [
        fraken_output.to_dict.return_value,
        report_file.to_dict.return_value,
    ]
    assert decoded_result["task_files"] == [fraken_stderr.to_dict.return_value]
    statuses = [
        call.kwargs["data"]["status"]
        for call in mock_send_event.call_args_list
        if "data" in call.kwargs
    ]
    assert statuses == ["Running Yara scan"]


def test_command_reports_fraken_failure_without_stderr_tail(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')
    input_file = tmp_path / "input.txt"
    input_file.write_text("test")

    all_yara = _mock_output_file(tmp_path / "all.yara")
    fraken_output = _mock_output_file(tmp_path / "fraken_out.jsonl")
    fraken_stderr = _mock_output_file(tmp_path / "fraken_stderr.log")

    def _run_with_stderr(*_, **kwargs):
        kwargs["stderr"].write("fraken exploded\n")
        return SimpleNamespace(returncode=2)

    with patch.dict(os.environ, {}, clear=True), patch(
        "src.tasks.create_output_file",
        side_effect=[all_yara, fraken_output, fraken_stderr],
    ), patch("src.tasks.subprocess.run", side_effect=_run_with_stderr), patch.object(
        command, "send_event"
    ):
        with pytest.raises(RuntimeError) as e:
            command.run(
                None,
                task_config={"Global Yara rules": str(rule_file)},
                input_files=[
                    {"path": str(input_file), "display_name": input_file.name},
                ],
                output_path=str(tmp_path),
            )

    assert "An error occurred while running fraken-x" in str(e.value)
    assert str(fraken_stderr.path) in str(e.value)
    assert "fraken exploded" not in str(e.value)
    with open(fraken_stderr.path, encoding="utf-8") as fh:
        assert fh.read() == "fraken exploded\n"


def test_command_rejects_disk_image_without_mount_disk_images(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')
    input_file = tmp_path / "disk.E01"
    input_file.write_text("disk")

    all_yara = _mock_output_file(tmp_path / "all.yara")
    fraken_output = _mock_output_file(tmp_path / "fraken_out.jsonl")
    fraken_stderr = _mock_output_file(tmp_path / "fraken_stderr.log")

    with patch.dict(os.environ, {}, clear=True), patch(
        "src.tasks.create_output_file",
        side_effect=[all_yara, fraken_output, fraken_stderr],
    ), patch("src.tasks.is_disk_image", return_value=True), patch(
        "src.tasks.subprocess.run"
    ) as mock_run, patch.object(command, "send_event"):
        with pytest.raises(RuntimeError, match="not supported in regular scan mode"):
            command.run(
                None,
                task_config={"Global Yara rules": str(rule_file)},
                input_files=[
                    {"path": str(input_file), "display_name": input_file.name},
                ],
                output_path=str(tmp_path),
            )

    mock_run.assert_not_called()


def test_command_skips_disk_image_without_mount_and_scans_other_inputs(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')
    disk_file = tmp_path / "disk.E01"
    disk_file.write_text("disk")
    regular_file = tmp_path / "input.txt"
    regular_file.write_text("test")

    all_yara = _mock_output_file(tmp_path / "all.yara")
    fraken_output = _mock_output_file(tmp_path / "fraken_out.jsonl")
    fraken_stderr = _mock_output_file(tmp_path / "fraken_stderr.log")
    report_file = _mock_output_file(tmp_path / "yara-scan-report.md")

    def _is_disk_image(input_file):
        return input_file["path"] == str(disk_file)

    with patch.dict(os.environ, {}, clear=True), patch(
        "src.tasks.create_output_file",
        side_effect=[all_yara, fraken_output, fraken_stderr, report_file],
    ), patch("src.tasks.is_disk_image", side_effect=_is_disk_image), patch(
        "src.tasks.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ) as mock_run, patch("src.tasks.logger") as mock_logger, patch.object(
        command, "send_event"
    ):
        result = command.run(
            None,
            task_config={"Global Yara rules": str(rule_file)},
            input_files=[
                {"path": str(disk_file), "display_name": disk_file.name},
                {"path": str(regular_file), "display_name": regular_file.name},
            ],
            output_path=str(tmp_path),
        )

    assert any(
        "Disk image input is not supported in regular scan mode" in str(call)
        for call in mock_logger.error.call_args_list
    )
    assert mock_run.call_args.args[0] == [
        "fraken",
        "--folder",
        str(regular_file),
        str(all_yara.path),
    ]
    with open(report_file.path, encoding="utf-8") as fh:
        report_content = fh.read()
    assert "Skipped inputs" in report_content
    assert disk_file.name in report_content
    assert "Disk image input is not supported in regular scan mode" in report_content

    decoded_result = json.loads(base64.b64decode(result).decode("utf-8"))
    task_report = decoded_result["task_report"]
    assert "1 input(s) skipped" in task_report["summary"]
    assert "Skipped inputs" in task_report["content"]


def test_command_mounts_disk_image_before_scanning(tmp_path):
    rule_file = tmp_path / "rule.yara"
    rule_file.write_text('rule test { strings: $ = "test" condition: true }')
    input_file = tmp_path / "disk.img"
    input_file.write_text("disk")
    mountpoint = tmp_path / "mounted-partition"
    mountpoint.mkdir()

    all_yara = _mock_output_file(tmp_path / "all.yara")
    fraken_output = _mock_output_file(tmp_path / "fraken_out.jsonl")
    fraken_stderr = _mock_output_file(tmp_path / "fraken_stderr.log")
    report_file = _mock_output_file(tmp_path / "yara-scan-report.md")
    block_device = MagicMock()
    block_device.mount.return_value = [str(mountpoint)]

    with patch.dict(os.environ, {}, clear=True), patch(
        "src.tasks.create_output_file",
        side_effect=[all_yara, fraken_output, fraken_stderr, report_file],
    ), patch("src.tasks.is_disk_image", return_value=True), patch(
        "src.tasks.BlockDevice", return_value=block_device
    ) as mock_block_device, patch(
        "src.tasks.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ) as mock_run, patch.object(
        command, "send_event"
    ):
        command.run(
            None,
            task_config={
                "Global Yara rules": str(rule_file),
                "mount_disk_images": True,
            },
            input_files=[
                {
                    "path": str(input_file),
                    "display_name": input_file.name,
                },
            ],
            output_path=str(tmp_path),
        )

    mock_block_device.assert_called_once_with(str(input_file), min_partition_size=1)
    block_device.setup.assert_called_once_with()
    block_device.mount.assert_called_once_with()
    block_device.umount.assert_called_once_with()
    assert mock_run.call_args.args[0] == [
        "fraken",
        "--folder",
        str(mountpoint),
        str(all_yara.path),
    ]
