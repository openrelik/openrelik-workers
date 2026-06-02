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

import subprocess

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-capa.tasks.capa"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Capa Malware Analysis",
    "description": "Detect capabilities from executable files",
}


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def capa(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run capa on input files.

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
    base_command = ["/usr/local/bin/capa", "--quiet"]

    self.send_event("task-progress")

    for input_file in input_files:
        # Run Capa and create JSON output
        self.send_event("task-progress", data={"status": "Creating JSON output"})
        json_output_file = create_output_file(
            output_path,
            display_name=f"{input_file.get('display_name')}_capa.json",
            data_type="capa:json",
        )
        command = base_command + ["--json", input_file.get("path")]
        with open(json_output_file.path, "w") as fh:
            process = subprocess.Popen(command, stdout=fh)
            process.wait()
        output_files.append(json_output_file.to_dict())

        # Create Capa Summary report
        self.send_event("task-progress", data={"status": "Creating summary report"})
        summary_output_file = create_output_file(
            output_path,
            display_name=f"{input_file.get('display_name')}_capa_summary.txt",
            data_type="capa:report:summary",
        )
        command = base_command + [(json_output_file.path)]
        with open(summary_output_file.path, "w") as fh:
            process = subprocess.Popen(command, stdout=fh)
            process.wait()
        output_files.append(summary_output_file.to_dict())

        # Create Capa Detailed report
        self.send_event("task-progress", data={"status": "Creating detailed report"})
        detailed_output_file = create_output_file(
            output_path,
            display_name=f"{input_file.get('display_name')}_capa_detailed.txt",
            data_type="capa:report:detailed",
        )
        command = base_command + ["-vv", (json_output_file.path)]
        with open(detailed_output_file.path, "w") as fh:
            process = subprocess.Popen(command, stdout=fh)
            process.wait()
        output_files.append(detailed_output_file.to_dict())

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=" ".join(base_command),
        meta={},
    )
