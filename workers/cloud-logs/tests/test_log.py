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

"""Tests for GoogleCloudLog."""

import json
import os
import tempfile

from src.cloud_logs.gcp.log import GoogleCloudLog


def test_log_initialization():
    log = GoogleCloudLog()
    assert log.service_name() is None
    assert log.log_record() is None
    assert log.output_all_request_field is False
    assert log.output_all_response_field is False


def test_add_log_record():
    log = GoogleCloudLog()
    log.add_log_record("key", None)
    assert log.log_record() is None
    log.add_log_record("key", "")
    assert log.log_record() is None
    log.add_log_record("service_name", "test_service")
    assert log.service_name() == "test_service"
    assert log.log_record() == {"service_name": "test_service"}


def test_add_log_payload_type():
    log = GoogleCloudLog()
    log.add_log_payload_type("protoPayload")
    assert log.log_record() == {"payload_type": "protoPayload"}


def test_service_account_delegation():
    log = GoogleCloudLog()
    # No delegation
    assert log._get_service_account_delegation({}) == []

    # First party principal with email
    auth_info = {
        "serviceAccountDelegationInfo": [
            {
                "principalSubject": "subject-1",
                "firstPartyPrincipal": {"principalEmail": "fp@example.com"},
            },
            {
                "principalSubject": "subject-2",
                "firstPartyPrincipal": {},
            },
            {
                "principalSubject": "subject-3",
            },
        ]
    }
    delegations = log._get_service_account_delegation(auth_info)
    assert delegations == ["fp@example.com", "subject-2", "subject-3"]


def test_parse_authentication_info():
    log = GoogleCloudLog()
    assert log._parse_authentication_info({}) is None

    payload = {
        "authenticationInfo": {
            "principalEmail": "user@example.com",
            "principalSubject": "user:user@example.com",
            "serviceAccountKeyName": "key-123",
            "serviceAccountDelegationInfo": [
                {
                    "principalSubject": "sub-1",
                }
            ],
        }
    }
    log._parse_authentication_info(payload)
    rec = log.log_record()
    assert rec["principal_email"] == "user@example.com"
    assert rec["principal_subject"] == "user:user@example.com"
    assert rec["service_account_key_name"] == "key-123"
    assert rec["delegations"] == ["sub-1"]
    assert rec["delegation_chain"] == "sub-1"


def test_parse_authorization_info():
    log = GoogleCloudLog()
    assert log._parse_authorization_info({}) is None

    payload = {
        "authorizationInfo": [
            {
                "permission": "compute.instances.create",
                "permissionType": "ADMIN_WRITE",
                "granted": True,
            },
            {
                "permission": "compute.instances.get",
            },
        ]
    }
    log._parse_authorization_info(payload)
    assert log.log_record()["permissions"] == [
        "compute.instances.create:ADMIN_WRITE:True",
        "compute.instances.get",
    ]


def test_parse_request_metadata():
    log = GoogleCloudLog()
    assert log._parse_request_metadata({}) is None

    payload = {
        "requestMetadata": {
            "callerIp": "1.2.3.4",
            "callerNetwork": "network-1",
            "callerSuppliedUserAgent": (
                "Google-Cloud-SDK/123 command/compute.instances.create "
                "invocation-id/inv-456"
            ),
        }
    }
    log._parse_request_metadata(payload)
    rec = log.log_record()
    assert rec["caller_ip"] == "1.2.3.4"
    assert rec["caller_network"] == "network-1"
    assert rec["gcloud_command_partial"] == "compute.instances.create"
    assert rec["gcloud_command_identity"] == "inv-456"


def test_parse_status():
    log = GoogleCloudLog()
    assert log._parse_status({}) is None

    payload = {
        "status": {
            "code": 7,
            "message": "Permission denied",
            "details": [{"reason": "ACCESS_DENIED"}, {"other": "value"}],
        }
    }
    log._parse_status(payload)
    rec = log.log_record()
    assert rec["status_coode"] == 7
    assert rec["status_message"] == "Permission denied"
    assert rec["status_reasons"] == ["ACCESS_DENIED"]


def test_parse_request_and_response():
    log = GoogleCloudLog()
    assert log._parse_request({}) is None
    assert log._parse_response({}) is None

    # Test filtering when output_all is False
    log.output_all_request_field = False
    log.request_fields = ["name", "@type", "slash/field"]
    log.output_all_response_field = False
    log.response_fields = ["name", "@type", "slash/field"]

    payload = {
        "request": {
            "name": "res-1",
            "@type": "type-1",
            "slash/field": "val-slash",
            "ignored": "ignored-val",
        },
        "response": {
            "name": "res-2",
            "@type": "type-2",
            "slash/field": "val-slash-2",
            "ignored": "ignored-val",
        },
    }
    log._parse_request(payload)
    log._parse_response(payload)

    rec = log.log_record()
    assert rec["request_name"] == "res-1"
    assert rec["request_type"] == "type-1"
    assert rec["request_slash_field"] == "val-slash"
    assert "request_ignored" not in rec

    assert rec["response_name"] == "res-2"
    assert rec["response_type"] == "type-2"
    assert rec["response_slash_field"] == "val-slash-2"
    assert "response_ignored" not in rec


