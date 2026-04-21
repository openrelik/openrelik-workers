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
import os
import shutil

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common import telemetry
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.mount_utils import BlockDevice
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

TASK_NAME = "openrelik-worker-extraction.tasks.extract_files"

TASK_METADATA = {
    "display_name": "Extract specific files from disk images",
    "description": "Mount a disk image and extract specific files provided as full paths.",
    "task_config": [
        {
            "name": "file_paths",
            "label": "Enter full file paths to extract (one per line)",
            "description": "Provide a multiline list of full file paths to extract from the disk image.",
            "type": "textarea",
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
def extract_files_task(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Mount disk images and extract specific files.

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

    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []

    file_paths_str = task_config.get("file_paths", "")
    file_paths = [path.strip() for path in file_paths_str.splitlines() if path.strip()]

    if not file_paths:
        logger.warning("No file paths provided for extraction.")
        return create_task_result(
            output_files=[],
            workflow_id=workflow_id,
        )

    self.send_event("task-progress")

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    for input_file in input_files:
        input_file_path = input_file.get("path")
        if not input_file_path:
            logger.error("No path for the input file.")
            continue

        logger.info(f"Processing image: {input_file_path}")
        bd = BlockDevice(image_path=input_file_path, min_partition_size=0)

        try:
            bd.setup()
            mountpoints = bd.mount()

            if not mountpoints:
                logger.warning(f"No mountpoints found for {input_file_path}")
                continue

            for requested_path in file_paths:
                # requested_path might be absolute (e.g. /Windows/System32/config/SYSTEM)
                # Ensure it's treated relative to mountpoint.
                clean_path = requested_path.lstrip(os.path.sep)

                for mountpoint in mountpoints:
                    full_path = os.path.join(mountpoint, clean_path)
                    if os.path.exists(full_path) and os.path.isfile(full_path):
                        logger.info(f"Extracting {requested_path} from {mountpoint}")

                        output_file = create_output_file(
                            output_path,
                            display_name=os.path.basename(full_path),
                            original_path=requested_path,
                            data_type="extraction:file",
                            source_file_id=input_file.get("id"),
                        )

                        try:
                            shutil.copy(full_path, output_file.path)
                        except Exception as e:
                            logger.error(
                                f"Error copying file {full_path} to {output_file.path}: {e}"
                            )
                            continue

                        output_files.append(output_file.to_dict())

        except Exception as e:
            logger.error(f"Error processing image {input_file_path}: {e}")
        finally:
            logger.info(f"Unmounting {input_file_path}")
            bd.umount()

    logger.info(f"Done {TASK_NAME} for workflow {workflow_id}")
    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
    )
