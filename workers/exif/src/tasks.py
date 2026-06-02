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

import subprocess

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-exif.tasks.extract_exif"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "ExifTool Extractor",
    "description": "Extracts EXIF metadata from files using ExifTool.",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "json_output",
            "label": "Output in JSON format",
            "description": "If checked, ExifTool will output metadata in JSON format. Output files will have a .json extension and 'application/json' MIME type.",
            "type": "checkbox",
            "required": False,
            "default_value": False,
        },
    ],
}


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run exiftool on input files to extract metadata.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    task_config = task_config or {}
    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []

    # Determine if JSON output is requested
    json_output_enabled = task_config.get("json_output", False)

    base_command = ["exiftool"]
    if json_output_enabled:
        base_command.append("-json")

    base_command_string = " ".join(base_command)

    for input_file in input_files:
        output_file_extension = ".json" if json_output_enabled else ".txt"
        output_file_data_type = (
            "application/json" if json_output_enabled else "text/plain"
        )

        output_file = create_output_file(
            output_path,
            display_name=input_file.get("display_name"),
            extension=output_file_extension,
            data_type=output_file_data_type,
        )
        # Command to run: exiftool [-json] <input_file_path>
        # The output will be redirected to output_file.path
        current_command = base_command + [input_file.get("path")]

        # Run the command
        with open(output_file.path, "w") as fh:
            process = subprocess.Popen(
                current_command, stdout=fh, stderr=subprocess.PIPE
            )
            _, stderr = process.communicate()
            if process.returncode != 0:
                error_message = (
                    f"ExifTool failed for {input_file.get('path')}: {stderr.decode()}"
                )
                raise RuntimeError(error_message)

        output_files.append(output_file.to_dict())

    if not output_files:
        raise RuntimeError(
            "No input files were processed or ExifTool produced no output."
        )

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command_string,
        meta={},
    )
