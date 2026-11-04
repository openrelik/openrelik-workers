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

"""Tests for GoogleCloudLogStat."""

from src.cloud_logs.stat import GoogleCloudLogStat


def test_stat_initialization():
    stat = GoogleCloudLogStat("test_source.jsonl")
    assert stat.log_source == "test_source.jsonl"
    assert stat.skipped_log_count == 0
    assert stat.payload_type_stat == {}
    assert stat.service_stat == {}
    assert stat.method_stat == {}
    assert stat.principal_email_stat == {}


def test_stat_update_empty_and_none():
    stat = GoogleCloudLogStat("test_source.jsonl")
    stat.update_cloud_log_stat({})
    assert stat.payload_type_stat == {}
    stat.update_cloud_log_stat(None)
    assert stat.payload_type_stat == {}


def test_stat_update_valid_entries():
    stat = GoogleCloudLogStat("test_source.jsonl")
    entry1 = {
        "payload_type": "protoPayload",
        "service_name": "compute.googleapis.com",
        "method_name": "compute.instances.insert",
        "principal_email": "user@example.com",
    }
    entry2 = {
        "payload_type": "protoPayload",
        "service_name": "storage.googleapis.com",
        "method_name": "storage.buckets.get",
        "principal_email": "user@example.com",
    }
    stat.update_cloud_log_stat(entry1)
    stat.update_cloud_log_stat(entry2)

    assert stat.payload_type_stat == {"protoPayload": 2}
    assert stat.service_stat == {
        "compute.googleapis.com": 1,
        "storage.googleapis.com": 1,
    }
    assert stat.method_stat == {
        "compute.instances.insert": 1,
        "storage.buckets.get": 1,
    }
    assert stat.principal_email_stat == {"user@example.com": 2}


def test_stat_increase_skip_counter():
    stat = GoogleCloudLogStat("test_source.jsonl")
    stat.increase_skip_log_counter()
    stat.increase_skip_log_counter()
    assert stat.skipped_log_count == 2


def test_stat_create_markdown_table():
    stat = GoogleCloudLogStat("test_source.jsonl")
    data = {"item1": 5, "item2": 10}
    table = stat._create_markdown_table("Item", "Count", data)
    assert table[0] == "| Item | Count |"
    assert table[1] == "|------|------|"
    assert "| item1 | 5 |" in table
    assert "| item2 | 10 |" in table


def test_stat_create_report():
    stat = GoogleCloudLogStat("test_source.jsonl")
    stat.increase_skip_log_counter()
    stat.update_cloud_log_stat({
        "payload_type": "protoPayload",
        "service_name": "compute.googleapis.com",
        "method_name": "compute.instances.insert",
        "principal_email": "user@example.com",
    })
    report = stat.create_report()
    assert "Google Cloud Audit Log Stat" in report
    assert "Log source: test_source.jsonl" in report
    assert "Skipped logs: 1" in report
    assert "compute.googleapis.com" in report
    assert "compute.instances.insert" in report
    assert "user@example.com" in report
