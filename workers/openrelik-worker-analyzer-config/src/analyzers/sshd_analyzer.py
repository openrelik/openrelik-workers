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
    """Analyzes an SSHD configuration.

    Args:
      input_file: The input file dictionary.
      task_config: The task configuration dictionary.

    Returns:
        report (Report): The analysis report.
    """
    # Read the input file to be analyzed.
    with open(input_file.get("path"), "r", encoding="utf-8") as fh:
        config = fh.read()
    num_misconfigs = 0

    report = Report()
    details_section = report.add_section()

    permit_root_login_re = re.compile(
        r"^\s*PermitRootLogin\s*(yes|prohibit-password|without-password)",
        re.IGNORECASE | re.MULTILINE,
    )
    password_authentication_re = re.compile(
        r'^\s*PasswordAuthentication[\s"]*yes', re.IGNORECASE | re.MULTILINE
    )
    permit_empty_passwords_re = re.compile(
        r'^\s*PermitEmptyPasswords[\s"]*Yes', re.IGNORECASE | re.MULTILINE
    )

    if re.search(permit_root_login_re, config):
        details_section.add_bullet("Root login enabled.")
        num_misconfigs += 1

    if re.search(password_authentication_re, config):
        details_section.add_bullet(("Password authentication enabled."))
        num_misconfigs += 1

    if re.search(permit_empty_passwords_re, config):
        details_section.add_bullet("Empty passwords permitted.")
        num_misconfigs += 1

    if num_misconfigs > 0:
        report.summary = "Insecure SSHD configuration found"
        report.priority = Priority.HIGH
        return report

    report.summary = "No issues found in SSH configuration"
    report.priority = Priority.LOW
    return report


def create_task_report(file_reports: list = []):
    """Creates a task report from a list of file reports.

    Args:
        file_reports (list): A list of file reports.

    Returns:
        report (Report): The task report.
    """
    pass
