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

"""Exports container to a `.raw` disk image or `.tar.gz` archive."""

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
from openrelik_worker_common.reporting import MarkdownDocumentSection, Report
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .utils import CE_BINARY, container_root_exists, log_entry

# Container worker expects input file is a disk image with one of the following file extensions
# specified in "filenames". Input files without expected file extensions are not processed.
COMPATIBLE_INPUTS: dict[str, Any] = {
    "data_types": [],
    "mime_types": [],
    "filenames": ["*.img", "*.raw", "*.dd", "*.qcow3", "*.qcow2", "*.qcow"],
}

# Container-Explorer exported output file extensions.
_DISK_EXT = ".raw"  # Created when --image flag is used.
_ARCHIVE_EXT = ".tar.gz"  # Created when --archive flag is used.

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-containers.tasks.container_export"

# Task metadata for registration in the core system.
TASK_METADATA: dict[str, Any] = {
    "display_name": "Containers: Export Container",
    "description": (
        "Exports a container to either a raw disk image or an archive. If no container "
        "ID is specified, all containers will be exported. By default, the export "
        "format is an image unless other options are provided. Containers residing in "
        "the Kubernetes namespace `kube-system` are automatically excluded from the "
        "export process."
    ),
    "task_config": [
        {
            "name": "container_id",
            "label": "Container ID to export",
            "description": (
                "Specify the comma-separated IDs of containers for export. If this is"
                " left blank, all containers will be exported."
            ),
            "type": "Text",
            "required": False,
        },
        {
            "name": "export_image",
            "label": "Export container as disk image (.raw).",
            "description": "Create a disk image from a container.",
            "type": "checkbox",
        },
        {
            "name": "export_archive",
            "label": "Export container as archive (.tar.gz).",
            "description": "Create a archive (tar.gz) from a container.",
            "type": "checkbox",
        },
        {
            "name": "filter",
            "label": "Filter containers using container labels.",
            "description": (
                "To filter and export containers, use key-value container labels in the"
                " format of `key=value`. For example: `io.kubernetes.pod.namespace=appspace`."
            ),
            "type": "Text",
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


def export_container(
    input_file: dict[str, Any],
    output_path: str,
    log_file: OutputFile,
    disk_mount_dir: str,
    container_id: str,
    task_config: dict[str, str],
) -> list[OutputFile]:
    """Exports container as disk image or an archive file."""
    logger.info("Attempting to export container ID: %s", container_id)

    container_export_dir: str = os.path.join(output_path, uuid4().hex)
    os.mkdir(container_export_dir)
    logger.debug("Created container export directory %s", container_export_dir)

    # TODO (rmaskey): Add support for non-default container root directory.
    export_command: list[str] = [
        CE_BINARY,
        "--support-container-data",
        "/opt/container-explorer/etc/supportcontainer.yaml",
        "--image-root",
        disk_mount_dir,
        "export",
        container_id,
        container_export_dir,
    ]

    # Container-Explorer binary supports exporting as disk image and .tar.gz archive.
    # Building the export type based on user selection.
    if task_config.get("export_image"):
        export_command.append("--image")
    if task_config.get("export_archive"):
        export_command.append("--archive")

    # Using default if user did not selection an export type.
    if "--image" not in export_command and "--archive" not in export_command:
        export_command.append("--image")

    output_files: list[OutputFile] = []
    logger.debug("Running container-explorer export command %s", " ".join(export_command))

    try:
        process: subprocess.CompletedProcess[str] = subprocess.run(
            export_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            exported_containers: list[str] = os.listdir(container_export_dir)
            for exported_container in exported_containers:
                logger.debug(
                    "Exported container %s in export directory %s",
                    exported_container,
                    container_export_dir,
                )

                output_file: OutputFile = create_output_file(
                    output_path,
                    display_name=exported_container,
                    data_type="image",
                    extension=exported_container.split(".")[-1],
                    source_file_id=input_file.get("id"),
                )

                # Converting ContainerExplorer generated output file to OpenRelik compatible name
                # and location.
                shutil.move(
                    os.path.join(container_export_dir, exported_container),
                    output_file.path,
                )

                # Fix double extension in display_name
                output_file.display_name = exported_container

                logger.info(f"Exporting container {container_id} as {output_file.path}")
                log_entry(
                    log_file,
                    f"Exporting container {container_id} as {exported_container}",
                )

                output_files.append(output_file)
        else:
            _log_message: str = f"Error exporting container {container_id}"
            logger.error(_log_message)
            log_entry(log_file, _log_message)
    except subprocess.CalledProcessError as err:
        logger.error("Error calling container-explorer command: %s", str(err))
    finally:
        # Clean up temporary folder
        shutil.rmtree(container_export_dir)
        logger.debug("Deleted container export directory %s", container_export_dir)

    return output_files


def export_all_containers(
    input_file: dict[str, Any],
    output_path: str,
    log_file: OutputFile,
    disk_mount_dir: str,
    task_config: dict[str, str],
) -> list[OutputFile]:
    """Exports all containers disk image (.raw) or archive (.tar.gz)."""
    logger.info("Attempting to export all containers on disk mounted at %s", disk_mount_dir)

    container_export_dir: str = os.path.join(output_path, uuid4().hex)
    os.mkdir(container_export_dir)
    logger.debug("Created container export directory %s", container_export_dir)

    # TODO (rmaskey): Add support for non-default container root directory.
    export_command: list[str] = [
        CE_BINARY,
        "--support-container-data",
        "/opt/container-explorer/etc/supportcontainer.yaml",
        "--image-root",
        disk_mount_dir,
        "export-all",
        container_export_dir,
    ]

    # Container-Explorer binary supports exporting as disk image and .tar.gz archive.
    # Building the export type based on user selection.
    if task_config.get("export_image"):
        export_command.append("--image")
    if task_config.get("export_archive"):
        export_command.append("--archive")

    # Using default if user did not selection an export type.
    if "--image" not in export_command and "--archive" not in export_command:
        export_command.append("--image")

    # Filter container to export using container label key-value pairs.
    filter: str | None = task_config.get("filter")
    if filter:
        export_command.extend(["--filter", filter])

    output_files: list[OutputFile] = []

    logger.debug("Running container-explorer export command %s", " ".join(export_command))

    try:
        process: subprocess.CompletedProcess[str] = subprocess.run(
            export_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            exported_containers: list[str] = os.listdir(container_export_dir)
            logger.debug(
                "%d container output files in export directory %s",
                len(exported_containers),
                container_export_dir,
            )

            for exported_container in exported_containers:
                logger.debug(
                    "Exported container %s in export directory %s",
                    exported_container,
                    container_export_dir,
                )

                output_file: OutputFile = create_output_file(
                    output_path,
                    display_name=exported_container,
                    data_type="image",
                    extension=exported_container.split(".")[-1],
                    source_file_id=input_file.get("id"),
                )

                # Converting ContainerExplorer generated output file to OpenRelik compatible name
                # and location.
                shutil.move(
                    os.path.join(container_export_dir, exported_container),
                    output_file.path,
                )

                # Fix display_name double extension
                output_file.display_name = exported_container

                # Determine container ID based on exported container file.
                #
                # When Container Explorer `export-all` command is used to export all containers,
                # container ID is not provided to the function. We are determining the container ID
                # based on the exported container files in the specified container output directory.
                #
                # Container name may have '.' in the container name. Thus, using known extensions to
                # identify container ID, and falling back to '.' as separator to handle unknown.
                container_id: str = ""
                if _DISK_EXT in exported_container:
                    container_id = exported_container.split(_DISK_EXT)[0]
                elif _ARCHIVE_EXT in exported_container:
                    container_id = exported_container.split(_ARCHIVE_EXT)[0]
                else:
                    container_id: str = exported_container.split(".")[0]

                logger.info(f"Exporting container {container_id} as {output_file.path}")
                log_entry(
                    log_file,
                    f"Exporting container {container_id} as {exported_container}",
                )

                output_files.append(output_file)
            logger.debug("%d output file created", len(output_files))

        else:
            _log_message: str = f"Error exporting all containers in disk {input_file.get('id')}"
            logger.error(_log_message)
            log_entry(log_file, _log_message)

    except subprocess.CalledProcessError as err:
        logger.error("Error calling container-explorer command: %s", str(err))
    finally:
        # Clean up temporary folder
        shutil.rmtree(container_export_dir)
        logger.debug("Deleted container export directory %s", container_export_dir)

    return output_files


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def container_export(
    self,
    pipe_result: str = None,
    input_files: list[dict] = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict[str, Any] = None,
) -> str:
    """Export containers as disk image, archive, or both.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    task_id = self.request.id
    log_root.bind(workflow_id=workflow_id)
    logger.info("Starting container export task ID: %s, Workflow ID: %s", task_id, workflow_id)

    final_output_files: list[Any] = []
    log_files: list[Any] = []
    temp_dir: str = ""
    mountpoints: list[str] = []

    input_files = get_input_files(pipe_result, input_files or [], filter=COMPATIBLE_INPUTS)

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)


    # Log file to capture logs.
    log_file: OutputFile = create_output_file(
        output_path,
        extension="log",
        display_name="container_export",
    )
    log_files.append(log_file.to_dict())

    if not input_files:
        message = "No input files provided."
        logger.warning(message)
        log_entry(log_file, message)

        return create_task_result(
            output_files=final_output_files,
            workflow_id=workflow_id,
        )

    container_ids: list[str] = []
    container_ids_str: str = task_config.get("container_id", "")
    if container_ids_str:
        for container_id in container_ids_str.split(","):
            if not container_id:
                continue
            container_ids.append(container_id.strip())

    # Indicate task progress start.
    self.send_event("task-progress")

    # Process each input file.
    for input_file in input_files:
        logger.info("Processing disk %s", input_file.get("id"))

        if container_ids:
            logger.info("Processing container IDs %s", ",".join(container_ids))
        else:
            logger.info("Processing all containers")

        try:
            bd = BlockDevice(input_file.get("path"))
            bd.setup()
            mountpoints: list[str] = bd.mount()

            if not mountpoints:
                logger.info("No mountpoints return for the disk %s", input_file.get("id"))

                logger.debug("Unmounting the disk %s", input_file.get("id"))
                bd.umount()

                continue

            export_files: list[OutputFile] = []

            for mountpoint in mountpoints:
                logger.debug(
                    "Processing mountpoint %s from disk %s",
                    mountpoint,
                    input_file.get("id"),
                )

                if not container_root_exists(mountpoint):
                    logger.debug(
                        "Container root does not exist in mountpoint %s. Skipping...",
                        mountpoint,
                    )

                    log_entry(
                        log_file,
                        f"Default container root directories do not exist in {input_file.get('id')}",
                    )

                    continue

                # Export all containers from the mountpoint.
                if not container_ids:
                    logger.debug("Procesing mountpoint %s to export all containers", mountpoint)

                    container_export_files: list[OutputFile] = export_all_containers(
                        input_file, output_path, log_file, mountpoint, task_config
                    )
                    if container_export_files:
                        export_files.extend(container_export_files)
                        log_entry(
                            log_file,
                            f"Exported {len(container_export_files)} containers",
                        )

                    logger.debug(
                        "Exported %d containers from mountpoint %s",
                        len(container_export_files),
                        mountpoint,
                    )

                # Export specified containers from the mountpoint.
                else:
                    for container_id in container_ids:
                        logger.debug(
                            "Processing mountpoint %s for container %s",
                            mountpoint,
                            container_id,
                        )

                        container_export_files: list[OutputFile] = export_container(
                            input_file,
                            output_path,
                            log_file,
                            mountpoint,
                            container_id,
                            task_config,
                        )
                        if container_export_files:
                            export_files.extend(container_export_files)

                        logger.debug(
                            "Exported %d containers from mountpoint %s",
                            len(container_export_files),
                            mountpoint,
                        )

            logger.debug("Completed processing mountpoints in disk %s", input_file.get("id"))

            for export_file in export_files:
                final_output_files.append(export_file.to_dict())

        except RuntimeError as err:
            logger.error("Error mounting disk image: %s", str(err))

        except Exception as err:
            logger.error(
                "Encounted unexpected error while processing disk %s - %s",
                input_file.get("id"),
                str(err),
            )

        finally:
            logger.debug("Unmounting disk %s", input_file.get("id"))
            log_entry(log_file, f"Done processing {input_file.get('path', '')}")
            bd.umount()

    logger.debug("Completed processing %d input disks", len(input_files))

    report: Report = container_export_report(final_output_files)

    return create_task_result(
        workflow_id=workflow_id,
        output_files=final_output_files,
        task_files=log_files,
        task_report=report.to_dict(),
    )


def container_export_report(output_files: list[dict]) -> Report:
    """Generates and returns container export report."""
    logger.debug("Generating container export report")

    report: Report = Report("Container Export Report")
    summary: MarkdownDocumentSection = report.add_section()

    if not output_files:
        summary.add_paragraph("No container exported.")
        return report

    for output_file in output_files:
        summary.add_bullet(f"Exported container output file {output_file.get('display_name')}")

    return report
