"""tests for log2timeline."""

import ast
import base64
import json
import os
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock
import pytest

from openrelik_worker_common import task_utils

LOG2TIMELINE_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "log2timeline.py"
)

# ---------------------------------------------------------------------------
# Stub heavy dependencies (plaso, openrelik_common, src.app) if not present,
# so tests run cleanly both in full container environments and lightweight CI.
# ---------------------------------------------------------------------------

if "plaso" not in sys.modules:
    plaso_pkg = types.ModuleType("plaso")
    sys.modules["plaso"] = plaso_pkg
else:
    plaso_pkg = sys.modules["plaso"]

if not hasattr(plaso_pkg, "__version__"):
    plaso_pkg.__version__ = "20240308"

if "plaso.output" not in sys.modules:
    plaso_output_pkg = types.ModuleType("plaso.output")
    plaso_output_manager = types.ModuleType("plaso.output.manager")

    class _FakeOutputManager:
        @staticmethod
        def GetOutputClasses():
            return [("csv", None), ("jsonl", None), ("l2tcsv", None)]

    plaso_output_manager.OutputManager = _FakeOutputManager
    plaso_output_pkg.manager = plaso_output_manager
    plaso_pkg.output = plaso_output_pkg
    sys.modules["plaso.output"] = plaso_output_pkg
    sys.modules["plaso.output.manager"] = plaso_output_manager

if "plaso.cli" not in sys.modules:
    plaso_cli_pkg = types.ModuleType("plaso.cli")
    sys.modules["plaso.cli"] = plaso_cli_pkg
else:
    plaso_cli_pkg = sys.modules["plaso.cli"]
plaso_pkg.cli = plaso_cli_pkg

if "plaso.cli.pinfo_tool" not in sys.modules:
    plaso_pinfo_tool = types.ModuleType("plaso.cli.pinfo_tool")

    class _FakePinfoTool:
        def _GetStorageReader(self, name):
            reader = MagicMock()
            reader.GetFormatVersion.return_value = 20230327
            return reader

        def _CalculateStorageCounters(self, reader):
            return {"parsers": {"filestat": 42}}

    plaso_pinfo_tool.PinfoTool = _FakePinfoTool
    sys.modules["plaso.cli.pinfo_tool"] = plaso_pinfo_tool
plaso_cli_pkg.pinfo_tool = sys.modules["plaso.cli.pinfo_tool"]

if "plaso.cli.extraction_tool" not in sys.modules:
    plaso_extraction_tool = types.ModuleType("plaso.cli.extraction_tool")

    class _FakeExtractionTool:
        _SUPPORTED_ARCHIVE_TYPES = {"zip": None, "tar": None}

    plaso_extraction_tool.ExtractionTool = _FakeExtractionTool
    sys.modules["plaso.cli.extraction_tool"] = plaso_extraction_tool
plaso_cli_pkg.extraction_tool = sys.modules["plaso.cli.extraction_tool"]

if "plaso.parsers" not in sys.modules:
    plaso_parsers_pkg = types.ModuleType("plaso.parsers")
    sys.modules["plaso.parsers"] = plaso_parsers_pkg
else:
    plaso_parsers_pkg = sys.modules["plaso.parsers"]
plaso_pkg.parsers = plaso_parsers_pkg

if "plaso.parsers.manager" not in sys.modules:
    plaso_parsers_manager = types.ModuleType("plaso.parsers.manager")

    class _FakeParsersManager:
        def GetParsersInformation(self):
            return [("winreg", "Windows Registry")]

        def GetNamesOfParsersWithPlugins(self):
            return ["winreg"]

        def GetParserPluginsInformation(self, parser_filter_expression=None):
            return [("appcompat", "AppCompatCache")]

    plaso_parsers_manager.ParsersManager = _FakeParsersManager
    sys.modules["plaso.parsers.manager"] = plaso_parsers_manager
plaso_parsers_pkg.manager = sys.modules["plaso.parsers.manager"]

