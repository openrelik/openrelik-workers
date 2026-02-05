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

"""List containers on disk."""

import json
import os
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common import telemetry
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import OutputFile, create_output_file
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.reporting import (
    MarkdownDocument,
    MarkdownDocumentSection,
    MarkdownTable,
    Report,
)
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .utils import CE_BINARY, COMPATIBLE_INPUTS, container_root_exists, log_entry

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-containers.tasks.container_list"

# Task metadata for registration in the core system.
TASK_METADATA: dict[str, Any] = {
    "display_name": "ContainerExplorer: List Containers",
    "description": "List containerd and Docker containers",
}

log_root = Logger()
logger = log_root.get_logger(__name__, get_task_logger(__name__))


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def container_list(
    self,
    pipe_result: str = None,
    input_files: list[dict] = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict[str, Any] = None,
) -> str:
    """List containers on a disk.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    task_id: str = self.request.id
    log_root.bind(workflow_id=workflow_id)
    logger.info("Starting task (%s) in workflow (%s) to list containers", task_id, workflow_id)

    input_files = get_input_files(pipe_result, input_files or [], filter=COMPATIBLE_INPUTS)
    output_files: list[dict] = []

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    # task_files contains dict of OutputFile for local use only.
    task_files: list[dict] = []

    # Log file to capture logs.
    log_file: OutputFile = create_output_file(
        output_path,
        extension="log",
        display_name="container_list",
    )
    task_files.append(log_file.to_dict())

    if not input_files:
        logger.warning("No supported input file extensions.")
        log_entry(log_file, "No supported input file extensions.")

        report: Report = create_task_report(output_files)

        return create_task_result(
            workflow_id=workflow_id,
            output_files=output_files,
            task_files=task_files,
            task_report=report.to_dict(),
        )

    # Indicate task progress start.
    self.send_event("task-progress")

    for input_file in input_files:
        input_file_id: str = input_file.get("id", "")
        input_file_path: str = input_file.get("path", "")

        try:
            bd = BlockDevice(input_file_path, max_mountpath_size=11)
            bd.setup()

            mountpoints: list[str] = bd.mount()
            if not mountpoints:
                logger.info("No mountpoints returned for disk %s", input_file_id)
                logger.info("Unmounting the disk %s", input_file_id)

                bd.umount()

                # Skipping current input_file.
                continue

            # Process each mountpoint looking for containers
            for mountpoint in mountpoints:
                logger.debug("Processing mountpoint %s for disk %s", mountpoint, input_file_id)

                # Only process the mountpoint containing valid containerd or Docker root directory.
                if not container_root_exists(mountpoint):
                    logger.debug(
                        "Container root directory does not exist in mount point %s",
                        mountpoint,
                    )
                    log_entry(
                        log_file,
                        f"Container directory not found in disk {input_file_id}",
                    )
                    continue

                output_file: OutputFile | None = list_containers(
                    input_file, output_path, log_file, mountpoint
                )
                if not output_file:
                    logger.debug("No containers on disk %s", input_file_id)
                    log_entry(log_file, f"No containers in disk {input_file_id}")
                    continue

                output_files.append(output_file.to_dict())

        except RuntimeError:
            logger.error("Encountered unexpected error while processing disk %s", input_file_id)
        finally:
            logger.debug("Unmounting disk %s", input_file_id)
            log_entry(log_file, f"Done processing {input_file.get('path', '')}")
            bd.umount()

        logger.debug("Completed processing %d input disks", len(input_files))

    markdown_report: OutputFile = create_markdown_report(output_path, output_files)
    output_files.append(markdown_report.to_dict())

    report: Report = create_task_report(output_files, markdown_report.path)

    return create_task_result(
        workflow_id=workflow_id,
        output_files=output_files,
        task_files=task_files,
        task_report=report.to_dict(),
    )


def create_task_report(output_files: list[dict], content_filepath: str = "") -> Report:
    """Create and return container list report."""
    logger.debug("Creating task report")

    report: Report = Report("Container List Report")
    summary: MarkdownDocumentSection = report.add_section()

    if content_filepath:
        with open(content_filepath, "r", encoding="utf-8") as fh:
            summary.add_paragraph(fh.read())

    return report


def create_markdown_report(output_path: str, output_files: list[dict]) -> OutputFile:
    """Create and return a markdown container list."""
    logger.debug("Creating list container markdown report")

    markdown_output_file: OutputFile = create_output_file(
        output_path, display_name="container_list", extension="md"
    )

    mdreport = MarkdownDocument(title="Container Listing")
    table_section: MarkdownDocumentSection = mdreport.add_section()

    report_table = MarkdownTable(
        columns=[
            "Namespace",
            "ID",
            "Hostname",
            "Image",
            "Container Runtime",
            "Created",
            "Updated",
        ]
    )

    for output_file in output_files:
        containers_info: list[dict[str, Any]] = _read_json_file(output_file.get("path", ""))
        for container_info in containers_info:
            _namespace = container_info.get("Namespace", "")
            _id: str = container_info.get("ID", "")
            _hostname: str = container_info.get("Hostname", "")
            _image: str = container_info.get("Image", "")
            _container_runtime: str = container_info.get("ContainerType", "")
            _created: str = container_info.get("CreatedAt", "")
            _updated: str = container_info.get("UpdatedAt", "")

            report_table.add_row(
                row_data=[
                    _namespace,
                    _id,
                    _hostname,
                    _image,
                    _container_runtime,
                    _created,
                    _updated,
                ]
            )

    table_section.add_table(report_table)

    with open(markdown_output_file.path, "w", encoding="utf-8") as fh:
        fh.write(mdreport.to_markdown())

    return markdown_output_file


def list_containers(
    input_file: dict[str, Any], output_path: str, log_file: OutputFile, mountpoint: str
) -> OutputFile:
    """Returns an output file with container list information."""
    temp_dir: str = os.path.join(output_path, uuid4().hex)
    os.mkdir(temp_dir)
    logger.debug(
        "Created temporary directory to store container list output files: %s.",
        temp_dir,
    )

    containers_info: list[dict] = []

    containerd_output_file: OutputFile = create_output_file(
        temp_dir,
        display_name="containerd_container_list",
        extension="json",
        source_file_id=input_file.get("id"),
    )

    _list_containerd_containers(mountpoint, containerd_output_file.path)

    containerd_containers_info: list[dict[str, Any]] = _read_json_file(containerd_output_file.path)
    if containerd_containers_info:
        containers_info.extend(containerd_containers_info)

    docker_output_file: OutputFile = create_output_file(
        temp_dir,
        display_name="docker_container_list",
        extension="json",
        source_file_id=input_file.get("id"),
    )

    _list_docker_containers(mountpoint, docker_output_file.path)

    docker_containers_info: list[dict[str, Any]] = _read_json_file(docker_output_file.path)
    if docker_containers_info:
        containers_info.extend(docker_containers_info)

    output_file: OutputFile = create_output_file(
        output_path,
        display_name="container_list",
        extension="json",
        source_file_id=input_file.get("id"),
    )
    _write_json_file(output_file.path, containers_info)

    # Cleanup
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    return output_file


def _list_containerd_containers(mountpoint: str, container_output_file: str) -> None:
    """List containerd containers and save to output file."""
    command: list[str] = [
        CE_BINARY,
        "--image-root",
        mountpoint,
        "--output-file",
        container_output_file,
        "--output",
        "json",
        "list",
        "containers",
    ]

    try:
        logger.debug("Running container explorer command: %s", " ".join(command))
        process: subprocess.CompletedProcess[str] = subprocess.run(
            command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            logger.debug("Successfully listed containerd containers at %s", mountpoint)
        else:
            logger.error("Container explorer failed listing containers at %s", mountpoint)
    except subprocess.CalledProcessError as err:
        logger.debug("Error running container explorer process: %s", str(err))


def _list_docker_containers(mountpoint: str, container_output_file: str) -> None:
    """List Docker containers and save to output file."""
    command: list[str] = [
        CE_BINARY,
        "--docker-managed",
        "--image-root",
        mountpoint,
        "--output-file",
        container_output_file,
        "--output",
        "json",
        "list",
        "containers",
    ]

    try:
        logger.debug("Running container explorer command: %s", " ".join(command))
        process: subprocess.CompletedProcess[str] = subprocess.run(
            command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            logger.debug("Successfully listed Docker containers at %s", mountpoint)
        else:
            logger.error("Container explorer failed listing containers at %s", mountpoint)
    except subprocess.CalledProcessError as err:
        logger.debug("Error running container explorer process: %s", str(err))


def _read_json_file(path: str) -> list[dict]:
    """Reads JSON file.

    Args:
        path: JSON file.

    Returns:
        Returns the content of json file.
    """
    if not os.path.exists(path):
        return []

    data: list[dict] = []

    with open(path, "r", encoding="utf-8") as file_handler:
        try:
            data = json.loads(file_handler.read())
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            return []

    return data


def _write_json_file(path: str, data: list[dict[str, Any]]) -> None:
    """Write JSON data."""
    with open(path, "w", encoding="utf-8") as file_handler:
        json.dump(data, file_handler, indent=4)
