# Copyright 2024 Google LLC
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

import glob
import json
import os
import subprocess
from dataclasses import dataclass

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common import telemetry
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import create_output_file, is_disk_image
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.reporting import MarkdownTable, Priority, Report
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

log_root = Logger()
logger = log_root.get_logger(__name__, get_task_logger(__name__))


TASK_NAME = "openrelik-worker-yara.tasks.yara-scan"

TASK_METADATA = {
    "display_name": "Yara scan",
    "description": "Scans a folder or files with Yara rules",
    "task_config": [
        {
            "name": "Manual Yara rules",
            "label": 'rule test { strings: $ = "test" condition: true }',
            "description": "Run these extra Yara rules using the YaraScan plugin.",
            "type": "textarea",
            "required": False,
        },
        {
            "name": "Global Yara rules",
            "label": "/usr/share/openrelik/data/yara/",
            "Description": "Path to Yara rules as fetched by Data Sources (newline separated)",
            "type": "textarea",
            "required": False,
        },
        {
            "name": "mount_disk_images",
            "label": "Mount disk images",
            "description": "If checked, the worker will try to mount disk images and scan the files inside the disk image.",
            "type": "checkbox",
            "required": True,
            "default_value": False,
        },
    ],
}


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


def safe_list_get(l, index, default):
    """Small helper function to safely get an item from a list."""
    try:
        return l[index]
    except IndexError:
        return default


@dataclass
class YaraMatch:
    """Dataclass to store Yara match information."""

    filepath: str
    hash: str
    rule: str
    desc: str
    ref: str
    score: int


def generate_report_from_matches(matches: list[YaraMatch]) -> Report:
    """Generate a report from Yara matches.

    Args:
        matches: List of YaraMatch objects.

    Returns:
        Report object.
    """
    report = Report("Yara scan report")
    matches_section = report.add_section()
    matches_section.add_paragraph("List of Yara matches found in the scanned files.")
    if matches:
        report.priority = Priority.CRITICAL
    match_table = MarkdownTable(["filepath", "hash", "rule", "desc", "ref", "score"])
    for match in matches:
        match_table.add_row(
            [
                match.filepath,
                match.hash,
                match.rule,
                match.desc,
                match.ref,
                str(match.score),
            ]
        )

    matches_section.add_table(match_table)

    return report


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Fetch and run Yara rules on the input files.

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
    logger.debug(f"Starting {TASK_NAME} for workflow {workflow_id}")

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    output_files = []

    all_patterns = ""
    global_yara = task_config.get("Global Yara rules", "")
    manual_yara = task_config.get("Manual Yara rules", "")
    mount_disk_images = task_config.get("mount_disk_images", False)

    if not global_yara and not manual_yara:
        error_msg = "At least one of Global and/or Manual Yara rules must be provided"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    total_rules_read = 0
    for rule_path in global_yara.split("\n"):
        if os.path.isfile(rule_path):
            with open(rule_path, encoding="utf-8") as rf:
                all_patterns += rf.read()
                total_rules_read += 1
        if os.path.isdir(rule_path):
            for rule_file in glob.glob(os.path.join(rule_path, "**/*.yar*"), recursive=True):
                with open(rule_file, encoding="utf-8") as rf:
                    all_patterns += rf.read()
                    total_rules_read += 1
    logger.info(f"Read {total_rules_read} rule files.")

    if manual_yara:
        logger.info("Manual rules provided, added manual Yara rules")
        all_patterns += manual_yara

    if not all_patterns:
        error_msg = "No Yara rules were collected, provide Global and/or manual Yara rules"
        logger.error(error_msg)
        raise ValueError(error_msg)

    all_yara = create_output_file(output_path, display_name="all.yara")
    with open(all_yara.path, "w", encoding="utf-8") as fh:
        fh.write(all_patterns)

    all_matches = []
    fraken_output = create_output_file(output_path, display_name="fraken_out.jsonl")
    output_files.append(fraken_output.to_dict())

    input_files = get_input_files(pipe_result, input_files)

    input_files_map = {}
    for input_file in input_files:
        input_files_map[input_file.get("path", input_file.get("uuid", "UNKNOWN FILE"))] = (
            input_file.get("display_name", "UNKNOWN FILE NAME")
        )

    disks_mounted = []
    try:
        folders_and_files = []
        bd = None
        for input_file in input_files:
            if "path" not in input_file:
                logger.warning("Skipping file %s as it does not have an path", input_file)
                continue

            input_file_path = input_file.get("path")
            # Check if disk image, mount and add mountpoints to scan
            if mount_disk_images and is_disk_image(input_file):
                bd = BlockDevice(input_file_path, min_partition_size=1)
                bd.setup()
                mountpoints = bd.mount()
                disks_mounted.append(bd)

                if not mountpoints:
                    logger.info(
                        "No mountpoints returned for input file %s",
                        input_file.get("display_name"),
                    )
                for mountpoint in mountpoints:
                    folders_and_files.append("--folder")
                    folders_and_files.append(mountpoint)
            else:
                folders_and_files.append("--folder")
                folders_and_files.append(input_file_path)

        cmd = ["fraken"] + folders_and_files + [f"{all_yara.path}"]
        logger.debug(f"fraken-x command: {cmd}")
        with open(fraken_output.path, "w+", encoding="utf-8") as log:
            self.send_event("task-progress")
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.PIPE)
            process.wait()
            if process.stderr:
                # Note: fraken-x uses the eprintln! Rust macro to print progress,
                #       this outputs to stderr....
                logger.info(f"fraken-x: {process.stderr.readlines()}")
    except RuntimeError as e:
        logger.error("Error encountered: %s", str(e))
    finally:
        for blockdevice in disks_mounted:
            if blockdevice:
                logger.debug(f"Unmounting image {blockdevice.image_path}")
                blockdevice.umount()

    with open(fraken_output.path, "r", encoding="utf-8") as json_file:
        matches_list_list = list(json_file)

        for matches_list in matches_list_list:
            matches = json.loads(matches_list)

            for match in matches:
                all_matches.append(
                    YaraMatch(
                        filepath=input_files_map.get(match["ImagePath"], match["ImagePath"]),
                        hash=match["SHA256"],
                        rule=match["Signature"],
                        desc=match["Description"],
                        ref=match["Reference"],
                        score=match["Score"],
                    )
                )

    report = generate_report_from_matches(all_matches)
    report_file = create_output_file(
        output_path,
        display_name="yara-scan-report.md",
        data_type="yara:yara-scan:report",
    )
    with open(report_file.path, "w", encoding="utf-8") as fh:
        fh.write(report.to_markdown())

    output_files.append(report_file.to_dict())

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command="fraken",
        task_report=report.to_dict(),
    )
