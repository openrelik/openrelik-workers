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

import subprocess

from celery import signals
from celery.utils.log import get_task_logger

from openrelik_common import telemetry
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import create_output_file, count_file_lines
from openrelik_worker_common.task_utils import create_task_result, get_input_files

import datetime
import time

from .app import celery

TASK_NAME = "openrelik-worker-grep.tasks.ugrep"

TASK_METADATA = {
    "display_name": "Ugrep",
    "description": "Search for patterns in a file using ugrep. Supports regexp, fuzzy search, searching inside archives, and more.",
    "task_config": [
        {
            "name": "pattern",
            "label": "pattern",
            "description": "Pattern to search for (defaults to extended regular expression)",
            "type": "text",
            "required": True,
        },
        {
            "name": "invert_match",
            "label": "invert match",
            "description": "Selected lines are those not matching any of the specified patterns.",
            "type": "checkbox",
            "required": True,
            "default_value": False,
        },
        {
            "name": "stats",
            "label": "stats",
            "description": "Output statistics on the number of files and directories searched and matches found.",
            "type": "checkbox",
            "required": True,
            "default_value": True,
        },
        {
            "name": "json_output",
            "label": "JSON output",
            "description": "Output file matches in JSON.",
            "type": "checkbox",
            "required": True,
            "default_value": False,
        },
        {
            "name": "decompress",
            "label": "search archives",
            "description": "Search compressed files and archives.",
            "type": "checkbox",
            "required": True,
            "default_value": False,
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

    # Setup logger
    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME} for workflow {workflow_id}")

    input_files = get_input_files(pipe_result, input_files or [])

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    output_files = []
    base_command = prepare_base_command(task_config)
    base_command_string = " ".join(base_command)

    output_extension = ".ugrep.json" if task_config.get("json_output") else ".ugrep"

    for input_file in input_files:
        output_file = create_output_file(
            output_path, display_name=input_file.get("display_name") + output_extension
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

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command_string,
        meta={},
    )


def prepare_base_command(task_config):
    base_command = ["ugrep"]

    if task_config.get("stats"):
        base_command.append("--stats")
    if task_config.get("json_output"):
        base_command.append("--json")
    if task_config.get("decompress"):
        base_command.append("--decompress")
 
    # Pattern options
    if task_config.get("invert-match"):
        base_command.append("--invert-match")
    base_command.append(task_config.get("pattern"))

    base_command.append("--")
    return base_command
