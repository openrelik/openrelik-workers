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

import os

from typing import Callable

from openrelik_common import telemetry
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files
from openrelik_worker_common.reporting import serialize_file_report

from .app import celery


def task_factory(
    task_name: str,
    task_name_short: str,
    compatible_inputs: dict,
    task_metadata: dict,
    operate_on_each_file: bool,
    analysis_function: Callable,
    task_report_function: Callable = None,
):
    """
    Factory function to create credential analyzer Celery tasks.

    Args:
        task_name: Full task name for registration.
        task_name_short: Short task name for display.
        compatible_inputs: Input file compatibility specifications.
        task_metadata: Metadata for registration in the core system.
        analysis_function: The function to use for analyzing the config file.

    Returns:
        A Celery task function.
    """

    @celery.task(bind=True, name=task_name, metadata=task_metadata)
    def creds_analyzer(
        self,
        pipe_result: str = None,
        input_files: list = None,
        output_path: str = None,
        workflow_id: str = None,
        task_config: dict = None,
    ) -> str:
        """Run the appropriate analyzer on input files."""

        input_files = get_input_files(pipe_result,
                                      input_files or [],
                                      filter=compatible_inputs)
        output_files = []
        file_reports = []
        task_report = None

        telemetry.add_attribute_to_current_span("input_files", input_files)
        telemetry.add_attribute_to_current_span("task_config", task_config)
        telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

        if operate_on_each_file:
            for input_file in input_files:
                report_file = create_output_file(
                    output_path,
                    display_name=
                    f"{input_file.get('display_name')}-{task_name_short}-report.md",
                    data_type=
                    f"worker:openrelik:os-creds:{task_name_short}:report",
                )

                # Read the input file to be analyzed.
                with open(input_file.get("path"), "r", encoding="utf-8") as fh:
                    creds_file = fh.read()

                # Use the provided analysis function.
                analysis_report = analysis_function(creds_file)
                file_report = serialize_file_report(input_file, report_file,
                                                    analysis_report)

                with open(report_file.path, "w", encoding="utf-8") as fh:
                    fh.write(analysis_report.to_markdown())

                file_reports.append(file_report)
                output_files.append(report_file.to_dict())
        else:
            unique_original_paths = set([
                os.path.dirname(y.get('original_path', ''))
                for y in input_files
            ])
            for unique_dirname in unique_original_paths:
                filtered_input_files = [
                    i for i in input_files if os.path.dirname(
                        i.get('original_path', '')) == unique_dirname
                ]

                # Operate on the directory of files only
                analysis_report = analysis_function(filtered_input_files)
                # task_report = analysis_report

                report_file = create_output_file(
                    output_path,
                    display_name=f"{task_name_short}-report.md",
                    data_type=
                    f"worker:openrelik:os-creds:{task_name_short}:report",
                )

                file_report = serialize_file_report(filtered_input_files[0],
                                                    report_file,
                                                    analysis_report)

                with open(report_file.path, "w", encoding="utf-8") as fh:
                    fh.write(analysis_report.to_markdown())
                file_reports.append(file_report)
                output_files.append(report_file.to_dict())

        return create_task_result(
            output_files=output_files,
            workflow_id=workflow_id,
            file_reports=file_reports,
            task_report=task_report,
        )

    return creds_analyzer
