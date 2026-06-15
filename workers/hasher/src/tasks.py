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
"""Celery tasks for calculating file hashes."""

import subprocess
import logging
import json

from celery.utils.log import get_task_logger

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

logger = get_task_logger(__name__)

# Task name used to register and route the task to the correct queue.
# This name should be unique and is used by Celery to identify the task.
TASK_NAME = "openrelik-worker-hasher.tasks.calculate_ssdeep_hash"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "SSDeep Hash Calculation",
    "description": (
        "Calculates the SSDeep (context-triggered piecewise hash) for each input file. "
        "Outputs a summary JSON file and a Markdown table with the results."
    ),
    "task_config": [],  # No user-configurable options for basic hashing.
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
    """Calculates the SSDeep hash for input files.

    The task processes each input file and calculates its SSDeep hash.
    Results are consolidated into two output files: a summary JSON file and
    a Markdown table.

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
    # General command for execution and reporting.
    # -s: Silent mode (suppresses errors to stderr, prints them to stdout)
    # -b: Bare mode (strips directory paths from filename in output, if any)
    base_command = ["/usr/bin/ssdeep", "-s", "-b"]

    if not input_files:
        return create_task_result(
            output_files=[],
            workflow_id=workflow_id,
            command=" ".join(base_command),
            meta={"message": "No input files provided to calculate SSDeep hash."},
        )

    results = []
    total_files = len(input_files)
    for index, input_file_dict in enumerate(input_files):
        input_file_path = input_file_dict.get("path")
        input_file_display_name = input_file_dict.get(
            "display_name", input_file_dict.get("filename", "input_file")
        )

        if not input_file_path:
            logger.warning(f"Skipping file entry with no path: {input_file_dict}")
            continue

        self.send_event(
            "task-progress",
            data={
                "status": f"Processing file {index + 1} of {total_files} with ssdeep..."
            },
        )

        # Run the command
        cmd_to_run = base_command + [input_file_path]

        process = subprocess.run(
            cmd_to_run, capture_output=True, text=True, check=False
        )
        ssdeep_result_text = process.stdout.strip()
        ssdeep_hash_or_error: str

        if process.returncode != 0:
            # This might capture other errors if -s doesn't suppress everything
            error_details = process.stderr.strip() or ssdeep_result_text
            ssdeep_hash_or_error = (
                f"Error running ssdeep (code {process.returncode}): " f"{error_details}"
            )
            logger.error(f"SSDeep failed for {input_file_path}: {ssdeep_hash_or_error}")

        elif (
            ',"' in ssdeep_result_text
        ):  # Expected format for a successful hash: HASH,"FILENAME"
            ssdeep_hash_or_error = ssdeep_result_text.split(',"', 1)[0]
        else:  # Likely "file too small" or other message from ssdeep printed to stdout
            ssdeep_hash_or_error = f"SSDeep notice: {ssdeep_result_text}"

        results.append(
            {"filename": input_file_display_name, "ssdeep": ssdeep_hash_or_error}
        )

    if results:
        # Create JSON output file
        json_output_file = create_output_file(
            output_path,
            display_name="ssdeep_results",
            extension="json",
            data_type="application/json",
        )
        with open(json_output_file.path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=4)
        output_files.append(json_output_file.to_dict())

        # Create Markdown output file
        md_output_file = create_output_file(
            output_path,
            display_name="ssdeep_results",
            extension="md",
            data_type="text/markdown",
        )
        with open(md_output_file.path, "w", encoding="utf-8") as fh:
            fh.write("# SSDeep Hash Results\n\n")
            fh.write("| Filename | SSDeep Hash |\n")
            fh.write("| --- | --- |\n")
            for result in results:
                fh.write(f"| {result['filename']} | {result['ssdeep']} |\n")
        output_files.append(md_output_file.to_dict())

    if (
        not output_files and input_files
    ):  # Processed inputs but no outputs (e.g. all files failed path validation)
        # This specific error might be too generic if individual file errors
        # are already captured in their output files.
        # Depending on desired behavior, this could be a warning or info log.
        logger.warning(
            "SSDeep task processed input files but generated no output files overall."
        )

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=" ".join(base_command),  # General command used
        meta={},  # No additional metadata for the overall task result in this case
    )
