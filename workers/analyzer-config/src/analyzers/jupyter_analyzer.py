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

from openrelik_worker_common.reporting import Priority, Report


def analyze_config(input_file: dict, task_config: dict) -> Report:
    """Extract security related configs from Jupyter configuration files.

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

    for line in config.split("\n"):
        if all(x in line for x in ["disable_check_xsrf", "True"]):
            details_section.add_bullet("XSRF protection is disabled.")
            num_misconfigs += 1
            continue
        if all(x in line for x in ["allow_root", "True"]):
            details_section.add_bullet("Juypter Notebook allowed to run as root.")
            num_misconfigs += 1
            continue
        if "NotebookApp.password" in line:
            if all(x in line for x in ["required", "False"]):
                details_section.add_bullet(
                    "Password is not required to access this Jupyter Notebook."
                )
                num_misconfigs += 1
                continue
            if "required" not in line:
                password_hash = line.split("=")
                if len(password_hash) > 1:
                    if password_hash[1].strip() == "''":
                        details_section.add_bullet(
                            "There is no password set for this Jupyter Notebook."
                        )
                        num_misconfigs += 1
        if all(x in line for x in ["allow_remote_access", "True"]):
            details_section.add_bullet("Remote access is enabled on this Jupyter Notebook.")
            num_misconfigs += 1
            continue

    if num_misconfigs > 0:
        report.priority = Priority.HIGH
        report.summary = "Insecure Jupyter Notebook configuration found"
        return report

    report.priority = Priority.LOW
    report.summary = "No issues found in Jupyter Notebook configuration."
    return report
