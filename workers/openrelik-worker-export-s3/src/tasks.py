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

import json
import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .s3_uploader import compress_gzip, upload_file

logger = logging.getLogger(__name__)

TASK_NAME = "openrelik-worker-export-s3.tasks.upload"

VALID_COMPRESSION = ("none", "gzip")

TASK_METADATA = {
    "display_name": "Export to S3",
    "description": "Export input files to Amazon S3 with optional gzip compression.",
    "task_config": [
        {
            "name": "s3_bucket",
            "label": "S3 bucket",
            "description": "Destination S3 bucket name (without the s3:// prefix).",
            "type": "text",
            "required": True,
        },
        {
            "name": "s3_prefix",
            "label": "S3 key prefix",
            "description": (
                "Optional key prefix (folder). Leading and trailing slashes "
                "are stripped, and '..' / '.' path components are dropped. "
                "Example: 'forensics/case-123'."
            ),
            "type": "text",
            "required": False,
        },
        {
            "name": "compression",
            "label": "Compression",
            "description": (
                "'none' uploads files as-is. 'gzip' gzips each file individually "
                "with a .gz suffix."
            ),
            "type": "select",
            "items": list(VALID_COMPRESSION),
            "required": False,
        },
        {
            "name": "object_name",
            "label": "Object name pattern",
            "description": (
                "Optional name for the uploaded object (the file portion of the "
                "S3 key, joined under 'S3 key prefix'). The '{basename}' "
                "placeholder is replaced with the source artifact name supplied "
                "via 'Source basename' — set a distinguisher around it (e.g. "
                "'{basename}_2024-01') to keep multiple export tasks from "
                "colliding. The uploaded file's extension is appended "
                "automatically. Leave blank to use the upstream filename."
            ),
            "type": "text",
            "required": False,
        },
        {
            "name": "export_basename",
            "label": "Source basename",
            "description": (
                "Value substituted into '{basename}' in the object name pattern. "
                "Typically injected per-import by an importer (param_name "
                "'export_basename') rather than set by hand."
            ),
            "type": "text",
            "required": False,
        },
    ],
}


def _file_extension(input_file: dict) -> str:
    """Return the upload file's extension (with leading dot), or '' if none.

    Prefers the display_name, falling back to the on-disk path. Only the final
    extension is returned, so 'abc.plaso.csv' yields '.csv'.
    """
    name = input_file.get("display_name") or os.path.basename(
        input_file.get("path", "")
    )
    return os.path.splitext(name)[1]


