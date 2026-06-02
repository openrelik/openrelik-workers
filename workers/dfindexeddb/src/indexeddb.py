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

import os
import re
import shutil
import subprocess
import time
import uuid

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from . import definitions


# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-dfindexeddb.tasks.indexeddb"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "dfindexeddb: indexeddb",
    "description": "Extracts IndexedDB records using dfindexeddb.",
    # Configuration that will be rendered as a web form in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "browser_type",
            "label": "Select browser type",
            "description": "The browser type",
            "items": [ "chromium", "firefox", "safari" ],
            "type": "select",  # Types supported: text, textarea, checkbox
            "required": True,
        },
        {
            "name": "output_format",
            "label": "Select output format",
            "description": "The output format",
            "items": [ "JSON", "JSONL", "REPR" ],
            "type": "select",  # Types supported: text, textarea, checkbox
            "required": True,
        }
    ],
}

INTERVAL_SECONDS = 2


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str | None = None,
    input_files: list | None = None,
    output_path: str | None = None,
    workflow_id: str | None = None,
    task_config: dict | None = None,
) -> str:
    """Run dfindexeddb on input files.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []
    base_command = "dfindexeddb"

    if not task_config:
        return create_task_result(
            output_files=output_files,
            workflow_id=workflow_id,
            command=base_command,
            meta={},
        )

    # parse task configuration
    output_format = task_config.get("output_format", []).lower()
    output_config = definitions.OUTPUT_TYPES_EXTENSIONS[output_format]
    output_extension = output_config["extension"]
    browser_type = task_config.get("browser_type", "")

    # Create temporary directory and hard link files for processing
    temp_dir = os.path.join(output_path, uuid.uuid4().hex)
    os.mkdir(temp_dir)

    input_files_temp = []
    for input_file in input_files or []:
        display_name = input_file.get("display_name")
        temp_file = f"{temp_dir}/{display_name}"
        shutil.copy(input_file.get("path"), temp_file)
        input_files_temp.append((input_file, temp_file))

    for input_file, temp_file in input_files_temp:
        display_name = input_file.get("display_name")
        original_path = input_file.get("path")
        source_file_id = input_file.get("id")
        data_type = f"openrelik:dfindexeddb:{browser_type}:{output_format}"
        if browser_type == "chromium":
            for subcommand, value in definitions.CHROMIUM_FILE_REGEX.items():
                if re.search(value, display_name):
                    break
            else:
                print(f"Unsupported {browser_type} file type for {display_name}.")
                continue
        elif (browser_type == "firefox" and
              re.search(definitions.FIREFOX_FILE_REGEX, display_name)):
            subcommand = "db"
        elif (browser_type == "safari" and
              re.search(definitions.SAFARI_FILE_REGEX, display_name)):
            subcommand = "db"
        else:
            print(f"Unsupported {browser_type} file type for {display_name}.")
            continue

        stdout_file = create_output_file(
            output_base_path=output_path,
            display_name=f"{display_name}.{browser_type}",
            extension=output_extension,
            data_type=data_type,
            original_path=original_path,
            source_file_id=source_file_id
        )
        stderr_file = create_output_file(
            output_base_path=output_path,
            display_name=display_name,
            extension=f"{output_extension}.error.txt",
            data_type=definitions.STDERR_FILE_DATA_TYPE,
            original_path=original_path,
            source_file_id=source_file_id
        )

        command_parts = [
            base_command,
            subcommand,
            "-s",
            temp_file,
            "-o",
            output_format
        ]

        if subcommand == "db":
            command_parts.extend([
                "--format",
                browser_type,
            ])

        # Run the command
        with (
            open(stdout_file.path, "w", encoding="utf-8") as stdout_fh,
            open(stderr_file.path, "w", encoding="utf-8") as stderr_fh
        ):
            process = subprocess.Popen(command_parts, stdout=stdout_fh, stderr=stderr_fh)
            while process.poll() is None:
                self.send_event("task-progress", data=None)
                time.sleep(INTERVAL_SECONDS)

        output_files.append(stdout_file.to_dict())
        output_files.append(stderr_file.to_dict())

    # Remove temp directory
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    if not output_files:
        raise RuntimeError("No supported files")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command,
        meta={},
    )