def test_parse_request_and_response_all_fields():
    log = GoogleCloudLog()
    log.output_all_request_field = True
    log.output_all_response_field = True

    payload = {
        "request": {"custom_field": "val1"},
        "response": {"custom_field": "val2"},
    }
    log._parse_request(payload)
    log._parse_response(payload)

    rec = log.log_record()
    assert rec["request_custom_field"] == "val1"
    assert rec["response_custom_field"] == "val2"


def test_parse_service_data():
    log = GoogleCloudLog()
    assert log._parse_service_data({}) is None

    payload = {
        "serviceData": {
            "policyDelta": {
                "bindingDeltas": [
                    {
                        "action": "ADD",
                        "member": "user:foo@example.com",
                        "role": "roles/owner",
                    }
                ]
            },
            "permissionDelta": {"permKey": "permVal"},
        }
    }
    log._parse_service_data(payload)
    rec = log.log_record()
    assert rec["policy_deltas"] == ["user:foo@example.com:roles/owner:ADD"]
    assert rec["permKey"] == "permVal"


def test_compute_audit_log():
    log = GoogleCloudLog()
    payload = {
        "serviceName": "compute.googleapis.com",
        "methodName": "compute.instances.insert",
        "resourceName": "projects/p/zones/z/instances/i",
        "request": {
            "disks": [
                {
                    "initializeParams": {
                        "sourceImage": "projects/debian-cloud/global/images/debian-11"
                    }
                },
                {"initializeParams": {}},
            ],
            "serviceAccounts": [
                {
                    "email": "sa@example.com",
                    "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
                }
            ],
        },
    }
    log.process_proto_payload(payload)
    rec = log.log_record()
    assert rec["service_name"] == "compute.googleapis.com"
    assert rec["source_images"] == [
        "projects/debian-cloud/global/images/debian-11"
    ]
    assert rec["dcsa_email"] == "sa@example.com"
    assert rec["dcsa_scopes"] == [
        "https://www.googleapis.com/auth/cloud-platform"
    ]


def test_process_json_payload():
    log = GoogleCloudLog()
    log.process_json_payload({"simple_key": "val1", "slash/key": "val2"})
    rec = log.log_record()
    assert rec["simple_key"] == "val1"
    assert rec["slash_key"] == "val2"


def test_process_text_payload():
    log = GoogleCloudLog()
    log.process_text_payload("plain text log")
    rec = log.log_record()
    assert rec["text_payload"] == "plain text log"


def test_process_log_entry_empty_and_invalid():
    log = GoogleCloudLog()
    assert log.process_log_entry("") is None
    assert log.process_log_entry("{invalid_json") is None


def test_process_log_entry_payload_types():
    # JSON payload
    log1 = GoogleCloudLog()
    raw_json = json.dumps({
        "timestamp": "2025-01-01T00:00:00Z",
        "severity": "INFO",
        "logName": "projects/p/logs/l",
        "resource": {"type": "gce_instance"},
        "labels": {"label/zone": "us-east1"},
        "jsonPayload": {"msg": "hello"},
    })
    rec1 = log1.process_log_entry(raw_json)
    assert rec1["payload_type"] == "jsonPayload"
    assert rec1["msg"] == "hello"
    assert rec1["label_zone"] == "us-east1"
    assert rec1["datetime"] == "2025-01-01T00:00:00Z"

    # Text payload
    log2 = GoogleCloudLog()
    raw_text = json.dumps({
        "timestamp": "2025-01-01T00:00:00Z",
        "textPayload": "test text message",
    })
    rec2 = log2.process_log_entry(raw_text)
    assert rec2["payload_type"] == "textPayload"
    assert rec2["message"] == "test text message"


def test_build_message_string_fallbacks():
    # Already has message
    log = GoogleCloudLog()
    log.add_log_record("message", "pre-existing")
    log._build_message_string()
    assert log.log_record()["message"] == "pre-existing"

    # Fallback to user, event_subtype, resource_project_id
    log2 = GoogleCloudLog()
    log2.add_log_record("user", "bob")
    log2.add_log_record("event_subtype", "login")
    log2.add_log_record("resource_project_id", "proj-999")
    log2._build_message_string()
    assert log2.log_record()["message"] == "bob performed login on proj-999"

    # Fallback completely unknown
    log3 = GoogleCloudLog()
    log3.add_log_record("dummy", "val")
    log3._build_message_string()
    assert (
        log3.log_record()["message"]
        == "An unknown actor performed an unknown action on an unknown resource"
    )


def test_process_log_file_with_skip_and_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "in.jsonl")
        output_file = os.path.join(tmpdir, "out.jsonl")
        report_file = os.path.join(tmpdir, "report.md")

        # Include valid line and invalid line
        valid_entry = json.dumps({
            "timestamp": "2025-01-01T00:00:00Z",
            "protoPayload": {
                "serviceName": "compute.googleapis.com",
                "methodName": "compute.instances.insert",
                "request": {"req_field": "val"},
                "response": {"resp_field": "val"},
            },
        })
        with open(input_file, "w", encoding="utf-8") as fh:
            fh.write(valid_entry + "\n")
            fh.write("bad json line\n")

        log = GoogleCloudLog()
        log.process_log_file(
            input_file,
            output_file,
            report_file,
            request_field="req_field",
            response_field="resp_field",
        )

        with open(output_file, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["request_req_field"] == "val"
        assert parsed["response_resp_field"] == "val"

        with open(report_file, "r", encoding="utf-8") as fh:
            report_content = fh.read()
        assert "Skipped logs: 1" in report_content
