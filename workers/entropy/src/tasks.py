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

import csv
import io
import math
import os

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.reporting import Report
from openrelik_worker_common.task_utils import create_task_result
from openrelik_worker_common.task_utils import get_input_files

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-entropy.tasks.entropy"

# Default value for high entropy
HIGH_ENTROPY_THRESHOLD = 7.0

# Default value for the maximum file size to compute entropy
MAX_FILE_SIZE_MB = 100 # 100MB

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "High Entropy",
    "description": "Detect files with entropy.",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "entropy-threshold",
            "label": "Entropy threshold value",
            "description": f"Entropy threshold value. (default is {HIGH_ENTROPY_THRESHOLD})",
            "type": "string",
            "require": False,
        },
        {
            "name": "max-filesize",
            "label": "Maximum size",
            "description": f"Maximum size (in MB) of files this will compute the entropy of (default is {MAX_FILE_SIZE_MB}MB)",
            "type": "string",
            "require": False,
        }
    ],
}


def calculate_entropy(data: bytes) -> float:
    """Calculate entropy of data, as a number of bits of entropy per byte.

    Args:
      data: The data to calculate entropy on.

    Returns:
      A float representing the entropy.
    """
    entropy = 0
    if not data:
        return 0
    for x in range(256):
        p_x = float(data.count(x)) / len(data)
        if p_x > 0:
            entropy -= p_x * math.log(p_x, 2)
    return entropy


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def run_entropy_task(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run Entropy task on input files.

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

    high_entropy_files = []

    high_entropy_thershold = task_config.get("entropy-threshold") or HIGH_ENTROPY_THRESHOLD

    max_file_size_mb = task_config.get("max-filesize") or MAX_FILE_SIZE_MB
    skipped_count = 0

    string_io = io.StringIO()
    csv_writer = csv.DictWriter(string_io, fieldnames=["path", "entropy"])
    csv_writer.writeheader()

    for input_file in input_files:
        input_file_path = input_file.get("path")

        file_size_mb = os.stat(input_file_path).st_size / 1000 / 1000
        if file_size_mb > max_file_size_mb:
            skipped_count += 1
            continue

        with open(input_file.get("path"), "rb") as fh:
            filename = input_file.get("display_name")

            entropy = calculate_entropy(fh.read())
            csv_writer.writerow({"path": filename, "entropy": str(entropy)})
            if entropy >= high_entropy_thershold:
                high_entropy_files.append([filename, entropy])

    csv_result = create_output_file(
        output_path,
        display_name="entropy_results",
        extension=".csv",
        data_type="openrelik:entropy:results",
    )
    with open(csv_result.path, "w") as outfile:
        outfile.write(string_io.getvalue())

    task_report = Report("Entropy analyzer report")
    results_summary = (
        f"Found {len(high_entropy_files)} files "
        f"with high entropy (>{high_entropy_thershold}).\n"
        f"Skipped {skipped_count} files because their size is over the {max_file_size_mb}MB limit."
    )
    task_report.summary = results_summary
    summary_section = task_report.add_section()
    summary_section.add_paragraph(results_summary)

    details_section = task_report.add_section()
    for path, entropy in high_entropy_files:
        details_section.add_bullet(f"{path}: {entropy}", level=1)

    return create_task_result(
        workflow_id=workflow_id,
        output_files=[csv_result.to_dict()],
        task_report=task_report.to_dict(),
        meta={},
    )
