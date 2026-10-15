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

import fnmatch
import logging
import os

from openrelik_worker_common.task_utils import create_task_result

from .app import celery

logger = logging.getLogger(__name__)

TASK_NAME = "openrelik-worker-cleanup.tasks.cleanup"

# Files matching these glob patterns (by basename) are preserved by default.
# Task logs are small and useful for debugging, so they are kept.
DEFAULT_KEEP_PATTERNS = ["*.log"]

TASK_METADATA = {
    "display_name": "Cleanup intermediate files",
    "description": (
        "Deletes every file left in the workflow output folder, except those "
        "matching the keep patterns (default: *.log). Intended as the final "
        "chord callback, so it runs only after all other tasks have finished "
        "with the files they produced."
    ),
    "task_config": [
        {
            "name": "keep_patterns",
            "label": "Keep patterns (comma-separated globs)",
            "description": (
                "Comma-separated glob patterns matched against each file's "
                "name. Matching files are preserved; everything else under the "
                "workflow output folder is deleted. Default: *.log"
            ),
            "type": "text",
            "required": False,
        },
        {
            "name": "dry_run",
            "label": "Dry run (report only, delete nothing)",
            "description": (
                "When enabled, the task logs and reports the files it WOULD "
                "delete without removing them. Useful for verifying selection "
                "before enabling real deletion."
            ),
            "type": "switch",
            "value": False,
            "required": False,
        },
        {
            "name": "remove_empty_dirs",
            "label": "Remove now-empty subdirectories",
            "description": (
                "After deleting files, remove any empty subdirectories left "
                "under the workflow output folder. The output folder itself is "
                "never removed."
            ),
            "type": "switch",
            "value": True,
            "required": False,
        },
    ],
}


def _parse_keep_patterns(raw) -> list[str]:
    """Parse the comma-separated keep_patterns config into a clean list.

    Falls back to DEFAULT_KEEP_PATTERNS when unset or empty.
    """
    if not raw:
        return list(DEFAULT_KEEP_PATTERNS)
    patterns = [p.strip() for p in raw.split(",")]
    patterns = [p for p in patterns if p]
    return patterns or list(DEFAULT_KEEP_PATTERNS)


def _is_kept(filename: str, keep_patterns: list[str]) -> bool:
    """True if the file's basename matches any keep pattern."""
    return any(fnmatch.fnmatch(filename, pattern) for pattern in keep_patterns)


def _unlink_quiet(path: str, dry_run: bool = False) -> bool:
    """Remove a file, logging (not raising) on failure.

    When ``dry_run`` is True the file is left in place and the removal is only
    logged. Returns True if the file is deleted, already missing, or skipped
    for dry_run — and False only if a real removal failed.
    """
    if dry_run:
        logger.info("[dry_run] would delete %s", path)
        return True
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        # Idempotent: already gone (e.g. removed by a concurrent run).
        return True
    except OSError:
        logger.exception("Failed to remove file %s", path)
        return False


def _prune_empty_dirs(output_path: str) -> int:
    """Remove empty directories strictly under output_path.

    Walks bottom-up so nested empty dirs collapse in one pass. Never removes
    ``output_path`` itself. Best-effort: non-empty dirs and races are ignored.
    """
    root_real = os.path.realpath(output_path)
    removed = 0
    for dirpath, _dirnames, _filenames in os.walk(output_path, topdown=False):
        if os.path.realpath(dirpath) == root_real:
            continue  # never remove the workflow folder itself
        try:
            os.rmdir(dirpath)  # only succeeds if empty
            removed += 1
        except OSError:
            pass
    return removed


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA, max_retries=0)
def cleanup(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Delete every file under output_path except those matching keep patterns.

    Designed as the final chord callback: because it is the terminal node,
    every other task in the workflow has already run and consumed the files it
    needed by the time this executes. It therefore treats anything left in the
    workflow output folder (except the keep patterns) as a deletable
    intermediate artifact.

    NOTE: this deletes files purely by location and name — it does NOT consult
    the database. If the workflow produced REGISTERED outputs (register_in_db=
    True), those blobs live in this same folder and WILL be deleted unless they
    match a keep pattern, orphaning their DB rows. Use this worker only in
    workflows whose retained results are exported elsewhere or are matched by 
    keep_patterns.

    Args:
        pipe_result: Chord-callback results from the header tasks. Unused —
            enumeration is by folder walk, not by piped file list.
        input_files: Unused.
        output_path: The workflow output folder to clean. Required.
        workflow_id: ID of the workflow.
        task_config: {"keep_patterns": str, "dry_run": bool,
            "remove_empty_dirs": bool}.

    Returns:
        Base64-encoded task result with empty output_files and a meta summary.
    """
    task_config = task_config or {}
    dry_run = bool(task_config.get("dry_run", False))
    remove_empty_dirs = bool(task_config.get("remove_empty_dirs", False))
    keep_patterns = _parse_keep_patterns(task_config.get("keep_patterns"))

    if not output_path or not os.path.isdir(output_path):
        logger.error(
            "cleanup called without a valid output_path (%r); deleting nothing.",
            output_path,
        )
        return create_task_result(
            output_files=[],
            workflow_id=workflow_id,
            command="cleanup",
            meta={
                "dry_run": dry_run,
                "keep_patterns": keep_patterns,
                "output_path": output_path,
                "scanned_count": 0,
                "kept_count": 0,
                "deleted_count": 0,
                "freed_bytes": 0,
                "error": "output_path missing or not a directory",
            },
        )

    self.send_event("task-progress", data={"status": "Scanning output folder"})

    scanned = 0
    kept = 0
    deleted_count = 0
    freed_bytes = 0
    failed = []

    # Walk the workflow output folder. os.walk does not follow directory
    # symlinks by default, so we stay within the folder tree. A file that is a
    # symlink is removed by unlinking the link itself (never its target).
    for dirpath, _dirnames, filenames in os.walk(output_path):
        for filename in filenames:
            scanned += 1
            if _is_kept(filename, keep_patterns):
                kept += 1
                continue
            path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if _unlink_quiet(path, dry_run=dry_run):
                deleted_count += 1
                freed_bytes += size
            else:
                failed.append(path)

    removed_dirs = 0
    if remove_empty_dirs and not dry_run:
        removed_dirs = _prune_empty_dirs(output_path)

    self.send_event(
        "task-progress",
        data={"status": "Done", "deleted": deleted_count, "dry_run": dry_run},
    )

    meta = {
        "dry_run": dry_run,
        "keep_patterns": keep_patterns,
        "output_path": output_path,
        "scanned_count": scanned,
        "kept_count": kept,
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "failed_paths": failed,
        "removed_empty_dirs": removed_dirs,
    }
    logger.info("cleanup summary: %s", meta)

    # IMPORTANT: do NOT raise on per-file failures. This is the chord callback;
    # raising would fail the whole workflow over a best-effort cleanup. Failures
    # are reported in meta and logs instead.
    return create_task_result(
        output_files=[],
        workflow_id=workflow_id,
        command="cleanup",
        meta=meta,
    )
