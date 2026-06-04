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

"""Shows filesystem files and directories changes in containers."""

import csv
import json
import logging
import os
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from openrelik_common import telemetry
from openrelik_worker_common.file_utils import OutputFile, create_output_file
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.reporting import MarkdownDocumentSection, Report
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .utils import CE_BINARY, COMPATIBLE_INPUTS, container_root_exists, log_entry

# Setting up task logger
logger: logging.Logger = logging.getLogger(__name__)

# Task name used to register and route the task to the correct queue.
TASK_NAME: str = "openrelik-worker-containers.tasks.container_drift"

# Task metadata for registration in the core system.
TASK_METADATA: dict[str, Any] = {
    "display_name": "Container Drift",
    "description": "Shows filesystem files and directories changes in containers",
}


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def container_drift(
    self,
    pipe_result: str = None,
    input_files: list[dict] = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict[str, Any] = None,
) -> str:
    """Checks for drifts in containers.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: list of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    task_id: str = self.request.id
    logger.debug(
        "Starting containers worker task: task_id=%s, workflow_id: %s",
        task_id,
        workflow_id,
    )

    # Task output files that can be provided to next worker for processing.
    output_files: list[dict] = []

    # Files created by the task that could be useful for user but not used for processing by
    # other workers. For example task log file.
    task_files: list[dict] = []

    # Task log file that containers relevant information for task user.
    # Note: This should not be used to capture debug messages not useful for user.
    log_file: OutputFile = create_output_file(
        output_base_path=output_path,
        display_name="container_drift",
        extension="log",
    )

    task_files.append(log_file.to_dict())

    # Get input files compatible with containers worker i.e. input files with extensions like
    # .raw, .dd, .img, .qcow, .qcow2, .qcow3, etc.
    input_files = get_input_files(
        pipe_result=pipe_result, input_files=input_files or [], filter=COMPATIBLE_INPUTS
    )

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    if not input_files:
        logger.warning("No supported input files provided.")
        log_entry(log_file, "No supported input files provided.")

        report: Report = Report("Container Drift Report")
        report.add_section().add_paragraph("No supported input files provided")

        return create_task_result(
            output_files=output_files,
            workflow_id=workflow_id,
            task_files=task_files,
            task_report=report.to_dict(),
        )

    # Indicate task progress start.
    self.send_event("task-progress")

    for input_file in input_files:
        input_file_path: str = input_file.get("path", "")
        if not input_file_path:
            logger.error("No path for the input file.")
            log_entry(log_file, "No path for input file.")
            continue

        try:
            # Using shorter mountpoint like /mnt/abcdef.
            # Overlay mount layers can get large and reach mount option limit of 4KB.
            bd: BlockDevice = BlockDevice(image_path=input_file_path, max_mountpath_size=11)
            bd.setup()

            mountpoints: list[str] = bd.mount()
            if not mountpoints:
                logger.info("No mountpoints returned for input file")
                bd.umount()
                continue

            # Process each mountpoint and check for containers.
            for mountpoint in mountpoints:
                logger.debug("Processing mountpoint %s", mountpoint)

                if not container_root_exists(mountpoint):
                    logger.info("No container root directory in the mountpoint %s", mountpoint)
                    continue

                drift_data: list[dict] = run_container_drift(
                    input_file, output_path, log_file, mountpoint
                )
                if not drift_data:
                    logger.info("No container drift for containers in mountpoint %s", mountpoint)
                    log_entry(log_file, "No container drift for containers in input file.")
                    continue

                drift_output_files: list[dict] = _create_drift_output_files(output_path, drift_data)
                output_files.extend(drift_output_files)

        except RuntimeError as e:
            logger.error("Disk mounting error encountered: %s", str(e))
        finally:
            logger.debug("Unmounting disk %s", input_file_path)
            log_entry(log_file, f"Done processing {input_file_path}")
            bd.umount()
        logger.debug("Proceessing input %s completed", input_file_path)

    report: Report = create_task_report(output_files)

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        task_files=task_files,
        task_report=report.to_dict(),
    )


def create_task_report(output_files: list[dict], content: str = "") -> Report:
    """Creates task report"""
    report: Report = Report("Container Drift Report")
    report_section: MarkdownDocumentSection = report.add_section()

    report_section.add_bullet(f"{len(output_files)} output files created")

    record_count: int = 0

    for output_file in output_files:
        output_file_path: str = output_file.get("path", "")
        if not output_file_path:
            logger.info("No file path to process")
            continue

        if ".json" not in output_file_path:
            continue

        with open(output_file_path, "r", encoding="utf-8") as json_file:
            data: list[dict] = json.loads(json_file.read())
            record_count += len(data)

    report_section.add_bullet(f"{record_count} files added, modified, or deleted")

    if content:
        report.add_section().add_paragraph(content)

    return report


def _create_drift_output_files(output_path: str, data: list[dict]) -> list[dict]:
    """Returns OutpuFile for container drift."""
    if not data:
        logger.info("Creating drift output - no data provided")
        return []

    drift_output_files: list[dict] = []

    json_output_file: OutputFile = create_output_file(
        output_base_path=output_path, display_name="container_drift", extension="json"
    )
    with open(json_output_file.path, "w", encoding="utf-8") as file_handler:
        json.dump(data, file_handler)
    drift_output_files.append(json_output_file.to_dict())

    csv_output_file: OutputFile = create_output_file(
        output_base_path=output_path, display_name="container_drift", extension="csv"
    )
    with open(csv_output_file.path, "w", newline="") as csvfile:
        csv_writer = csv.writer(csvfile)
        if isinstance(data, list):
            header = data[0].keys()
            csv_writer.writerow(header)

            for row in data:
                csv_writer.writerow(row.values())
    drift_output_files.append(csv_output_file.to_dict())

    return drift_output_files


def run_container_drift(
    input_file: dict[str, Any], output_path: str, log_file: OutputFile, mountpoint: str
) -> list[dict]:
    """Run container drift on input file and return container drift data."""
    drift_data: list[dict] = []

    # Temporary directory to save the container drift output file produced by container-explorer
    temp_dir: str = os.path.join(output_path, uuid4().hex)
    os.mkdir(temp_dir)
    logger.debug("Created temp directory to store container drift output %s", temp_dir)

    # TODO(rmaskey): Update container-explorer to run container drift on Docker and containerd using
    # single command.
    #
    # container drift must be run for containerd and Docker separately.
    containerd_drift_data: list[dict] = _run_containerd_drift(mountpoint, temp_dir)
    if containerd_drift_data:
        drift_data.extend(containerd_drift_data)

    docker_drift_data: list[dict] = _run_docker_drift(mountpoint, temp_dir)
    if docker_drift_data:
        drift_data.extend(docker_drift_data)

    # Clean up temporary directory
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    return drift_data


def _run_containerd_drift(mountpoint: str, temp_dir: str) -> list[dict]:
    """Run containerd drift and return drift data."""
    output_file: OutputFile = create_output_file(
        output_base_path=temp_dir, display_name="containerd_drift", extension="json"
    )

    command: list[str] = [
        CE_BINARY,
        "--image-root",
        mountpoint,
        "--output-file",
        output_file.path,
        "--output",
        "json",
        "drift",
    ]

    return _run_container_explorer(command, output_file.path)


def _run_docker_drift(mountpoint: str, temp_dir: str) -> list[dict]:
    """Run containerd drift and return drift data."""
    output_file: OutputFile = create_output_file(
        output_base_path=temp_dir, display_name="docker_drift", extension="json"
    )

    command: list[str] = [
        CE_BINARY,
        "--docker-managed",
        "--image-root",
        mountpoint,
        "--output-file",
        output_file.path,
        "--output",
        "json",
        "drift",
    ]

    return _run_container_explorer(command, output_file.path)


def _run_container_explorer(command: list[str], output_file_path: str) -> list[dict]:
    """Run container-explorer and return the output."""
    try:
        logger.debug("Running container-explorer command: %s", " ".join(command))

        process: subprocess.CompletedProcess = subprocess.run(
            command, capture_output=True, check=False, text=True
        )
        if process.returncode != 0:
            logger.error("container-explorer ran with error: %s", process.stderr)
            return []

        logger.debug("container-explorer ran successfully")
        return _get_container_drift_data(output_file_path)

    except subprocess.CalledProcessError as e:
        logger.error("Error running container-explorer command: %s", str(e))
        return []


def _get_container_drift_data(path: str) -> list[dict]:
    """Returns container drift data on file."""
    try:
        with open(path, "r", encoding="utf-8") as file_handler:
            data: list[dict] = json.loads(file_handler.read())
            return _flattern_container_drift_data(data)
    except FileNotFoundError as e:
        logger.error("File %s container container drift output does not exist: %s", path, str(e))
        return []
    except json.decoder.JSONDecodeError as e:
        logger.error("Error loading container drift output from %s: %s", path, str(e))
        return []


def _flattern_container_drift_data(data: list[dict]) -> list[dict]:
    """Reads nested container drift data and returns the flattern dict."""
    if not data:
        logger.debug("No data provided to process.")
        return []

    drift_data: list[dict] = []

    for item in data:
        container_id: str = item.get("ContainerID", "")
        container_type: str = item.get("ContainerType", "")

        added_or_modified_files: list[dict] | None = item.get("AddedOrModified")

        # Handling edge cases where added_or_modified_files may container unexpected data.
        if added_or_modified_files and isinstance(added_or_modified_files, list):
            for file_info in added_or_modified_files:
                drift_data.append(
                    _create_drift_record(
                        container_id,
                        container_type,
                        "File added or modified",
                        file_info,
                    )
                )

        inaccessible_files: list[dict] | None = item.get("InaccessibleFiles")

        # Handling edge cases where inaccessible_files may container unexpected data.
        if inaccessible_files and isinstance(inaccessible_files, list):
            for file_info in inaccessible_files:
                drift_data.append(
                    _create_drift_record(container_id, container_type, "File deleted", file_info)
                )

    return drift_data


def _create_drift_record(
    container_id: str, container_type: str, drift_status: str, file_info: dict
) -> dict:
    """Create and return drift record."""
    # Adding "-" for missing fields so exporting to csv is aligned.
    file_name: str = file_info.get("file_name", "-")
    full_path: str = file_info.get("full_path", "-")
    file_size: str = str(file_info.get("file_size", "-"))
    file_type: str = file_info.get("file_type", "-")
    file_modified: str = file_info.get("file_modified", "-")
    file_accessed: str = file_info.get("file_accessed", "-")
    file_changed: str = file_info.get("file_changed", "-")
    file_birth: str = file_info.get("file_birth", "-")
    file_sha256: str = file_info.get("file_sha256", "-")

    return {
        "container_id": container_id,
        "container_type": container_type,
        "drift_status": drift_status,
        "file_name": file_name,
        "file_path": full_path,
        "file_size": file_size,
        "file_type": file_type,
        "file_modified": file_modified,
        "file_accessed": file_accessed,
        "file_changed": file_changed,
        "file_birth": file_birth,
        "file_sha256": file_sha256,
    }
