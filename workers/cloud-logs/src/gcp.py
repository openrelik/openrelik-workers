"""Google Cloud audit log processor."""

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

from pathlib import Path

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .cloud_logs.gcp.log import GoogleCloudLog

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-cloud-logs.tasks.gcp"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Cloud Logs: GCP",
    "description": "Process Google Cloud audit logs.",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "request_field",
            "label": "protoPayload request fields",
            "description": (
                "Comma separated request fields to include in the output. `all` "
                "includes all fields."
            ),
            "type": "text",  # Types supported: text, textarea, checkbox
            "required": False,
        },
        {
            "name": "response_field",
            "label": "protoPayload response fields",
            "description": (
                "Comma separated response fields to include in the output. `all` "
                "includes all fields."
            ),
            "type": "text",
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
    task_config: dict = None,
) -> str:
    """Run cloud-logs on input files.

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
    base_command = ["cloud-logs.py"]
    base_command_string = " ".join(base_command)

    for input_file in input_files:
        source_filename = Path(input_file.get("display_name")).stem

        output_file = create_output_file(
            output_path,
            display_name=f"{source_filename}_output",
            extension="jsonl",
            data_type="cloud-logs:gcp:jsonl",
        )

        report_file = create_output_file(
            output_path,
            display_name=f"{source_filename}_report",
            extension="md",
            data_type="cloud-logs:gcp:report",
        )

        # Run the command
        log_processor = GoogleCloudLog()
        log_processor.process_log_file(
            input_file.get("path"),
            output_file.path,
            report_file.path,
            task_config.get("request_field", ""),
            task_config.get("response_field", ""),
        )

        output_files.append(output_file.to_dict())
        output_files.append(report_file.to_dict())

    if not output_files:
        raise RuntimeError("No supported input files.")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command_string,
        meta={},
    )