if "openrelik_common" not in sys.modules:
    openrelik_common_pkg = types.ModuleType("openrelik_common")
    telemetry_mod = types.ModuleType("openrelik_common.telemetry")
    telemetry_mod.add_attribute_to_current_span = lambda *a, **k: None
    logging_mod = types.ModuleType("openrelik_common.logging")

    class _FakeLogger:
        def get_logger(self, *a, **k):
            return MagicMock()

        def bind(self, *a, **k):
            pass

    logging_mod.Logger = _FakeLogger
    openrelik_common_pkg.telemetry = telemetry_mod
    openrelik_common_pkg.logging = logging_mod
    sys.modules["openrelik_common"] = openrelik_common_pkg
    sys.modules["openrelik_common.telemetry"] = telemetry_mod
    sys.modules["openrelik_common.logging"] = logging_mod

if "src.app" not in sys.modules:
    app_mod = types.ModuleType("src.app")

    class _FakeCelery:
        def task(self, *dargs, **dkwargs):
            def deco(fn):
                return fn

            return deco

    app_mod.celery = _FakeCelery()
    sys.modules["src.app"] = app_mod

from src import log2timeline  # noqa: E402


def _decode(result_b64: str) -> dict:
    return json.loads(base64.b64decode(result_b64.encode("utf-8")).decode("utf-8"))


@pytest.fixture
def bound_task():
    """Mock the Celery task instance (self)."""
    task = MagicMock()
    task.send_event = MagicMock()
    return task


@pytest.fixture
def fake_subprocess(monkeypatch):
    """Patch subprocess.Popen so the task body runs without invoking log2timeline.py."""
    class _InvokedCommands(list):
        returncode = 0
        stdout = "log2timeline finished successfully\n"
        stderr = ""

    invoked = _InvokedCommands()

    class _FakeProcess:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self._returncode = returncode
            self.stdout = MagicMock()
            self.stdout.read.return_value = stdout
            self.stderr = MagicMock()
            self.stderr.read.return_value = stderr

        def poll(self):
            return self._returncode

    def fake_popen(cmd, *args, **kwargs):
        invoked.append(list(cmd))
        return _FakeProcess(
            returncode=invoked.returncode,
            stdout=invoked.stdout,
            stderr=invoked.stderr,
        )

    monkeypatch.setattr(log2timeline.subprocess, "Popen", fake_popen)
    return invoked


# ---------------------------------------------------------------------------
# AST and source-level verification tests
# ---------------------------------------------------------------------------

