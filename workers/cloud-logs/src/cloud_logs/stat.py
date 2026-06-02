# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cloud logs stats."""

from typing import Any, Dict, List

from openrelik_worker_common.reporting import MarkdownDocument
from openrelik_worker_common.reporting import MarkdownDocumentSection
from openrelik_worker_common.reporting import MarkdownTable


class GoogleCloudLogStat:
    """Class for tracking Google Cloud audit log stats."""

    def __init__(self, log_source: str) -> None:
        """Initializes GoogleCloudLogStat."""
        self.log_source = log_source
        self.skipped_log_count: int = 0
        self.payload_type_stat: Dict[str, int] = {}
        self.service_stat: Dict[str, int] = {}
        self.method_stat: Dict[str, int] = {}
        self.principal_email_stat: Dict[str, int] = {}

    def update_cloud_log_stat(self, log_entry: Dict[str, Any]) -> None:
        """Updates GoogleCloudLogStat values using processed log entry."""
        if not log_entry:
            return

        payload_type = log_entry.get("payload_type")
        if payload_type:
            self.payload_type_stat[payload_type] = (
                self.payload_type_stat.get(payload_type, 0) + 1
            )

        service_name = log_entry.get("service_name")
        if service_name:
            self.service_stat[service_name] = self.service_stat.get(service_name, 0) + 1

        method_name = log_entry.get("method_name")
        if method_name:
            self.method_stat[method_name] = self.method_stat.get(method_name, 0) + 1

        principal_email = log_entry.get("principal_email")
        if principal_email:
            self.principal_email_stat[principal_email] = (
                self.principal_email_stat.get(principal_email, 0) + 1
            )

    def increase_skip_log_counter(self) -> None:
        """Increment skip log counter by 1."""
        self.skipped_log_count += 1

    def _create_markdown_table(
        self, attribute_title: str, value_title: str, stat: Dict[str, int]
    ) -> List[str]:
        """Returns markdown table list."""
        md_table = []
        md_table.append(f"| {attribute_title} | {value_title} |")
        md_table.append("|------|------|")

        for attribute, value in stat.items():
            md_table.append(f"| {attribute} | {value} |")

        return md_table

    def create_report(self) -> str:
        """Create GoogleCloudLogStat report."""
        mddoc = MarkdownDocument(title="Google Cloud Audit Log Stat")

        general_section = mddoc.add_section()
        general_section.add_bullet(f"Log source: {self.log_source}")
        general_section.add_bullet(f"Skipped logs: {self.skipped_log_count}")
        general_section.add_paragraph("")

        payload_section = mddoc.add_section()
        payload_section.add_header("Payload Stat", 2)
        payload_table = MarkdownTable(columns=["Payload Type", "Count"])
        for attribute, value in self.payload_type_stat.items():
            payload_table.add_row(row_data=[attribute, str(value)])
        payload_section.add_table(payload_table)

        service_section = mddoc.add_section()
        service_section.add_header("Service Stat", 2)
        service_table = MarkdownTable(columns=["Service Name", "Count"])
        for attribute, value in self.service_stat.items():
            service_table.add_row(row_data=[attribute, str(value)])
        service_section.add_table(service_table)

        method_section = mddoc.add_section()
        method_section.add_header("Method Stat", 2)
        method_table = MarkdownTable(columns=["Method Name", "Count"])
        for attribute, value in self.method_stat.items():
            method_table.add_row(row_data=[attribute, str(value)])
        method_section.add_table(method_table)

        principal_section = mddoc.add_section()
        principal_section.add_header("Principal Email Stat", 2)
        principal_table = MarkdownTable(columns=["Principal Email", "Count"])
        for attribute, value in self.principal_email_stat.items():
            principal_table.add_row(row_data=[attribute, str(value)])
        principal_section.add_table(principal_table)

        return mddoc.to_markdown()
