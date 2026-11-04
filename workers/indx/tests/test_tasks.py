"""Tests for OpenRelik Celery task execution and artifact generation."""

from __future__ import annotations

import base64
import csv
import json
import struct
import tempfile
import zipfile
from pathlib import Path

from src.tasks import TASK_METADATA, TASK_NAME, command
from tests.test_parser import (
    build_synthetic_indx_block,
    build_synthetic_mft_record,
    create_end_entry,
    create_test_file_name_payload,
    create_test_index_entry,
)


def test_task_metadata() -> None:
    """Verify task metadata properties."""
    assert TASK_NAME == "openrelik-worker-indx.tasks.parse"
    task_config = TASK_METADATA.get("task_config")
    assert isinstance(task_config, list)
    assert "carve_slack" in [c["name"] for c in task_config if isinstance(c, dict)]


def test_task_execution_on_i30_file() -> None:
    """Test task execution on a synthetic $I30 file, verifying JSONL, CSV, and Timesketch."""
    active_e = create_test_index_entry(
        file_mft_ref=101,
        file_name_payload=create_test_file_name_payload(
            "report.docx",
            real_size=5000,
            allocated_size=8192,
        ),
    )
    slack_e = create_test_index_entry(
        file_mft_ref=202,
        file_name_payload=create_test_file_name_payload(
            "deleted_notes.txt",
            real_size=300,
            allocated_size=4096,
        ),
    )
    block = build_synthetic_indx_block(
        active_entries=[active_e], slack_entries=[slack_e]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test_$I30"
        input_path.write_bytes(block)

        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        input_files = [{"path": str(input_path), "display_name": "$I30"}]

        res_b64 = command(
            None,
            input_files=input_files,
            output_path=str(out_dir),
            workflow_id="wf-test-01",
        )

        res_data = json.loads(base64.b64decode(res_b64))
        output_files = res_data.get("output_files", [])

        # Should generate 3 output files: indx_parsed.jsonl, indx_parsed.csv, indx_timesketch.jsonl
        assert len(output_files) == 3
        display_names = {f["display_name"]: f["path"] for f in output_files}
        assert "indx_parsed.jsonl" in display_names
        assert "indx_parsed.csv" in display_names
        assert "indx_timesketch.jsonl" in display_names

        # Verify indx_parsed.jsonl
        jsonl_path = display_names["indx_parsed.jsonl"]
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        assert len(lines) == 2
        assert lines[0]["filename"] == "report.docx"
        assert lines[0]["is_slack"] is False
        assert lines[1]["filename"] == "deleted_notes.txt"
        assert lines[1]["is_slack"] is True

        # Verify indx_parsed.csv
        csv_path = display_names["indx_parsed.csv"]
        with open(csv_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["filename"] == "report.docx"
        assert rows[0]["is_slack"] == "False"
        assert rows[1]["filename"] == "deleted_notes.txt"
        assert rows[1]["is_slack"] == "True"

        # Verify indx_timesketch.jsonl
        ts_path = display_names["indx_timesketch.jsonl"]
        with open(ts_path, "r", encoding="utf-8") as fh:
            events = [json.loads(line) for line in fh if line.strip()]
        # Each entry has 4 timestamps (Created, Modified, MFT Modified, Accessed)
        assert len(events) == 8
        first_event = events[0]
        assert first_event["data_type"] == "windows:ntfs:indx"
        assert first_event["filename"] in ("report.docx", "deleted_notes.txt")
        assert "message" in first_event
        assert "datetime" in first_event
        assert "timestamp_desc" in first_event

        # Verify meta summary counts
        meta = res_data.get("meta", {})
        assert meta.get("active_count") == 1
        assert meta.get("slack_count") == 1
        assert meta.get("total_count") == 2
        assert meta.get("scanned_count") == 1
        assert "**Total Entries**: 2" in meta.get("summary", "")


def test_task_execution_disable_slack() -> None:
    """Test task execution with carve_slack disabled in task_config."""
    active_e = create_test_index_entry(
        file_mft_ref=101,
        file_name_payload=create_test_file_name_payload("active_only.txt"),
    )
    slack_e = create_test_index_entry(
        file_mft_ref=202,
        file_name_payload=create_test_file_name_payload("slack_ignored.txt"),
    )
    block = build_synthetic_indx_block(
        active_entries=[active_e], slack_entries=[slack_e]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "$I30"
        input_path.write_bytes(block)

        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        res_b64 = command(
            None,
            input_files=[{"path": str(input_path)}],
            output_path=str(out_dir),
            workflow_id="wf-no-slack",
            task_config={"carve_slack": False},
        )

        res_data = json.loads(base64.b64decode(res_b64))
        meta = res_data.get("meta", {})
        assert meta.get("active_count") == 1
        assert meta.get("slack_count") == 0
        assert meta.get("total_count") == 1


def test_task_execution_with_zip_archive() -> None:
    """Test task execution when input file is a ZIP bundle containing an INDX stream."""
    active_e = create_test_index_entry(
        file_mft_ref=10,
        file_name_payload=create_test_file_name_payload("zipped_doc.pdf"),
    )
    block = build_synthetic_indx_block(active_entries=[active_e])

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "bundle.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("evidence/$I30", block)

        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        res_b64 = command(
            None,
            input_files=[{"path": str(zip_path)}],
            output_path=str(out_dir),
            workflow_id="wf-zip",
        )

        res_data = json.loads(base64.b64decode(res_b64))
        assert res_data.get("meta", {}).get("total_count") == 1


def test_task_execution_with_piped_result() -> None:
    """Test task execution when inputs are provided via pipe_result."""
    active_e = create_test_index_entry(
        file_mft_ref=88,
        file_name_payload=create_test_file_name_payload("piped.txt"),
    )
    block = build_synthetic_indx_block(active_entries=[active_e])

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "stream.bin"
        input_path.write_bytes(block)

        prev_task_dict = {
            "output_files": [{"path": str(input_path), "display_name": "stream.bin"}],
            "workflow_id": "wf-piped",
        }
        pipe_result = base64.b64encode(
            json.dumps(prev_task_dict).encode("utf-8")
        ).decode("utf-8")

        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        res_b64 = command(
            pipe_result=pipe_result,
            input_files=None,
            output_path=str(out_dir),
            workflow_id="wf-piped",
        )

        res_data = json.loads(base64.b64decode(res_b64))
        assert res_data.get("meta", {}).get("total_count") == 1


def test_task_execution_on_mft_file() -> None:
    """Test Celery task execution on a synthetic $MFT file."""
    e1 = create_test_index_entry(
        file_mft_ref=4001,
        file_name_payload=create_test_file_name_payload("task_mft.txt"),
    )
    root_buf = bytearray(256)
    struct.pack_into("<IIIb3s", root_buf, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    curr = 0x20
    root_buf[curr : curr + len(e1)] = e1
    curr += len(e1)
    end_e = create_end_entry()
    root_buf[curr : curr + len(end_e)] = end_e
    curr += len(end_e)
    struct.pack_into(
        "<IIIb3s",
        root_buf,
        0x10,
        0x10,
        curr - 0x10,
        len(root_buf) - 0x10,
        0,
        b"\x00\x00\x00",
    )
    rec = build_synthetic_mft_record(record_num=5, index_root_payload=bytes(root_buf))

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "$MFT"
        input_path.write_bytes(rec)

        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        res_b64 = command(
            None,
            input_files=[{"path": str(input_path)}],
            output_path=str(out_dir),
            workflow_id="wf-mft",
        )

        res_data = json.loads(base64.b64decode(res_b64))
        meta = res_data.get("meta", {})
        assert meta.get("total_count") == 1
        assert meta.get("active_count") == 1
        assert meta.get("scanned_count") == 1
