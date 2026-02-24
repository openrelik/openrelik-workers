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
from openrelik_worker_common.reporting import serialize_file_report
from uuid import uuid4
import os
import shutil

from .app import celery
from .utils import extract_non_empty_files, generate_summary_report

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-bulkextractor.tasks.bulkextractor"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Bulkextractor",
    "description": "Runs the bulk_extractor command against a file",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
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
    """
    Run bulk_extractor on input files.

    Args:
        self: The Celery task instance.
        pipe_result (str, optional): Base64-encoded result from a previous Celery task.
        input_files (list, optional): A list of dictionaries representing input files.
        output_path (str, optional): Path to the output directory.
        workflow_id (str, optional): The ID of the OpenRelik workflow.
        task_config (dict, optional): A dictionary containing user configuration.

    Returns:
        str: A Base64-encoded dictionary string containing the task results.

    Raises:
        RuntimeError: If bulk_extractor fails or if the output directory is missing.
    """
    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []
    file_reports = []

    for input_file in input_files:
        base_command = ["bulk_extractor"]
        report_file = create_output_file(
            output_path,
            display_name=f"Report_{input_file.get('display_name')}.html",
        )
        tmp_artifacts_dir = os.path.join(output_path, uuid4().hex)
        base_command.extend(["-o", tmp_artifacts_dir])
        base_command_string = " ".join(base_command)
        command_list = base_command + [input_file.get("path")]

        # Run the command
        process = subprocess.Popen(command_list)
        process.wait()
        if process.returncode == 0:
            # Execution complete, verify the results
            if os.path.exists(tmp_artifacts_dir):
                report = generate_summary_report(tmp_artifacts_dir)
                with open(report_file.path, "w") as fh:
                    fh.write(report.to_markdown())
                output_files.append(report_file.to_dict())
                output_files.extend(
                    extract_non_empty_files(tmp_artifacts_dir, output_path)
                )
                file_reports.append(
                    serialize_file_report(input_file, report_file, report)
                )
            else:
                raise RuntimeError(
                    f"Bulk Extractor successful but output directory "
                    f"'{tmp_artifacts_dir}' was not created."
                )
        else:
            raise RuntimeError(
                f"Bulk Extractor failed with exit code {process.returncode}."
            )

        if os.path.exists(tmp_artifacts_dir):
            shutil.rmtree(tmp_artifacts_dir)

    if not output_files:
        raise RuntimeError("Error running bulk extractor, no files returned.")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command_string,
        meta={},
        file_reports=file_reports,
    )