def _task_metadata_node():
    tree = ast.parse(LOG2TIMELINE_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TASK_METADATA":
                    return node.value
    raise AssertionError("TASK_METADATA assignment not found in log2timeline.py")


def test_register_in_db_switch_declared_in_task_metadata():
    """The user-facing switch must be wired into TASK_METADATA so the UI
    renders it as a configuration option."""
    metadata_dict = _task_metadata_node()
    assert isinstance(metadata_dict, ast.Dict)

    # Find the task_config list value.
    task_config_value = None
    for k, v in zip(metadata_dict.keys, metadata_dict.values):
        if isinstance(k, ast.Constant) and k.value == "task_config":
            task_config_value = v
            break
    assert task_config_value is not None, "task_config key missing from TASK_METADATA"
    assert isinstance(task_config_value, ast.List)

    names = []
    for entry in task_config_value.elts:
        assert isinstance(entry, ast.Dict)
        for k, v in zip(entry.keys, entry.values):
            if (
                isinstance(k, ast.Constant)
                and k.value == "name"
                and isinstance(v, ast.Constant)
            ):
                names.append(v.value)
    assert "register_in_db" in names, (
        "register_in_db switch missing from log2timeline TASK_METADATA"
    )


def test_register_in_db_threaded_through_to_create_output_file():
    """Both create_output_file calls in log2timeline must pass register_in_db
    so single-input and multi-input runs both honor the user's choice."""
    source = LOG2TIMELINE_PATH.read_text()
    storage_calls = source.count('data_type="plaso:log2timeline:plaso_storage"')
    register_passes = source.count("register_in_db=register_in_db")
    assert storage_calls >= 2, (
        "expected single-input and multi-input branches to both create the "
        "plaso storage OutputFile"
    )
    assert register_passes >= storage_calls, (
        "every plaso_storage create_output_file call must thread register_in_db"
    )


def test_single_input_threads_upstream_original_path():
    """Single-input runs must forward the upstream upload's original_path
    onto the .plaso OutputFile so downstream tasks like the S3 exporter can
    derive object keys from the user's uploaded filename rather than this
    worker's UUID-based on-disk name."""
    source = LOG2TIMELINE_PATH.read_text()
    assert 'original_path=upstream_original' in source, (
        "single-input branch must thread the upstream original_path "
        "into create_output_file"
    )
    assert (
        'input_files[0].get("original_path")' in source
        and 'input_files[0].get("path")' in source
    ), "single-input branch must derive upstream_original with a path fallback"


# ---------------------------------------------------------------------------
# Unit tests for _output_display_name helper function
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "config,expected",
    [
        (None, None),
        ({}, None),
        ({"output_file_name": None}, None),
        ({"output_file_name": ""}, None),
        ({"output_file_name": "   "}, None),
        ({"output_file_name": "evidence"}, "evidence.plaso"),
        ({"output_file_name": "evidence.raw"}, "evidence.plaso"),
        ({"output_file_name": "/var/log/syslog.log"}, "syslog.plaso"),
        ({"output_file_name": "  spaced_name  "}, "spaced_name.plaso"),
        ({"output_file_name": ["first_name", "second_name"]}, "first_name.plaso"),
        ({"output_file_name": []}, None),
        ({"output_file_name": "."}, None),
        ({"output_file_name": ".."}, None),
    ],
)
def test_output_display_name(config, expected):
    """Verify display name normalization, sanitization, and fallback."""
    assert log2timeline._output_display_name(config) == expected


# ---------------------------------------------------------------------------
# Functional unit tests for log2timeline task
# ---------------------------------------------------------------------------

def test_log2timeline_empty_input_files_skips(bound_task):
    """When input_files is empty, task must skip processing and return empty result."""
    raw = log2timeline.log2timeline(
        bound_task,
        pipe_result=None,
        input_files=[],
        output_path="/tmp",
        workflow_id="wf-empty",
        task_config=None,
    )
    result = _decode(raw)
    assert result["output_files"] == []
    assert result["workflow_id"] == "wf-empty"
    assert result["command"] == ""
    assert bound_task.send_event.call_count == 0


def test_log2timeline_none_input_files_skips(bound_task):
    """When input_files and pipe_result are None, task must skip processing."""
    raw = log2timeline.log2timeline(
        bound_task,
        pipe_result=None,
        input_files=None,
        output_path="/tmp",
        workflow_id="wf-none",
        task_config=None,
    )
    result = _decode(raw)
    assert result["output_files"] == []
    assert result["workflow_id"] == "wf-none"
    assert result["command"] == ""
    assert bound_task.send_event.call_count == 0


def test_log2timeline_pipe_result_with_empty_files_skips(bound_task):
    """When pipe_result contains no output files, task skips processing."""
    pipe_input = task_utils.encode_dict_to_base64({"output_files": []})
    raw = log2timeline.log2timeline(
        bound_task,
        pipe_result=pipe_input,
        input_files=None,
        output_path="/tmp",
        workflow_id="wf-pipe-empty",
        task_config=None,
    )
    result = _decode(raw)
    assert result["output_files"] == []
    assert result["workflow_id"] == "wf-pipe-empty"
    assert result["command"] == ""


