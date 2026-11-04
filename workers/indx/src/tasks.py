"""OpenRelik Celery task entrypoint for NTFS $I30 / INDX parsing and slack carving."""

from __future__ import annotations

import csv
import json
import logging
import struct
import tarfile
import zipfile
from typing import Any

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import (
    create_output_file,
)
from openrelik_worker_common.task_utils import (
    create_task_result,
    get_input_files,
)

from .app import celery
from .parser import IndexEntry, parse_file

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-indx.tasks.parse"

# Task metadata for registration in the core system.
TASK_METADATA: dict[str, Any] = {
    "display_name": "INDX Parser",
    "description": "NTFS directory index ($I30 / INDX) parser and slack carver",
    "task_config": [
        {
            "name": "carve_slack",
            "label": "Carve Slack Space",
            "description": "Carve deleted index entries from unallocated slack space",
            "type": "checkbox",
            "default": True,
            "required": False,
        },
    ],
}

log_root = Logger()
logger: logging.Logger = log_root.get_logger(__name__, get_task_logger(__name__))


@signals.task_prerun.connect  # type: ignore[untyped-decorator]
def on_task_prerun(
    sender: Any, task_id: str, task: Any, args: Any, kwargs: Any, **_: Any
) -> None:
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)  # type: ignore[untyped-decorator]
def command(
    self: Any,
    pipe_result: str | None = None,
    input_files: list[dict[str, Any]] | None = None,
    output_path: str | None = None,
    workflow_id: str | None = None,
    task_config: dict[str, Any] | None = None,
) -> str:
    """Run NTFS $I30 / INDX parsing and slack carving on input files.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries.
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    log_root.bind(workflow_id=workflow_id)
    logger.info("Starting %s for workflow %s", TASK_NAME, workflow_id)

    task_config = task_config or {}
    carve_slack = bool(task_config.get("carve_slack", True))

    resolved_files = get_input_files(pipe_result, input_files or [])
    all_entries: list[IndexEntry] = []
    scanned_count = 0

    for input_file in resolved_files:
        file_path = input_file.get("path")
        if not file_path:
            continue

        try:
            entries = parse_file(file_path, carve_slack=carve_slack)
            all_entries.extend(entries)
            scanned_count += 1
            logger.info("Parsed %d entries from %s", len(entries), file_path)
        except (
            OSError,
            ValueError,
            struct.error,
            zipfile.BadZipFile,
            tarfile.TarError,
        ) as e:
            logger.exception("Failed to parse %s", file_path)
            logger.debug("Parsing error: %s", e)

    active_count = sum(1 for e in all_entries if not e.is_slack)
    slack_count = sum(1 for e in all_entries if e.is_slack)
    total_count = len(all_entries)

    output_files_dicts: list[dict[str, Any]] = []

    if output_path:
        output_jsonl = create_output_file(
            output_path,
            display_name="indx_parsed",
            extension="jsonl",
            data_type="openrelik:worker:indx:jsonl",
        )
        with open(output_jsonl.path, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(entry.to_dict()) + "\n" for entry in all_entries)
        output_files_dicts.append(output_jsonl.to_dict())

        output_csv = create_output_file(
            output_path,
            display_name="indx_parsed",
            extension="csv",
            data_type="openrelik:worker:indx:csv",
        )
        csv_fields = [
            "filename",
            "parent_mft_ref",
            "parent_mft_seq",
            "file_mft_ref",
            "file_mft_seq",
            "real_size",
            "allocated_size",
            "created_time",
            "modified_time",
            "mft_modified_time",
            "accessed_time",
            "is_slack",
            "is_directory",
            "namespace",
            "flags",
            "source_offset",
        ]
        with open(output_csv.path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=csv_fields)
            writer.writeheader()
            for entry in all_entries:
                writer.writerow(entry.to_dict())
        output_files_dicts.append(output_csv.to_dict())

        output_ts = create_output_file(
            output_path,
            display_name="indx_timesketch",
            extension="jsonl",
            data_type="openrelik:worker:indx:timesketch",
        )
        with open(output_ts.path, "w", encoding="utf-8") as fh:
            for entry in all_entries:
                summary_status = "[Slack]" if entry.is_slack else "[Active]"
                message = f"{summary_status} {entry.filename} (Size: {entry.real_size}, MFT: {entry.file_mft_ref})"

                ts_mappings = [
                    (entry.created_time, "File Created"),
                    (entry.modified_time, "File Modified"),
                    (entry.mft_modified_time, "MFT Modified"),
                    (entry.accessed_time, "File Accessed"),
                ]

                for dt_val, desc in ts_mappings:
                    if dt_val is not None:
                        event = {
                            "datetime": dt_val,
                            "timestamp_desc": desc,
                            "message": message,
                            "data_type": "windows:ntfs:indx",
                            "is_slack": entry.is_slack,
                            "filename": entry.filename,
                            "file_size": entry.real_size,
                            "allocated_size": entry.allocated_size,
                            "file_mft_ref": entry.file_mft_ref,
                            "file_mft_seq": entry.file_mft_seq,
                            "parent_mft_ref": entry.parent_mft_ref,
                            "parent_mft_seq": entry.parent_mft_seq,
                            "namespace": entry.namespace,
                            "is_directory": entry.is_directory,
                        }
                        fh.write(json.dumps(event) + "\n")
        output_files_dicts.append(output_ts.to_dict())

    summary_markdown = (
        "### NTFS $I30 / INDX Parser Summary\n"
        f"- **Scanned Files/Streams**: {scanned_count}\n"
        f"- **Active Entries**: {active_count}\n"
        f"- **Carved Slack Entries**: {slack_count}\n"
        f"- **Total Entries**: {total_count}\n"
    )

    logger.info("Finished %s for workflow %s", TASK_NAME, workflow_id)

    task_result: str = create_task_result(
        output_files=output_files_dicts,
        workflow_id=workflow_id,
        command="parse",
        meta={
            "summary": summary_markdown,
            "scanned_count": scanned_count,
            "active_count": active_count,
            "slack_count": slack_count,
            "total_count": total_count,
        },
    )
    return task_result
