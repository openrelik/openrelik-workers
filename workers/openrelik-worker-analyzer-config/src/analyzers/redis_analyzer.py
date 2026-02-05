# Copyright 2024-2025 Google LLC
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
import re

from openrelik_worker_common.reporting import Priority, Report


def analyze_config(input_file: dict, task_config: dict) -> Report:
    """Analyzes a Redis configuration.

    Args:
      file_content (str): configuration file content.

    Returns:
        report (Report): The analysis report.
    """
    # Read the input file to be analyzed.
    with open(input_file.get("path"), "r", encoding="utf-8") as fh:
        config = fh.read()
    num_misconfigs = 0

    report = Report()
    details_section = report.add_section()

    bind_everywhere_re = re.compile(r'^\s*bind[\s"]*0\.0\.0\.0', re.IGNORECASE | re.MULTILINE)
    default_port_re = re.compile(r"port\s+6379\b", re.IGNORECASE)
    missing_logs_re = re.compile(r'^logfile\s+"[^"]+"$', re.MULTILINE)

    if config is None or config == "":
        report.summary = "No Redis config found"
        report.priority = Priority.LOW
        pass
    else:
        if re.search(bind_everywhere_re, config):
            num_misconfigs += 1
            details_section.add_bullet("Redis listening on every IP")

        if re.search(default_port_re, config):
            num_misconfigs += 1
            details_section.add_bullet("Redis configured with default port (6379)")

        if not re.search(missing_logs_re, config):
            num_misconfigs += 1
            details_section.add_bullet("Log destination not configured")

        if num_misconfigs > 0:
            report.summary = "Insecure Redis configuration found"
            report.priority = Priority.HIGH

    return report


def create_task_report(file_reports: list = []):
    """Creates a task report from a list of file reports.

    Args:
        file_reports (list): A list of file reports.

    Returns:
        report (Report): The task report.
    """
    pass