def test_log2timeline_single_input_default(tmp_path, fake_subprocess, bound_task):
    """Single input file runs log2timeline with default settings."""
    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]

    raw = log2timeline.log2timeline(
        bound_task,
        pipe_result=None,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-single",
        task_config=None,
    )

    assert len(fake_subprocess) == 1
    cmd = fake_subprocess[0]
    assert cmd[0] == "log2timeline.py"
    assert "--quiet" in cmd
    assert "--unattended" in cmd
    assert "--partitions" in cmd and cmd[cmd.index("--partitions") + 1] == "all"
    assert "--volumes" in cmd and cmd[cmd.index("--volumes") + 1] == "all"
    assert "--status-view" in cmd and cmd[cmd.index("--status-view") + 1] == "file"
    assert "--status-view-file" in cmd
    assert "--storage-file" in cmd
    assert cmd[-1] == "/in/disk.raw"

    result = _decode(raw)
    assert len(result["output_files"]) == 1
    output = result["output_files"][0]
    assert output["display_name"] == "disk.raw.plaso"
    assert output["data_type"] == "plaso:log2timeline:plaso_storage"
    assert output["original_path"] == "/in/disk.raw"
    assert output["register_in_db"] is True
    assert os.path.exists(output["path"])

    assert result["meta"]["plaso_version"] == "20240308"
    assert result["meta"]["plaso_storage_version"] == "20230327"
    assert result["meta"]["event_counters"] == {"filestat": 42}
    bound_task.send_event.assert_any_call("task-progress", data={})


def test_log2timeline_single_input_threads_upstream_original_path(
    tmp_path, fake_subprocess, bound_task
):
    """When input has original_path, it must be forwarded to the output file."""
    inputs = [
        {
            "path": "/in/disk.raw",
            "display_name": "disk.raw",
            "original_path": "/uploads/user_evidence.dd",
        }
    ]

    raw = log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-orig",
        task_config=None,
    )

    result = _decode(raw)
    assert result["output_files"][0]["original_path"] == "/uploads/user_evidence.dd"


def test_log2timeline_configured_display_name(tmp_path, fake_subprocess, bound_task):
    """User-configured output_file_name overrides default display_name."""
    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]

    raw = log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-custom-name",
        task_config={"output_file_name": "custom_case"},
    )

    result = _decode(raw)
    assert result["output_files"][0]["display_name"] == "custom_case.plaso"


def test_log2timeline_register_in_db_false(tmp_path, fake_subprocess, bound_task):
    """register_in_db=False propagates to output file."""
    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]

    raw = log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-no-db",
        task_config={"register_in_db": False},
    )

    result = _decode(raw)
    assert result["output_files"][0]["register_in_db"] is False


def test_log2timeline_command_options(tmp_path, fake_subprocess, bound_task):
    """Verify artifacts, parsers, and archives flags are added to command."""
    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]
    task_config = {
        "artifacts": ["BrowserHistory", "WindowsRegistry"],
        "parsers": ["winreg", "appcompat"],
        "archives": ["zip", "tar"],
    }

    log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-flags",
        task_config=task_config,
    )

    cmd = fake_subprocess[0]
    assert "--artifact_filters" in cmd
    assert cmd[cmd.index("--artifact_filters") + 1] == "BrowserHistory,WindowsRegistry"
    assert "--parsers" in cmd
    assert cmd[cmd.index("--parsers") + 1] == "winreg,appcompat"
    assert "--archives" in cmd
    assert cmd[cmd.index("--archives") + 1] == "zip,tar"


def test_log2timeline_yara_rules(tmp_path, fake_subprocess, bound_task):
    """Yara rules are written to an output file and passed via --yara_rules."""
    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]
    yara_rule_text = "rule TestRule { condition: true }"

    log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-yara",
        task_config={"Yara rules": yara_rule_text},
    )

    cmd = fake_subprocess[0]
    assert "--yara_rules" in cmd
    yara_path = cmd[cmd.index("--yara_rules") + 1]
    assert os.path.exists(yara_path)
    with open(yara_path, "r") as fh:
        assert fh.read() == yara_rule_text


