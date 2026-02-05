# Copyright 2025 Google LLC
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

"""Exports files and directory archive from container."""

import json
import os
import shutil
from typing import Any
from uuid import uuid4

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common import telemetry
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import OutputFile, create_output_file
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.reporting import MarkdownDocumentSection, Report
from openrelik_worker_common.task_utils import (
    create_task_result,
    get_input_files,
)

from .app import celery
from .container_list import list_containers
from .utils import (
    COMPATIBLE_INPUTS,
    container_root_exists,
    log_entry,
    mount_container,
    unmount_container,
)

# Task name used to register and route the task to the correct queue.
TASK_NAME: str = "openrelik-worker-containers.tasks.container_file_extract"

# Task metadata for registration in the core system.
TASK_METADATA: dict[str, Any] = {
    "display_name": "Container File Extraction",
    "description": "Extract files for directories from a container filesystem",
    "task_config": [
        {
            "name": "container_ids",
            "label": "Containers to extract the files from",
            "description": "Specify the container IDs of the containers for file extraction",
            "type": "Text",
            "required": True,
        },
        {
            "name": "file_paths",
            "label": "Comma separated file paths to extract",
            "description": "Specify the absolute file paths to extract",
            "type": "text",
            "required": True,
        },
    ],
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
def container_file_extraction(
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
    log_root.bind(workflow_id=workflow_id)
    logger.debug("Starting container worker task_id: %s, workflow_id: %s", task_id, workflow_id)

    # Task output files that can be provided to next worker for processing.
    output_files: list[dict] = []

    # Files created by the task that could be useful for user but not used for processing by
    # other workers. For example task log file.
    task_files: list[dict] = []

    # Task log file that containers relevant information for task user.
    # Note: This should not be used to capture debug messages not useful for user.
    log_file: OutputFile = create_output_file(
        output_base_path=output_path,
        display_name="container_file_extraction",
        extension="log",
    )

    task_files.append(log_file.to_dict())

    # Check user provided parameters on server side and return workflow if the required fields are
    # missing.
    container_id_str: str = task_config.get("container_ids", [])
    container_ids: list[str] = [
        container_id.strip() for container_id in container_id_str.split(",")
    ]

    file_path_str: str = task_config.get("file_paths", "")
    file_paths: list[str] = [file_path.strip() for file_path in file_path_str.split(",")]

    report_bullet: list[str] = []

    if not container_ids:
        logger.error("Container IDs not provided. Container ID is required.")
        log_entry(log_file, "Container IDs not provided. Container ID is required.")
        report_bullet.append("Container IDs not provided. Container ID is required.")

    if not file_paths:
        logger.error("File paths not provided.File paths are required.")
        log_entry(log_file, "File paths not provided. File paths are required.")
        report_bullet.append("File paths not provided. File paths are required.")

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
        report_bullet.append("No supported input files provided.")

    if not container_ids or not file_paths or not input_files:
        report: Report = Report("Container File Extraction Report")
        report_section: MarkdownDocumentSection = report.add_section()

        for bullet in report_bullet:
            report_section.add_bullet(bullet)

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

        input_file_name: str = input_file.get("display_name", "unknown")

        try:
            bd: BlockDevice = BlockDevice(image_path=input_file_path, max_mountpath_size=11)
            bd.setup()

            mountpoints: list[str] = bd.mount()
            if not mountpoints:
                logger.info("No mountpoints returned for input file %s", input_file_name)
                bd.umount()
                continue

            for mountpoint in mountpoints:
                logger.debug("Processing mountpoint %s", mountpoint)

                if not container_root_exists(mountpoint):
                    logger.info(
                        "Container root directory does not exist in mount point %s",
                        mountpoint,
                    )
                    continue

                extracted_output_files: list[dict[str, Any]] = run_container_file_extraction(
                    input_file,
                    output_path,
                    log_file,
                    mountpoint,
                    container_ids,
                    file_paths,
                )
                if not extracted_output_files:
                    logger.info("No files extracted from mountpoint %s", mountpoint)
                    continue

                logger.debug(
                    "%d files extracted from mountpoint %s",
                    len(extracted_output_files),
                    mountpoint,
                )
                output_files.extend(extracted_output_files)

        except RuntimeError as e:
            logger.error("Disk mounting error encountered: %s", str(e))

        finally:
            logger.debug("Unmounting disk %s", input_file_path)
            bd.umount()

        logger.debug("Processing input %s completed", input_file_name)
    logger.debug("Completed processing %d input disks", len(input_files))

    logger.debug("%d files extracted from %d input disks", len(output_files), len(input_files))

    report: Report = create_task_report(output_files)

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        task_files=task_files,
        task_report=report.to_dict(),
    )


def create_task_report(output_files: list[dict], content: str = "") -> Report:
    """Create task report"""
    report: Report = Report("Container File Extraction Report")
    report_section: MarkdownDocumentSection = report.add_section()

    if content:
        report_section.add_paragraph(content)

    report_section.add_paragraph(f"{len(output_files)} files extracted.")
    for output_file in output_files:
        display_name: str = output_file.get("display_name", "")
        extension: str = output_file.get("extension", "")

        filename: str = ""
        if extension:
            filename = f"{display_name}.{extension}"
        else:
            filename = f"{display_name}"

        report_section.add_bullet(f"{filename} extracted to {output_file.get('path', '')}")

    return report


def run_container_file_extraction(
    input_file: dict[str, Any],
    output_path: str,
    log_file: OutputFile,
    disk_mountpoint: str,
    container_ids: list[str],
    file_paths: list[str],
) -> list[dict[str, Any]]:
    """Run container file extraction and return output files"""
    input_file_id: str = input_file.get("id", "")
    input_file_name: str = input_file.get("display_name", "unknown")

    # Get the containers IDs in the mountpoint
    containers: dict[str, Any] = _get_containers_info(
        input_file, output_path, log_file, disk_mountpoint
    )
    logger.debug(
        "%d containers found in the input disk %s (%s:%s)",
        len(containers.keys()),
        input_file_name,
        input_file_id,
        disk_mountpoint,
    )
    if not containers:
        logger.debug("No containers in the input disk %s (%s)", input_file_id, disk_mountpoint)
        log_entry(log_file, f"No containers in the input disk {input_file_id}")

        return []

    file_extraction_output_files: list[dict[str, Any]] = []

    for container_id in container_ids:
        logger.debug("Searching for container %s", container_id)

        if container_id not in containers.keys():
            logger.debug(
                "Container %s not in input disk %s (%s)",
                container_id,
                input_file_name,
                disk_mountpoint,
            )
            continue

        logger.debug(
            "Container %s found in input disk %s (%s)",
            container_id,
            input_file_name,
            disk_mountpoint,
        )

        # Create container mountpoint. We need to use shorter mountpoint to avoid reaching mount
        # path limit.
        container_mount_dir: str = os.path.join(output_path, uuid4().hex[:6])
        os.mkdir(container_mount_dir)
        logger.debug("Created container mount directory %s", container_mount_dir)

        container_namespace: str = containers[container_id].get("Namespace", "")
        if not container_namespace:
            logger.info(
                "No defined container namespace for %s. Using default as the namespace",
                container_id,
            )
            container_namespace = "default"

        ret_container_mount_dir: str | None = mount_container(
            container_id, container_namespace, disk_mountpoint, container_mount_dir
        )
        if not ret_container_mount_dir or ret_container_mount_dir != container_mount_dir:
            logger.error(
                "Mounting container %s - Returned container mountpoint is null or does not exist",
                container_id,
            )

            unmount_container(container_id, container_mount_dir)
            continue

        # Container is mounted successfully. Next step is to extract the specified files or directories
        container_output_files: list[dict[str, Any]] = _extract_file_and_directory(
            output_path, container_mount_dir, file_paths
        )
        if not container_output_files:
            logger.debug("No files extracted from container %s", container_id)
            continue

        logger.debug(
            "Extracted %d files from container %s",
            len(container_output_files),
            container_id,
        )
        file_extraction_output_files.extend(container_output_files)

        # Unmount and clean temp directory
        unmount_container(container_id, container_mount_dir)
        shutil.rmtree(container_mount_dir)
        logger.debug("Removed container mount directory %s", container_mount_dir)

    return file_extraction_output_files


def _get_containers_info(
    input_file: dict[str, Any], output_path: str, log_file: OutputFile, mountpoint: str
) -> dict[str, Any]:
    """Get the containers IDs in the mountpoint"""
    container_list_output_file: OutputFile = list_containers(
        input_file, output_path, log_file, mountpoint
    )

    containers: dict[str, Any] = {}

    try:
        with open(container_list_output_file.path, "r", encoding="utf-8") as fh:
            containers_info: list[dict[str, Any]] = json.loads(fh.read())
            if not containers_info:
                logger.debug(
                    "Containers not found in the disk %s",
                    input_file.get("id", "unknown"),
                )
                return {}

            for container_info in containers_info:
                container_id: str = container_info.get("ID", "")
                if container_id:
                    containers[container_id] = container_info
    except FileNotFoundError as e:
        logger.error(
            "Error reading container list file: %s: %s",
            container_list_output_file.path,
            str(e),
        )
        return {}
    except json.decoder.JSONDecodeError as e:
        logger.error(
            "Error decoding container list file: %s: %s",
            container_list_output_file.path,
            str(e),
        )
        return {}

    return containers


def _extract_file_and_directory(
    output_path: str, mountpoint: str, file_paths: list[str]
) -> list[dict[str, Any]]:
    """Extract files from the mountpoint"""
    if not mountpoint or not file_paths:
        logger.debug("No mountpoint or file paths provided")
        return []

    extracted_output_files: list[dict] = []

    for original_path in file_paths:
        logger.debug("Attempting to extract file or directory %s", original_path)

        file_to_extract: str = os.path.join(mountpoint, original_path.strip("/"))
        if not os.path.exists(file_to_extract):
            logger.debug("File or directory %s does not exist", file_to_extract)
            files_in_dir: list[str] = os.listdir(os.path.dirname(file_to_extract))
            logger.debug("Files in directory: %s", ", ".join(files_in_dir))
            continue

        if os.path.isfile(file_to_extract):
            extracted_file: dict[str, Any] = _extract_regular_file(output_path, file_to_extract)
            if extracted_file:
                extracted_output_files.append(extracted_file)
        elif os.path.isdir(file_to_extract):
            extracted_file: dict[str, Any] = _archive_and_extract_directory(
                output_path=output_path,
                file_path=file_to_extract,
                original_path=original_path,
            )

            if extracted_file:
                extracted_output_files.append(extracted_file)
        else:
            logger.info("Unsupported file extraction")

    return extracted_output_files


def _extract_regular_file(
    output_path: str, file_path: str, original_path: str = ""
) -> dict[str, Any]:
    """Extract a regular file"""
    logger.debug("Extracting a regular file %s", file_path)

    file_name: str = os.path.basename(file_path)
    file_name_no_extension: str = os.path.splitext(file_name)[0]
    file_extension: str = os.path.splitext(file_name)[1][1:]

    output_file: OutputFile = create_output_file(
        output_base_path=output_path,
        display_name=file_name_no_extension,
        extension=file_extension,
    )

    if original_path:
        output_file.original_path = original_path

    try:
        shutil.copy(file_path, output_file.path)
    except FileNotFoundError:
        logger.error("File %s not found", file_path)
        return {}
    except shutil.Error as e:
        logger.error("Error copying the file %s: %s", file_path, str(e))
        return {}

    logger.debug("Extracted file %s to %s", file_path, output_file.path)
    return output_file.to_dict()  # default return


def _archive_and_extract_directory(
    output_path: str,
    file_path: str,
    original_path: str = "",
    archive_format: str = "tar",
) -> dict[str, Any]:
    """Archive and extract the archive directory."""
    logger.debug("Archiving and extracting directory %s", file_path)

    dir_name: str = os.path.basename(file_path)

    output_file: OutputFile = create_output_file(
        output_base_path=output_path,
        display_name=dir_name,
        original_path=original_path,
        extension="tar",
    )

    root_dir: str = os.path.dirname(file_path)
    base_dir: str = os.path.basename(file_path)
    archive_base_name: str = os.path.splitext(output_file.path)[0]

    try:
        archive_path: str = shutil.make_archive(
            base_name=archive_base_name,
            format=archive_format,
            root_dir=root_dir,
            base_dir=base_dir,
        )
        logger.debug("Successfully archived directory %s to %s", file_path, archive_path)
    except FileNotFoundError:
        logger.error("Root directory %s for archiving not found.", root_dir)
        return {}
    except Exception as e:
        logger.error("Error archiving directory %s: %s", file_path, str(e))
        return {}

    return output_file.to_dict()  # default return
