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

import datetime
import time
import subprocess

from openrelik_worker_common.file_utils import create_output_file, count_file_lines
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-floss.tasks.floss"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "FLOSS",
    "description": "Runs FLARE's floss tool on a file.",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "min_length",
            "description": "Minimum length the tool will consider for finding new strings.",
            "type": "text",  # Types supported: text, textarea, checkbox
            "required": False,
        },
    ],
}


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str = None,
    input_files: list | None = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict | None = None,
) -> str:
    """Run floss on input files.

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
    base_command = ["floss", "-q"]
    min_length_config = None
    if task_config:
        min_length_config = task_config.get("min_length")
    if min_length_config:
        # Ensure min_length_config is a string before adding to command list
        base_command.extend(["-n", str(min_length_config)])
    base_command_string = " ".join(base_command)

    for input_file in input_files:
        output_file = create_output_file(
            output_path,
            display_name=input_file.get("display_name"),
            extension="strings",
            data_type="openrelik:floss:strings",
        )
        input_file_path = input_file.get("path")
        if not input_file_path:
            raise ValueError(
                f"Input file path is missing for {input_file.get('display_name', 'unknown file')}"
            )
        run_command = base_command + [str(input_file_path)]

        # Run the command
        with open(output_file.path, "w", encoding="utf-8") as fh:
            process = subprocess.Popen(run_command, stdout=fh, stderr=subprocess.PIPE)
            start_time = datetime.datetime.now()
            update_interval_s = 3

            while process.poll() is None:
                strings_found = count_file_lines(output_file.path)
                duration = datetime.datetime.now() - start_time
                rate = (
                    int(strings_found / duration.total_seconds())
                    if duration.total_seconds() > 0
                    else 0
                )
                self.send_event(
                    "task-progress",
                    data={"extracted_strings": strings_found, "rate": rate},
                )
                time.sleep(update_interval_s)

            if process.stderr:
                err_message = process.stderr.read().decode()
                if err_message:
                    raise RuntimeError(err_message)

        output_files.append(output_file.to_dict())

    if not output_files or count_file_lines(output_file.path) == 0:
        raise RuntimeError("FLOSS found no strings.")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command_string,
        meta={},
    )
