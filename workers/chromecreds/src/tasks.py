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

import sqlite3

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files
from openrelik_worker_common.reporting import Report, Priority

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-chromecreds.tasks.analyse"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Chrome Credentials Analyser",
    "description": "Extracts and analyses Chrome Browser Credential store",
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
    """Extract and analyse credentials from input files.

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
    task_report = None

    extracted_creds = {}

    for input_file in input_files:
        report_file = create_output_file(
            output_path,
            display_name=f"{input_file.get('display_name')}-chromecreds.dict",
            data_type=f"worker:openrelik:chromecreds:report",
        )
        creds = _extract_chrome_creds(input_file.get("path"))
        extracted_creds.update(creds)

        if creds:
            with open(report_file.path, "w", encoding="utf-8") as fh:
                fh.write(str(creds))

            output_files.append(report_file.to_dict())

    for key in extracted_creds:
      extracted_creds[key] = list(set(extracted_creds[key]))

    task_report = [generate_report(extracted_creds).to_dict()]

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        task_report=task_report,
    )

def generate_report(creds):
    report = Report("Chrome Config Analyzer")
    summary_section = report.add_section()
    details_section = report.add_section()
    report.summary = f'{len(creds)} saved credentials found in Chrome Login Data'
    report.priority = Priority.LOW

    if creds:
      report.priority = Priority.MEDIUM
      details_section.add_bullet('Credentials:')
      for k, v in creds.items():
        line = f"Site '{k}' with users '{v}'"
        details_section.add_bullet(line, level=2)
    else:
        details_section.add_bullet('No saved credentials found')

    summary_section.add_paragraph(report.summary)
    return report

def _extract_chrome_creds(filepath):
    """Extract saved credentials from a Chrome Login Database file.

    Args:
        filepath (str): path to Login Database file.

    Returns:
        dict: of username against website
    """
    ret = {}

    con = sqlite3.connect(filepath)
    cur = con.cursor()
    try:
        for row in cur.execute('SELECT origin_url, username_value FROM logins'):
            if not row[1]:
                continue
            if row[0] not in ret:
                ret[row[0]] = []
            ret[row[0]].append(row[1])
    # Database path not found.
    except sqlite3.OperationalError:
        return ret
    # Not a valid SQLite DB.
    except sqlite3.DatabaseError:
        return ret

    con.close()
    return ret