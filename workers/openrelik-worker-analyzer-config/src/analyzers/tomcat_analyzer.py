# Copyright 2024-2025 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Analyze Tomcat configuration files."""

import re

from openrelik_worker_common.reporting import Priority, Report


def analyze_config(input_file: dict, task_config: dict) -> Report:
    """Analyze a Tomcat file.

    - Search for clear text password entries in user configuration file
    - Search for .war deployment
    - Search for management control panel activity

    Args:
      config (str): Tomcat file content.
    Returns:
      report (Report): The analysis report.
    """
    with open(input_file.get("path"), "r", encoding="utf-8") as fh:
        config = fh.read()
    num_misconfigs = 0

    report = Report()
    details_section = report.add_section()

    tomcat_deploy_re = re.compile("(^.*Deploying web application archive.*)", re.MULTILINE)
    tomcat_manager_activity_re = re.compile("(^.*POST /manager/html/upload.*)", re.MULTILINE)
    tomcat_readonly_re = re.compile("<param-name>readonly</param-name>", re.IGNORECASE)
    tomcat_readonly_false_re = re.compile(
        r"<param-name>readonly</param-name>\s*<param-value>false</param-value>",
        re.IGNORECASE,
    )
    tomcat_user_passwords_re = re.compile("(^.*password.*)", re.MULTILINE)

    for password_entry in re.findall(tomcat_user_passwords_re, config):
        num_misconfigs += 1
        details_section.add_bullet("tomcat user: " + password_entry.strip())

    for deployment_entry in re.findall(tomcat_deploy_re, config):
        num_misconfigs += 1
        details_section.add_bullet("Tomcat App Deployed: " + deployment_entry.strip())

    for mgmt_entry in re.findall(tomcat_manager_activity_re, config):
        num_misconfigs += 1
        details_section.add_bullet("Tomcat Management: " + mgmt_entry.strip())

    if re.search(tomcat_readonly_re, config):
        if re.search(tomcat_readonly_false_re, config):
            num_misconfigs += 1
            details_section.add_bullet("Tomcat servlet IS NOT read-only")

    if num_misconfigs > 0:
        report.summary = "Tomcat analysis found misconfigs"
        report.priority = Priority.HIGH
        return report

    report.summary = "No issues found in Tomcat configuration"
    report.priority = Priority.LOW
    return report
