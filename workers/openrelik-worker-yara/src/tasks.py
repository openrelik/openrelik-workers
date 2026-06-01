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
from openrelik_worker_common.file_utils import (
    create_output_file,
    is_disk_image,
    OutputFile,
)
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


@dataclass
class SkippedInput:
    """Dataclass to store skipped Yara input information."""

    input_name: str
    reason: str


def validate_scan_target(path: str, display_name: str = "input") -> None:
    """Reject scan targets that would silently scan the worker container."""
    if not path:
        raise RuntimeError("Input file path is empty.")
    if os.path.abspath(path) == os.path.sep:
        raise RuntimeError(
            "Refusing to scan filesystem root as Yara input. "
            "Select a file or folder input instead."
        )
    if not os.path.exists(path):
        raise RuntimeError(f"Input path does not exist: {path}")
    if not (os.path.isfile(path) or os.path.isdir(path)):
        raise RuntimeError(
            f"Unsupported Yara scan target: {display_name}. "
            "The Yara worker can scan regular files and directories. "
            "Disk images must be mounted before scanning."
        )


def send_progress(task, status: str, progress: str | None = None) -> None:
    """Send task progress text for the OpenRelik UI."""
    data = {"status": status}
    if progress:
        data["progress"] = progress
    task.send_event("task-progress", data=data)


def cleanup_fraken_output_log(logfile: OutputFile) -> None:
    """Cleanup fraken-x output to be one entry per line.

    Args:
        logfile: Output file created by fraken-x

    Returns:
        None
    """
    extracted_dicts = []
    try:
        with open(logfile.path, "r") as f:
            for line in f:
                line = line.strip()
                try:
                    data = json.loads(line)
                    if isinstance(data, list) and len(data) > 0:
                        for entry in data:
                            extracted_dicts.append(entry)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Incorrect fraken-x JSON line found: could not parse: {line}"
                    )
                    continue
    except FileNotFoundError:
        logger.warning("Could not find fraken-x outputfile.")
        return

    with open(logfile.path, "w") as f:
        if not extracted_dicts:
            f.write("[]")
        else:
            json.dump(extracted_dicts, f)


