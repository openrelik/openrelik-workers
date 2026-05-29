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

from openrelik_worker_common.file_utils import create_output_file, count_file_lines
from openrelik_worker_common.task_utils import create_task_result, get_input_files

import datetime
import time

from .app import celery

TASK_NAME = "openrelik-worker-grep.tasks.grep"

TASK_METADATA = {
    "display_name": "Grep",
    "description": "Search for a regular expression in a file (case insensitive).",
    "task_config": [
        {
            "name": "regex",
            "label": "[a-f][0-9]+",
            "description": "Regular expression to grep for",
            "type": "text",
            "required": True,
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
    """Run grep on input files.

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
    base_command = ["grep", "-Ei", task_config.get("regex")]
    base_command_string = " ".join(base_command)

    for input_file in input_files:
        output_file = create_output_file(
            output_path, display_name=input_file.get("display_name") + ".grep"
        )
        command = base_command + [input_file.get("path")]

        with open(output_file.path, "w") as fh:
            process = subprocess.Popen(command, stdout=fh)
            start_time = datetime.datetime.now()
            update_interval_s = 3

            while process.poll() is None:
                grep_matches = count_file_lines(output_file.path)
                duration = datetime.datetime.now() - start_time
                rate = (
                    int(grep_matches / duration.total_seconds())
                    if duration.total_seconds() > 0
                    else 0
                )
                self.send_event(
                    "task-progress",
                    data={"extracted_strings": grep_matches, "rate": rate},
                )
                time.sleep(update_interval_s)

        output_files.append(output_file.to_dict())

    if not output_files:
        raise RuntimeError("Grep task yielded no results")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command_string,
        meta={},
    )
