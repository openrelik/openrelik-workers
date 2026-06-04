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

"""Celery task: carve files from disk images with PhotoRec."""

import glob
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.reporting import MarkdownTable, Priority, Report
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

TASK_NAME = "openrelik-worker-photorec.tasks.photorec_carve"

TASK_METADATA = {
    "display_name": "PhotoRec carve",
    "description": (
        "Signature-based file carving from disk images with PhotoRec. By "
        "default carves unallocated space only (deleted files); carved files "
        "have no original names, paths or timestamps."
    ),
    "task_config": [
        {
            "name": "file_formats",
            "label": "File formats to carve (comma separated)",
            "description": (
                "PhotoRec family names, e.g. elf,exe,txt,gz,zip,sqlite. "
                "Default: elf,exe,txt"
            ),
            "type": "text",
        },
        {
            "name": "wholespace",
            "label": "Carve the whole image (not just unallocated space)",
            "description": (
                "Also recovers files still referenced by the filesystem; "
                "useful when filesystem metadata is damaged."
            ),
            "type": "checkbox",
        },
        {
            "name": "max_files",
            "label": "Maximum carved files to keep",
            "description": "Cap on registered output files. Default: 500.",
            "type": "text",
        },
    ],
}

DEFAULT_FORMATS = "elf,exe,txt"
DEFAULT_MAX_FILES = 500
ABSOLUTE_MAX_FILES = 5000

log_root = Logger()
logger = log_root.get_logger(__name__, get_task_logger(__name__))


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


def _build_command(image_path: str, dest_dir: str, formats: list[str],
                   wholespace: bool) -> list[str]:
    """Build the non-interactive PhotoRec invocation.

    The /cmd grammar runs the interactive menus unattended: fileopt disables
    every signature then enables the requested families; freespace restricts
    carving to unallocated space.
    """
    cmd_parts = ["partition_none", "options", "paranoid"]
    cmd_parts.append("wholespace" if wholespace else "freespace")
    cmd_parts.append("fileopt")
    cmd_parts.extend(["everything", "disable"])
    for fmt in formats:
        cmd_parts.extend([fmt, "enable"])
    cmd_parts.append("search")
    return [
        "photorec", "/log", "/d", dest_dir, "/cmd", image_path,
        ",".join(cmd_parts),
    ]


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def photorec_carve(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Carve files from each input disk image.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME} for workflow {workflow_id}")

    task_config = task_config or {}
    formats = [
        f.strip() for f in
        (task_config.get("file_formats") or DEFAULT_FORMATS).split(",")
        if f.strip()
    ]
    wholespace = bool(task_config.get("wholespace"))
    try:
        max_files = int(str(task_config.get("max_files", "")).strip() or DEFAULT_MAX_FILES)
    except ValueError:
        max_files = DEFAULT_MAX_FILES
    max_files = max(1, min(max_files, ABSOLUTE_MAX_FILES))

    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []
    counts: Counter = Counter()
    kept = 0
    skipped_over_cap = 0

    for input_file in input_files:
        # Carve into the shared output volume: container-local /tmp is
        # ephemeral storage with tight limits, and carving a real disk image
        # there gets the worker pod evicted mid-task.
        with tempfile.TemporaryDirectory(dir=output_path) as dest_dir:
            command = _build_command(
                input_file.get("path"), dest_dir, formats, wholespace
            )
            logger.info(f"Executing: {' '.join(command)}")
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True,
            )
            while process.poll() is None:
                self.send_event("task-progress")
                time.sleep(3)
            if process.returncode != 0:
                stderr = (process.stderr.read() or "")[:500] if process.stderr else ""
                logger.warning(
                    f"photorec exited {process.returncode} on "
                    f"{input_file.get('display_name')}: {stderr}"
                )

            # PhotoRec does not write into the given destination: it creates
            # sibling directories suffixed .1, .2, ... - walk those.
            carve_dirs = sorted(glob.glob(f"{dest_dir}.*")) or [dest_dir]
            for carve_dir in carve_dirs:
              for root, _, files in os.walk(carve_dir):
                  for name in sorted(files):
                      if name == "report.xml":
                          continue
                      extension = os.path.splitext(name)[1].lstrip(".") or "bin"
                      counts[extension] += 1
                      if kept >= max_files:
                          skipped_over_cap += 1
                          continue
                      carved = create_output_file(
                          output_path,
                          display_name=f"{input_file.get('display_name')}.carved.{name}",
                          data_type="openrelik:worker:photorec:carved_file",
                      )
                      shutil.copy(os.path.join(root, name), carved.path)
                      output_files.append(carved.to_dict())
                      kept += 1
              # PhotoRec leaves the sibling dirs outside the TemporaryDirectory
              # cleanup; remove them explicitly.
              if carve_dir != dest_dir:
                  shutil.rmtree(carve_dir, ignore_errors=True)

    report = Report("PhotoRec carving")
    report.priority = Priority.INFO
    report.summary = (
        f"{sum(counts.values())} files carved "
        f"({'whole image' if wholespace else 'unallocated space only'}; "
        f"formats: {','.join(formats)}); {kept} registered"
        + (f", {skipped_over_cap} over the cap" if skipped_over_cap else "")
    )
    section = report.add_section()
    section.add_paragraph(report.summary)
    if counts:
        table = MarkdownTable(["Extension", "Carved"])
        for extension, count in counts.most_common(30):
            table.add_row([extension, str(count)])
        section.add_table(table)

    logger.info(report.summary)
    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command="photorec /cmd",
        meta={
            "carved_total": sum(counts.values()),
            "registered": kept,
            "skipped_over_cap": skipped_over_cap,
        },
        task_report=report.to_dict(),
    )
