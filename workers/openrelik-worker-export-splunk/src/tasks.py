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
# limitations under the License.

import asyncio
import logging
import os

from openrelik_worker_common.slice_utils import select_slice
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .hec_uploader import HECUploader, UploadProgress

logger = logging.getLogger(__name__)

COMPATIBLE_INPUTS = {
    "data_types": [],
    "mime_types": [],
    "filenames": ["*.jsonl", "*.json_line", "*.json"],
}

TASK_NAME = "openrelik-worker-export-splunk.tasks.upload"

TASK_METADATA = {
    "display_name": "Export to Splunk",
    "description": "Upload JSONL events to Splunk Cloud via the HTTP Event Collector.",
    "task_config": [
        {
            "name": "index",
            "label": "Splunk index",
            "description": "Target Splunk index to receive the events.",
            "type": "text",
            "required": True,
        },
        {
            "name": "sourcetype",
            "label": "Sourcetype",
            "description": "Splunk sourcetype to assign to the events (default: _json).",
            "type": "text",
            "required": False,
        },
        {
            "name": "host",
            "label": "Host",
            "description": (
                "Optional Splunk 'host' field. Leave blank to let the Splunk "
                "indexer assign a value, or to rely on search-time field "
                "extraction of the source host from the event body."
            ),
            "type": "text",
            "required": False,
        },
        {
            "name": "source",
            "label": "Source override",
            "description": "Optional source field. Defaults to the input display name.",
            "type": "text",
            "required": False,
        },
        {
            "name": "hec_endpoint",
            "label": "HEC endpoint",
            "description": (
                "'raw' (default) posts lines verbatim to /services/collector/raw "
                "with metadata on the URL. 'event' wraps each JSONL row with "
                "index/host/source metadata and POSTs to /services/collector/event."
            ),
            "type": "select",
            "items": ["raw", "event"],
            "required": False,
        },
        {
            "name": "slice_select",
            "label": "Time-slice selection",
            "description": (
                "When inputs are time-sliced psort outputs (filename pattern "
                "<base>.slice-<K>-of-<N>.<ext>), choose which slice to upload. "
                "'all' (default) uploads every slice; 'latest' uploads only "
                "slice K=N per source; an integer K uploads only slice K. "
                "Inputs without a slice suffix are always passed through."
            ),
            "type": "text",
            "value": "all",
            "required": False,
        },
    ],
}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA, max_retries=0)
def upload(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Upload JSONL events from input files to Splunk HEC.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory (unused — this task emits no files).
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    input_files = get_input_files(pipe_result, input_files or [], filter=COMPATIBLE_INPUTS)
    task_config = task_config or {}

    input_files = select_slice(
        input_files, mode=task_config.get("slice_select") or "all"
    )

    if not input_files:
        return create_task_result(
            output_files=[],
            workflow_id=workflow_id,
            command="Splunk HEC upload",
            meta={"warnings": "No supported input files provided. Expected *.jsonl or *.json_line files."},
        )

    hec_url = os.environ.get("SPLUNK_HEC_URL")
    hec_token = os.environ.get("SPLUNK_HEC_TOKEN")
    if not hec_url:
        raise RuntimeError("SPLUNK_HEC_URL environment variable is not set on the worker.")
    if not hec_token:
        raise RuntimeError("SPLUNK_HEC_TOKEN environment variable is not set on the worker.")
    verify_tls = _bool_env("SPLUNK_HEC_VERIFY_TLS", default=True)

    index = task_config.get("index")
    if not index:
        raise ValueError("task_config['index'] is required.")
    sourcetype = task_config.get("sourcetype") or "_json"
    endpoint = task_config.get("hec_endpoint") or "raw"
    host = task_config.get("host")
    source_override = task_config.get("source")

    total_files = len(input_files)
    total_success = 0
    total_failed = 0
    total_skipped = 0
    per_file: list[dict] = []

    for i, input_file in enumerate(input_files, start=1):
        display_name = input_file.get("display_name") or input_file.get("path", "")
        source = source_override or display_name

        self.send_event(
            "task-progress",
            data={
                "status": "Uploading to Splunk HEC",
                "progress": f"File {i} of {total_files}",
                "current_file": display_name,
                "index": index,
                "sourcetype": sourcetype,
                "endpoint": endpoint,
            },
        )

        uploader = HECUploader(
            file_path=input_file["path"],
            hec_url=hec_url,
            token=hec_token,
            index=index,
            sourcetype=sourcetype,
            host=host,
            source=source,
            endpoint=endpoint,
            verify_tls=verify_tls,
            progress_cb=_make_progress_cb(self, display_name, i, total_files, index),
        )
        result = asyncio.run(uploader.run())

        if result.permanent_error:
            raise RuntimeError(
                f"Splunk HEC upload failed for {display_name}: "
                f"{result.permanent_error} (index={index!r}). "
                f"Aborted after {result.success_count} successful events."
            )

        total_success += result.success_count
        total_failed += result.failed_count
        total_skipped += result.skipped_count
        per_file.append(
            {
                "file": display_name,
                "success_events": result.success_count,
                "failed_events": result.failed_count,
                "skipped_events": result.skipped_count,
                "error_codes": result.error_dict if result.failed_count else {},
            }
        )

    self.send_event(
        "task-progress",
        data={
            "status": "Done",
            "success_events": total_success,
            "failed_events": total_failed,
            "skipped_events": total_skipped,
        },
    )

    return create_task_result(
        output_files=[],
        workflow_id=workflow_id,
        command="Splunk HEC upload",
        meta={
            "success_events": total_success,
            "failed_events": total_failed,
            "skipped_events": total_skipped,
            "per_file": per_file,
        },
    )


def _make_progress_cb(task, display_name: str, file_index: int, total_files: int, index: str):
    """Build an async progress callback that forwards uploader stats to the UI."""

    async def _cb(progress: UploadProgress) -> None:
        task.send_event(
            "task-progress",
            data={
                "status": "Uploading to Splunk HEC",
                "progress": f"File {file_index} of {total_files}",
                "current_file": display_name,
                "index": index,
                "success_events": progress.success_count,
                "failed_events": progress.failed_count,
                "batches_completed": progress.batches_completed,
            },
        )

    return _cb
