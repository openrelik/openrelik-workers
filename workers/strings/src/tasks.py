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

import enum
import subprocess
import time
from datetime import datetime

from openrelik_common import telemetry
from openrelik_worker_common.file_utils import count_file_lines, create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery


# This ENum is to store encoding names, with their corresponding strings
# denomination per strings(1):
# s = single-7-bit-byte characters (default), S = single-8-bit-byte characters,
# b = 16-bit bigendian, l = 16-bit littleendian, B = 32-bit bigendian,
# L = 32-bit littleendian.
class StringsEncoding(enum.StrEnum):
    ASCII = "s"
    UTF16LE = "l"


# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-strings.tasks.strings"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Strings",
    "description": "Extract strings from files",
    "task_config": [
        {
            "name": StringsEncoding.UTF16LE.name,
            "label": "Extract Unicode strings",
            "description": (
                "This will tell the strings command to extract UTF-16LE (little"
                " endian) encoded strings"
            ),
            "type": "checkbox",
        },
        {
            "name": StringsEncoding.ASCII.name,
            "label": "Extract ASCII strings",
            "description": (
                "This will tell the strings command to extract ASCII"
                " (single-7-bit-byte) encoded strings"
            ),
            "type": "checkbox",
        },
    ],
}


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def strings(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Extract ASCII strings from files.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result
          exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    for encoding_name, unused_encoding_enabled in task_config.items():
        if encoding_name not in StringsEncoding.__members__:
            raise RuntimeError(f"{encoding_name} is not a valid StringsEncoding name")

        for input_file in input_files:
            encoding_object = StringsEncoding[encoding_name]
            output_file = create_output_file(
                output_path,
                display_name=(f"{input_file.get('display_name')}.{encoding_name}_strings"),
            )
            command = [
                "strings",
                "-a",
                "-t",
                "d",
                "--encoding",
                encoding_object.value,
                input_file.get("path"),
            ]
 
            telemetry.add_attribute_to_current_span('generated_command', command)


            with open(output_file.path, "w") as fh:
                process = subprocess.Popen(command, stdout=fh)
                start_time = datetime.now()
                update_interval_s = 3

                while process.poll() is None:
                    extracted_strings = count_file_lines(output_file.path)
                    duration = datetime.now() - start_time
                    rate = (
                        int(extracted_strings / duration.total_seconds())
                        if duration.total_seconds() > 0
                        else 0
                    )
                    self.send_event(
                        "task-progress",
                        data={"extracted_strings": extracted_strings, "rate": rate},
                    )
                    time.sleep(update_interval_s)
            output_files.append(output_file.to_dict())

    if not output_files:
        raise RuntimeError("No strings extracted from the provided files.")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        meta={},
    )