def test_log2timeline_multiple_inputs_non_ewf(tmp_path, fake_subprocess, bound_task):
    """Multiple non-EWF input files are hardlinked to a temp directory."""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    f1 = in_dir / "evidence_part1.raw"
    f2 = in_dir / "evidence_part2.raw"
    f1.write_text("part1")
    f2.write_text("part2")

    inputs = [
        {"path": str(f1), "display_name": "evidence_part1.raw"},
        {"path": str(f2), "display_name": "evidence_part2.raw"},
    ]

    raw = log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-multi",
        task_config=None,
    )

    cmd = fake_subprocess[0]
    temp_dir = cmd[-1]
    assert temp_dir != str(f1)
    # The temporary directory must be cleaned up after execution.
    assert not os.path.exists(temp_dir)

    result = _decode(raw)
    assert len(result["output_files"]) == 1
    # Multiple inputs without output_file_name creates extension="plaso" OutputFile.
    assert result["output_files"][0]["extension"] == ".plaso"
    assert result["output_files"][0]["original_path"] is None


def test_log2timeline_multiple_inputs_ewf(tmp_path, fake_subprocess, bound_task):
    """Multiple EWF files are hardlinked with a common base name and .e01 passed to command."""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    e01 = in_dir / "disk.E01"
    e02 = in_dir / "disk.E02"
    e01.write_text("e01 data")
    e02.write_text("e02 data")

    inputs = [
        {"path": str(e01), "display_name": "disk.E01"},
        {"path": str(e02), "display_name": "disk.E02"},
    ]

    raw = log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-ewf",
        task_config=None,
    )

    cmd = fake_subprocess[0]
    target_e01 = cmd[-1]
    assert target_e01.endswith(".e01")
    temp_dir = os.path.dirname(target_e01)
    # Temp dir cleaned up after execution.
    assert not os.path.exists(temp_dir)

    result = _decode(raw)
    assert len(result["output_files"]) == 1


def test_log2timeline_multiple_inputs_ewf_missing_e01_raises(
    tmp_path, fake_subprocess, bound_task
):
    """If EWF segment set is missing an E01 file, a RuntimeError is raised."""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    e02 = in_dir / "disk.E02"
    e03 = in_dir / "disk.E03"
    e02.write_text("e02 data")
    e03.write_text("e03 data")

    inputs = [
        {"path": str(e02), "display_name": "disk.E02"},
        {"path": str(e03), "display_name": "disk.E03"},
    ]

    with pytest.raises(RuntimeError, match="Expected EWF file .* does not exist"):
        log2timeline.log2timeline(
            bound_task,
            input_files=inputs,
            output_path=str(tmp_path),
            workflow_id="wf-ewf-missing",
            task_config=None,
        )


def test_log2timeline_extract_single_zip(
    tmp_path, fake_subprocess, bound_task, monkeypatch
):
    """A single ZIP input with extract-single-zip=True extracts the archive first."""
    zip_file = tmp_path / "triage.zip"
    zip_file.touch()

    extracted_dir = tmp_path / "extracted_dir"
    extracted_dir.mkdir()

    monkeypatch.setattr(
        log2timeline,
        "extract_archive",
        lambda file, out_path, log_path: ("unzip command", str(extracted_dir)),
    )

    inputs = [{"path": str(zip_file), "display_name": "triage.zip"}]
    log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-zip",
        task_config={"extract-single-zip": True},
    )

    cmd = fake_subprocess[0]
    assert cmd[-1] == str(extracted_dir)
    # Extracted temp_dir cleaned up after execution.
    assert not os.path.exists(extracted_dir)


def test_log2timeline_extract_single_zip_error_raises(
    tmp_path, fake_subprocess, bound_task, monkeypatch
):
    """Failure in extract_archive raises and logs the exception."""
    zip_file = tmp_path / "corrupted.zip"
    zip_file.touch()

    def _fail_extract(*args, **kwargs):
        raise ValueError("Corrupted archive")

    monkeypatch.setattr(log2timeline, "extract_archive", _fail_extract)

    inputs = [{"path": str(zip_file), "display_name": "corrupted.zip"}]
    with pytest.raises(ValueError, match="Corrupted archive"):
        log2timeline.log2timeline(
            bound_task,
            input_files=inputs,
            output_path=str(tmp_path),
            workflow_id="wf-zip-fail",
            task_config={"extract-single-zip": True},
        )


