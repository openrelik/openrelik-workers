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

from celery import signals
from celery.utils.log import get_task_logger
from openrelik_common import telemetry
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.reporting import Priority, Report
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery
from .logger import log_root
from .ssh_analyzer import LinuxSSHAnalysisTask

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-analyzer-logs.tasks.ssh_analyzer"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "SSH login analyzer",
    "description": "Search for suspicious SSH login events in system logs",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "log_year",
            "label": "Log year",
            "description": "Specify log year for SSH events, in case it's not captured by syslog. Otherwise it will be guessed based on the last SSH event and current date/time.",
            "type": "text",  # Types supported: text, textarea, checkbox
            "required": False,
        },
    ],
}

logger = log_root.get_logger(__name__, get_task_logger(__name__))


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def run_ssh_analyzer(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run <REPLACE_WITH_COMMAND> on input files.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME} for workflow {workflow_id}")

    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []

    telemetry.add_attribute_to_current_span("input_files", input_files)
    telemetry.add_attribute_to_current_span("task_config", task_config)
    telemetry.add_attribute_to_current_span("workflow_id", workflow_id)

    task_report = Report("SSH log analyzer report")
    summary_section = task_report.add_section()

    try:
        log_year = int(task_config.get("log_year"))
    except (TypeError, ValueError):
        log_year = None

    ssh_analysis_task = LinuxSSHAnalysisTask(log_year=log_year)
    analyzer_output_priority = Priority.LOW

    # Indicate task progress start.
    self.send_event("task-progress")

    df = ssh_analysis_task.read_logs(input_files=input_files)
    if df.empty:
        summary_section.add_paragraph("No SSH authentication events in input files.")
    else:
        # 01. Brute Force Analyzer
        (result_priority, result_summary, result_markdown) = (
            ssh_analysis_task.brute_force_analysis(df)
        )
        if result_priority > analyzer_output_priority:
            task_report.priority = result_priority
        logger.debug(f"Report priority: {result_priority}")

        summary_section.add_paragraph(result_markdown)

        output_file = create_output_file(
            output_path,
            display_name="linux_ssh_analysis",
            extension=".md",
            data_type="openrelik:ssh:report",
        )
        with open(output_file.path, "w") as outfile:
            outfile.write(result_markdown)

        output_files.append(output_file.to_dict())

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        task_report=task_report.to_dict(),
        meta={},
    )
