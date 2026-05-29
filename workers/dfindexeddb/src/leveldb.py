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

import re
import subprocess
import time

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from . import definitions


# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-dfindexeddb.tasks.leveldb"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "dfindexeddb: leveldb",
    "description": "Extracts LevelDB records using dfleveldb",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "record_type",
            "label": "Record Type",
            "description": "The record type to extract",
            "items": set(
                definitions.LEVELDB_RECORD_TYPES["descriptor"] +
                definitions.LEVELDB_RECORD_TYPES["ldb"] +
                definitions.LEVELDB_RECORD_TYPES["log"]
            ),
            "type": "select",
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
    """Run dfleveldb on input files.

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
    base_command = "dfleveldb"

    if not task_config:
        return create_task_result(
            output_files=output_files,
            workflow_id=workflow_id,
            command=base_command,
            meta={},
        )

    # parse task configuration
    output_format = task_config.get("output_format", "").lower()
    output_config = definitions.OUTPUT_TYPES_EXTENSIONS[output_format]
    output_extension = output_config["extension"]
    record_type = task_config.get("record_type", "")

    # parse input files
    for input_file in input_files or []:
        display_name = input_file.get("display_name")
        original_path = input_file.get("path")
        source_file_id = input_file.get("id")
        for file_ext, file_regex in definitions.LEVELDB_FILE_REGEX.items():
            if re.search(file_regex, display_name):
                subcommand = file_ext
                break
        else:
            print(f"Unsupported file type for {display_name}.")
            continue
        if record_type not in definitions.LEVELDB_RECORD_TYPES[subcommand]:
            print(f"Unsupported record type {record_type} for {subcommand} file.")
            continue
        data_type = f"openrelik:dfleveldb:{record_type}:{output_format}"

        stdout_file = create_output_file(
            output_base_path=output_path,
            display_name=display_name,
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
            original_path,
            "-t",
            record_type,
            "-o",
            output_format
        ]

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

    if not output_files:
        raise RuntimeError("No supported files")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command,
        meta={},
    )