def generate_report_from_matches(
    matches: list[YaraMatch], skipped_inputs: list[SkippedInput] | None = None
) -> Report:
    """Generate a report from Yara matches.

    Args:
        matches: List of YaraMatch objects.
        skipped_inputs: List of skipped input files and the reason they were skipped.

    Returns:
        Report object.
    """
    skipped_inputs = skipped_inputs or []
    report = Report("Yara scan report")
    report.summary = f"{len(matches)} Yara match(es) found."
    if skipped_inputs:
        report.summary += f" {len(skipped_inputs)} input(s) skipped."

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

    if skipped_inputs:
        skipped_section = report.add_section()
        skipped_section.add_header("Skipped inputs")
        skipped_section.add_paragraph(
            "Inputs that were not scanned because they were not valid scan targets."
        )
        skipped_table = MarkdownTable(["input", "reason"])
        for skipped_input in skipped_inputs:
            skipped_table.add_row([skipped_input.input_name, skipped_input.reason])
        skipped_section.add_table(skipped_table)

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
    task_files = []

    all_patterns = ""
    global_yara = task_config.get("Global Yara rules", "")
    manual_yara = task_config.get("Manual Yara rules", "")
    mount_disk_images = task_config.get("mount_disk_images", False)

    # If the environment variable YARA_RULES_FOLDER is set, add it to the global Yara rules
    env_yara = os.getenv("OPENRELIK_YARA_RULES_FOLDER", "")
    if env_yara:
        logger.info(
            f"Environment variable YARA_RULES_FOLDER provided, added {env_yara} to global Yara rules"
        )
        if not global_yara:
            global_yara = f"{env_yara}"
        else:
            global_yara += f"\n{env_yara}"

    if not global_yara and not manual_yara and not env_yara:
        error_msg = (
            "At least one of Environment, Global or Manual Yara rules must be provided"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    total_rules_read = 0
    for rule_path in global_yara.split("\n"):
        if os.path.isfile(rule_path):
            with open(rule_path, encoding="utf-8") as rf:
                all_patterns += rf.read()
                total_rules_read += 1
        if os.path.isdir(rule_path):
            for rule_file in glob.glob(
                os.path.join(rule_path, "**/*.yar*"), recursive=True
            ):
                with open(rule_file, encoding="utf-8") as rf:
                    all_patterns += rf.read()
                    total_rules_read += 1
    logger.info(f"Read {total_rules_read} rule files.")

    if manual_yara:
        logger.info("Manual rules provided, added manual Yara rules")
        all_patterns += manual_yara

    if not all_patterns:
        error_msg = (
            "No Yara rules were collected, provide Global and/or manual Yara rules"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    all_yara = create_output_file(output_path, display_name="all.yara")
    with open(all_yara.path, "w", encoding="utf-8") as fh:
        fh.write(all_patterns)

    all_matches = []
    fraken_output = create_output_file(
        output_path, display_name="fraken_out.jsonl", data_type="yara:yara-scan:jsonl"
    )
    fraken_stderr = create_output_file(
        output_path,
        display_name="fraken_stderr.log",
        data_type="yara:yara-scan:log",
    )
    output_files.append(fraken_output.to_dict())
    task_files.append(fraken_stderr.to_dict())

    input_files = get_input_files(pipe_result, input_files or [])
    if not input_files:
        raise RuntimeError("No input files were provided to Yara scan.")

    input_files_map = {}
    for input_file in input_files:
        input_files_map[
            input_file.get("path", input_file.get("uuid", "UNKNOWN FILE"))
        ] = input_file.get("display_name", "UNKNOWN FILE NAME")

    disks_mounted = []
    try:
        folders_and_files = []
        skipped_inputs = []
        bd = None
        for input_file in input_files:
            if "path" not in input_file:
                skipped_inputs.append(
                    SkippedInput(
                        input_file.get("display_name", "UNKNOWN FILE"),
                        "Input does not have a path.",
                    )
                )
                logger.warning(
                    "Skipping file %s as it does not have an path", input_file
                )
                continue

            input_file_path = input_file.get("path")
            display_name = input_file.get("display_name", input_file_path)
            try:
                validate_scan_target(input_file_path, display_name)
            except RuntimeError as e:
                skipped_inputs.append(SkippedInput(display_name, str(e)))
                logger.error(
                    "Skipping Yara scan input %s (%s): %s",
                    display_name,
                    input_file_path,
                    str(e),
                )
                continue

            # Check if disk image, mount and add mountpoints to scan
            if is_disk_image(input_file):
                if not mount_disk_images:
                    reason = (
                        "Disk image input is not supported in regular scan mode. "
                        "Enable mount_disk_images to scan files inside supported "
                        "disk image filesystems."
                    )
                    skipped_inputs.append(SkippedInput(display_name, reason))
                    logger.error(
                        "%s: %s",
                        display_name,
                        reason,
                    )
                    continue

                try:
                    send_progress(self, "Mounting disk image", display_name)
                    bd = BlockDevice(input_file_path, min_partition_size=1)
                    bd.setup()
                    disks_mounted.append(bd)
                    mountpoints = bd.mount()
                    send_progress(
                        self,
                        "Mounted disk image",
                        f"{display_name}: {len(mountpoints)} mountpoint(s)",
                    )
                except RuntimeError as e:
                    logger.error(
                        "Error mounting disk image %s (%s): %s",
                        display_name,
                        input_file_path,
                        str(e),
                    )
                    skipped_inputs.append(
                        SkippedInput(
                            display_name,
                            "Disk image input is not supported or could not be "
                            "mounted by the Yara worker.",
                        )
                    )
                    continue

                if not mountpoints:
                    skipped_inputs.append(
                        SkippedInput(
                            input_file.get("display_name", input_file_path),
                            "No mountpoints returned for input file.",
                        )
                    )
                    logger.error(
                        "No mountpoints returned for input file %s",
                        input_file.get("display_name"),
                    )
                    continue
                for mountpoint in mountpoints:
                    try:
                        validate_scan_target(mountpoint, display_name)
                    except RuntimeError as e:
                        skipped_inputs.append(
                            SkippedInput(f"{display_name}: {mountpoint}", str(e))
                        )
                        logger.error(
                            "Skipping Yara scan mountpoint %s for %s: %s",
                            mountpoint,
                            display_name,
                            str(e),
                        )
                        continue
                    folders_and_files.append("--folder")
                    folders_and_files.append(mountpoint)
            else:
                folders_and_files.append("--folder")
                folders_and_files.append(input_file_path)

        if not folders_and_files:
            message = "No scan targets were produced from input files."
            if skipped_inputs:
                last_skipped_input = skipped_inputs[-1]
                message = (
                    f"{message} Last skipped input error: "
                    f"{last_skipped_input.input_name}: {last_skipped_input.reason}"
                )
            raise RuntimeError(message)

        cmd = ["fraken"] + folders_and_files + [f"{all_yara.path}"]
        logger.info(
            "fraken-x scan targets: %s",
            folders_and_files[1::2],
        )
        logger.debug(f"fraken-x command: {cmd}")
        with (
            open(fraken_output.path, "w+", encoding="utf-8") as log,
            open(fraken_stderr.path, "w+", encoding="utf-8") as stderr_log,
        ):
            send_progress(self, "Running Yara scan")
            process = subprocess.run(
                cmd,
                stdout=log,
                stderr=stderr_log,
                check=False,
                text=True,
            )

        if os.path.getsize(fraken_stderr.path) > 0:
            logger.info(f"fraken-x stderr written to {fraken_stderr.path}")

        if process.returncode != 0:
            raise RuntimeError(
                "An error occurred while running fraken-x. "
                f"Exit code: {process.returncode}. "
                f"See stderr log for details: {fraken_stderr.path}"
            )
    except RuntimeError as e:
        logger.error("Error encountered: %s", str(e))
        raise
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
                        filepath=input_files_map.get(
                            match["ImagePath"], match["ImagePath"]
                        ),
                        hash=match["SHA256"],
                        rule=match["Signature"],
                        desc=match["Description"],
                        ref=match["Reference"],
                        score=match["Score"],
                    )
                )

    cleanup_fraken_output_log(fraken_output)

    report = generate_report_from_matches(all_matches, skipped_inputs)
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
        task_files=task_files,
        workflow_id=workflow_id,
        command="fraken",
        task_report=report.to_dict(),
    )