def _resolve_object_name(
    pattern: str, basename: str, input_file: dict, fallback: str
) -> str:
    """Build the object name from a user pattern, or fall back to ``fallback``.

    When ``pattern`` is set, ``{basename}`` is substituted with ``basename`` and
    the upload file's own extension is appended. A pattern that references
    ``{basename}`` without a value provided is treated as unset so callers fall
    back rather than emit a literal '{basename}' key.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return fallback
    if "{basename}" in pattern:
        if not basename:
            return fallback
        pattern = pattern.replace("{basename}", basename)
    return f"{pattern}{_file_extension(input_file)}"


def _safe_key_segment(raw: str) -> str:
    """Sanitize a user-supplied path segment for use in an S3 key.

    Strips surrounding whitespace and slashes, rejects NUL bytes, and drops
    ``..`` / ``.`` path components so users cannot escape ``s3_prefix`` or
    produce surprising keys via crafted ``display_name`` values.
    """
    if not raw:
        return ""
    if "\x00" in raw:
        raise ValueError(f"Invalid S3 key segment (NUL byte): {raw!r}")
    parts = (p.strip() for p in raw.split("/"))
    return "/".join(p for p in parts if p and p not in (".", ".."))


def _unlink_quiet(path: str) -> None:
    """Remove a temp file, logging (but not raising) on failure."""
    try:
        os.unlink(path)
    except OSError:
        logger.exception("Failed to remove temp file %s", path)


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA, max_retries=0)
def upload(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Export input files to Amazon S3, with optional compression.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory (unused — this task emits no files).
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    input_files = get_input_files(pipe_result, input_files or [])
    task_config = task_config or {}

    if not input_files:
        return create_task_result(
            output_files=[],
            workflow_id=workflow_id,
            command="S3 upload",
            meta={"warnings": "No input files provided."},
        )

    bucket = task_config.get("s3_bucket")
    if not bucket:
        raise ValueError("task_config['s3_bucket'] is required.")
    prefix = _safe_key_segment(task_config.get("s3_prefix") or "")
    object_name_pattern = task_config.get("object_name") or ""
    export_basename = task_config.get("export_basename") or ""
    compression = task_config.get("compression") or "none"
    if compression not in VALID_COMPRESSION:
        raise ValueError(
            f"task_config['compression'] must be one of {VALID_COMPRESSION!r}; "
            f"got {compression!r}."
        )

    aws_region = os.environ.get("AWS_REGION")
    if not aws_region:
        raise RuntimeError("AWS_REGION environment variable is not set on the worker.")
    # Empty string from compose's `${VAR:-}` default must collapse to None so
    # boto3 falls back to its real-AWS endpoint.
    endpoint_url = os.environ.get("AWS_S3_ENDPOINT_URL") or None

    # Credentials are resolved via boto3's default credential chain (env vars,
    # shared credentials file, IAM role, SSO). If none are available the first
    # S3 call raises NoCredentialsError, which is caught below.
    s3 = boto3.client("s3", region_name=aws_region, endpoint_url=endpoint_url)

    def _make_key(name: str) -> str:
        return "/".join(p for p in (prefix, name) if p)

    total_files = len(input_files)
    uploaded: list[dict] = []
    failed: list[dict] = []

    for i, input_file in enumerate(input_files, start=1):
        display_name = input_file.get("display_name") or os.path.basename(
            input_file["path"]
        )
        # Prefer the upstream/source filename (basename of original_path) so the
        # S3 key matches the originally uploaded artifact rather than any
        # derived display_name from intermediate pipeline steps.
        original_path = input_file.get("original_path")
        fallback_name = (
            os.path.basename(original_path) if original_path else display_name
        )
        # An object-name pattern (with {basename} from export_basename) wins over
        # the upstream name — this is how the original artifact name survives a
        # pipeline that has otherwise reduced everything to UUIDs.
        source_name = _resolve_object_name(
            object_name_pattern, export_basename, input_file, fallback_name
        )
        safe_name = _safe_key_segment(source_name)
        if not safe_name:
            failed.append(
                {"display_name": display_name, "error": "empty/invalid source name"}
            )
            continue

        self.send_event(
            "task-progress",
            data={
                "status": "Uploading to S3",
                "progress": f"File {i} of {total_files}",
                "current_file": display_name,
                "bucket": bucket,
            },
        )

        cleanup_path = None
        if compression == "gzip":
            local_path = compress_gzip(input_file["path"])
            cleanup_path = local_path
            key_name = f"{safe_name}.gz"
        else:
            local_path = input_file["path"]
            key_name = safe_name
        key = _make_key(key_name)

        try:
            # Note: no per-byte progress callback. boto3.upload_file invokes
            # callbacks from its multipart worker threads, and Celery's event
            # dispatcher is not thread-safe — concurrent send_event calls have
            # corrupted the event channel and prevented task-succeeded from
            # reaching the mediator (UI stuck on "running"). One progress
            # event per file from the main thread is enough.
            size = upload_file(s3, local_path, bucket, key)
            uploaded.append({"display_name": display_name, "key": key, "size": size})
        except (ClientError, BotoCoreError) as exc:
            logger.exception(
                "S3 upload failed for %s -> s3://%s/%s", display_name, bucket, key
            )
            failed.append(
                {"display_name": display_name, "key": key, "error": str(exc)}
            )
        finally:
            if cleanup_path:
                _unlink_quiet(cleanup_path)

    total_bytes = sum(u["size"] for u in uploaded)
    self.send_event(
        "task-progress",
        data={
            "status": "Done",
            "uploaded": len(uploaded),
            "failed": len(failed),
            "bytes": total_bytes,
        },
    )

    meta = {
        "bucket": bucket,
        "prefix": prefix,
        "compression": compression,
        "endpoint_url": endpoint_url,
        "uploaded_count": len(uploaded),
        "uploaded_bytes": total_bytes,
        "uploaded_objects": uploaded,
        "failed_count": len(failed),
        "failed_objects": failed,
    }

    if failed:
        # Celery only persists return values, not exception payloads — log the
        # full meta so operators can recover what went where.
        logger.error("S3 upload partial failure: %s", json.dumps(meta, default=str))
        raise RuntimeError(
            f"S3 upload completed with {len(failed)} failure(s) out of "
            f"{total_files} file(s). Successful uploads: {len(uploaded)}. "
            f"See worker logs for failed_objects details."
        )

    return create_task_result(
        output_files=[],
        workflow_id=workflow_id,
        command=f"S3 upload (compression={compression})",
        meta=meta,
    )