def test_log2timeline_status_progress_polling(tmp_path, bound_task, monkeypatch):
    """Task polls status file during execution and emits progress events."""
    monkeypatch.setattr(log2timeline.time, "sleep", lambda s: None)

    class _StatusPollingProcess:
        def __init__(self, status_path):
            self.status_path = status_path
            self.poll_count = 0
            self.stdout = MagicMock()
            self.stdout.read.return_value = ""
            self.stderr = MagicMock()
            self.stderr.read.return_value = ""

        def poll(self):
            if self.poll_count == 0:
                with open(self.status_path, "w") as fh:
                    fh.write(
                        "header Processed: 1000 Total: 2000\n"
                    )
                self.poll_count += 1
                return None
            return 0

    def fake_popen(cmd, *args, **kwargs):
        status_path = cmd[cmd.index("--status-view-file") + 1]
        return _StatusPollingProcess(status_path)

    monkeypatch.setattr(log2timeline.subprocess, "Popen", fake_popen)

    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]
    log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-status",
        task_config=None,
    )

    # Verify task-progress event was sent at least twice (initial + from status file)
    assert bound_task.send_event.call_count >= 2
    event_names = [call[0][0] for call in bound_task.send_event.call_args_list]
    assert all(name == "task-progress" for name in event_names)


def test_log2timeline_process_cli_logs_called_on_stderr(
    tmp_path, fake_subprocess, bound_task, monkeypatch
):
    """When subprocess produces stderr, process_plaso_cli_logs processes it."""
    fake_subprocess.stderr = "[WARNING] something unexpected\n"
    mock_process_logs = MagicMock()
    monkeypatch.setattr(log2timeline, "process_plaso_cli_logs", mock_process_logs)

    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]
    log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-stderr",
        task_config=None,
    )

    mock_process_logs.assert_called_once_with(
        "[WARNING] something unexpected\n", log2timeline.logger
    )


def test_log2timeline_pipe_result_input(tmp_path, fake_subprocess, bound_task):
    """Input files passed through pipe_result from upstream tasks are processed."""
    pipe_data = {
        "output_files": [
            {"path": "/in/upstream.raw", "display_name": "upstream.raw"}
        ]
    }
    pipe_result = base64.b64encode(json.dumps(pipe_data).encode("utf-8")).decode("utf-8")

    raw = log2timeline.log2timeline(
        bound_task,
        pipe_result=pipe_result,
        input_files=None,
        output_path=str(tmp_path),
        workflow_id="wf-pipe",
        task_config=None,
    )

    result = _decode(raw)
    assert len(result["output_files"]) == 1
    assert result["output_files"][0]["display_name"] == "upstream.raw.plaso"
    assert result["output_files"][0]["original_path"] == "/in/upstream.raw"
    cmd = fake_subprocess[0]
    assert cmd[-1] == "/in/upstream.raw"


def test_log2timeline_telemetry_recorded(tmp_path, fake_subprocess, bound_task, monkeypatch):
    """Telemetry spans record input_files, task_config, and workflow_id."""
    mock_telemetry = MagicMock()
    monkeypatch.setattr(log2timeline.telemetry, "add_attribute_to_current_span", mock_telemetry)

    inputs = [{"path": "/in/disk.raw", "display_name": "disk.raw"}]
    config = {"register_in_db": True}

    log2timeline.log2timeline(
        bound_task,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-telemetry",
        task_config=config,
    )

    mock_telemetry.assert_any_call("input_files", inputs)
    mock_telemetry.assert_any_call("task_config", config)
    mock_telemetry.assert_any_call("workflow_id", "wf-telemetry")
