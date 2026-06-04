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
"""Google Cloud Logs Processor"""

import orjson
import logging
import re

from typing import Any, Dict, List

from src.cloud_logs.stat import GoogleCloudLogStat


class GoogleCloudLog:
    """Class for processing Google Cloud logs.

    Attributes:
        _log_record (Dict[str, Any]): A dictionary containing data that will be exported to
                Timesketch.
        output_all_request_field (bool): Indicates if all request fields will be added to the
                output.
        request_fields (List[str]): A list of request fields that will be included in the output.
        output_all_response_field (bool): Indicates if all response fields will be added to the
                output.
        response_fields (List[str]): A list of response fields that will be included in the output.
    """

    _USER_AGENT_COMMAND_RE = re.compile(r"command/([^\s]+)")
    _USER_AGENT_INVOCATION_ID_RE = re.compile(r"invocation-id/([^\s]+)")

    def __init__(self) -> None:
        """Initializes GoogleCloudLog."""
        self._log_record = {}
        self.output_all_request_field = False
        self.request_fields = [
            "@type",
            "billingAccountName",
            "name",
        ]
        self.output_all_response_field = False
        self.response_fields = [
            "@type",
            "name",
        ]

    def service_name(self) -> str | None:
        """Returns service name"""
        return self._log_record.get("service_name")

    def add_log_record(self, attribute: str, value: Any) -> None:
        """Adds Gogole Cloud log record."""
        if not value:
            return
        self._log_record[attribute] = value

    def add_log_payload_type(self, payload_type: str) -> None:
        """Adds Google Cloud log payload type."""
        self.add_log_record("payload_type", payload_type)

    def _get_service_account_delegation(
        self, authentication_info: Dict[str, Any]
    ) -> List[str]:
        """Returns service account delegation list."""
        # protoPayload.authenticationInfo.serviceAccountDelegationInfo
        # https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog#ServiceAccountDelegationInfo
        delegation_infos = authentication_info.get("serviceAccountDelegationInfo", [])
        if not delegation_infos:
            return []

        delegations = []
        for delegation_info in delegation_infos:
            principal_subject = delegation_info.get("principalSubject", "")

            first_party_principal = delegation_info.get("firstPartyPrincipal", "")
            if not first_party_principal:
                delegations.append(principal_subject)
                continue

            first_party_principal_email = first_party_principal.get(
                "principalEmail", ""
            )
            if first_party_principal_email:
                delegations.append(first_party_principal_email)

        return delegations

    def _parse_authentication_info(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.authenticationInfo."""
        # https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog#AuthenticationInfo
        authentication_info = payload.get("authenticationInfo")
        if not authentication_info:
            return None

        self.add_log_record("principal_email", authentication_info.get("principalEmail"))
        self.add_log_record(
            "principal_subject", authentication_info.get("principalSubject")
        )
        self.add_log_record(
            "service_account_key_name", authentication_info.get("serviceAccountKeyName")
        )

        delegations = self._get_service_account_delegation(authentication_info)
        if delegations:
            self.add_log_record("delegations", delegations)
            self.add_log_record("delegation_chain", "->".join(delegations))

    def _parse_authorization_info(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.authorizationInfo."""
        # protoPayload.authorizationInfo
        # https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog#AuthorizationInfo

        # `permissions` contains concatenation of two authorizationInfo attributes
        # `permission` and `permissionType` i.e. `permission`:`permissionType`
        # Example: `compute.project.get:ADMIN_READ`
        authorization_infos = payload.get("authorizationInfo", [])
        if not authorization_infos:
            return None

        permissions = []

        for authorization_info in authorization_infos:
            granted = authorization_info.get("granted", False)
            permission = authorization_info.get("permission")
            permission_type = authorization_info.get("permissionType")

            if permission_type:
                permission = f"{permission}:{permission_type}:{granted}"
            permissions.append(permission)

        self.add_log_record("permissions", permissions)

    def _parse_request_metadata(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.requestMetadata."""
        # protoPayload.requestMetadata
        # https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog#RequestMetadata
        request_metadata = payload.get("requestMetadata")
        if not request_metadata:
            return None

        self.add_log_record("caller_ip", request_metadata.get("callerIp"))
        self.add_log_record("user_agent", request_metadata.get("callerSuppliedUserAgent"))
        self.add_log_record("caller_network", request_metadata.get("callerNetwork"))

        user_agent = request_metadata.get("callerSuppliedUserAgent")
        if user_agent:
            if "command/" in user_agent:
                matches = self._USER_AGENT_COMMAND_RE.search(user_agent)
                if matches:
                    command_string = matches.group(1).replace(",", " ")
                    self.add_log_record("gcloud_command_partial", command_string)

            if "invocation-id" in user_agent:
                matches = self._USER_AGENT_INVOCATION_ID_RE.search(user_agent)
                if matches:
                    self.add_log_record("gcloud_command_identity", matches.group(1))

    def _parse_status(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.status."""
        # https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog#Status
        status = payload.get("status")
        if not status:
            return None

        self.add_log_record("status_coode", status.get("code"))
        self.add_log_record("status_message", status.get("message"))

        status_reasons = []

        for detail in status.get("details", []):
            reason = detail.get("reason")
            if reason:
                status_reasons.append(reason)
        if status_reasons:
            self.add_log_record("status_reasons", status_reasons)

    def _parse_request(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.request."""
        request = payload.get("request")
        if not request:
            return None

        for key, value in request.items():
            if not self.output_all_request_field:
                if key not in self.request_fields:
                    continue

            if "@" in key:
                key = key.replace("@", "")

            if "/" in key:
                key = key.replace("/", "_")
            request_key = f"request_{key}"

            self.add_log_record(request_key, value)

    def _parse_response(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.response."""
        response = payload.get("response")
        if not response:
            return None

        for key, value in response.items():
            if not self.output_all_response_field:
                if key not in self.response_fields:
                    continue

            if "@" in key:
                key = key.replace("@", "")

            if "/" in key:
                key = key.replace("/", "_")
            response_key = f"response_{key}"

            self.add_log_record(response_key, value)

    def _parse_service_data(self, payload: Dict[str, Any]) -> None:
        """Parse protoPayload.serviceData."""
        service_data = payload.get("serviceData")
        if not service_data:
            return None

        # Policy changes
        policy_delta = service_data.get("policyDelta")
        if policy_delta:
            policy_delta_list = []

            for binding_delta in policy_delta.get("bindingDeltas", []):
                action = binding_delta.get("action")
                member = binding_delta.get("member")
                role = binding_delta.get("role")

                policy_delta_list.append(f"{member}:{role}:{action}")
            self.add_log_record("policy_deltas", policy_delta_list)

        # Permission changes
        permission_delta = service_data.get("permissionDelta")
        if permission_delta:
            for key, value in permission_delta.items():
                self.add_log_record(key, value)

    def _parse_compute_source_images(self, request: Dict[str, Any]) -> None:
        """Parse source images."""
        source_images = []

        for disk in request.get("disks", []):
            initialize_params = disk.get("initializeParams", {})

            source_image = initialize_params.get("sourceImage")
            if source_image:
                source_images.append(source_image)
        if source_images:
            self.add_log_record("source_images", source_images)

    def _parse_dcsa(self, request: Dict[str, Any]) -> None:
        """Parse request and extract DCSA."""
        dcsa_email = None
        dcsa_scopes = None

        for service_account in request.get("serviceAccounts", []):
            email = service_account.get("email")
            if email:
                dcsa_email = email

            scopes = service_account.get("scopes")
            if scopes:
                if not dcsa_scopes:
                    dcsa_scopes = []

                dcsa_scopes.extend(scopes)

        self.add_log_record("dcsa_email", dcsa_email)
        self.add_log_record("dcsa_scopes", dcsa_scopes)

    def _parse_compute_audit_log(self, payload: Dict[str, Any]) -> None:
        """Parse compute.googleapis.com logs."""
        request: Dict[str, Any] = payload.get("request", {})

        # GCE instance create/insert activity
        self._parse_compute_source_images(request)
        self._parse_dcsa(request)

    def process_proto_payload(self, payload: Dict[str, Any]) -> None:
        """Process Google Cloud audit protoPayload."""
        # AuditLog or protoPayload attributes
        # https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog
        # https://github.com/googleapis/googleapis/blob/master/google/cloud/audit/audit_log.proto
        self.add_log_record("service_name", payload.get("serviceName"))
        self.add_log_record("method_name", payload.get("methodName"))
        self.add_log_record("resource_name", payload.get("resourceName"))

        self._parse_authentication_info(payload)
        self._parse_authorization_info(payload)
        self._parse_request_metadata(payload)
        self._parse_request(payload)
        self._parse_response(payload)
        self._parse_service_data(payload)

        # service specific parsing
        if self.service_name() == "compute.googleapis.com":
            self._parse_compute_audit_log(payload)

    def process_json_payload(self, payload: Dict[str, Any]) -> None:
        """Process Google Cloud jsonPayload."""
        for key, value in payload.items():
            if "/" in key:
                key = key.replace("/", "_")
            self.add_log_record(key, value)

    def process_text_payload(self, payload: Dict[str, Any]) -> None:
        """Process Google Cloud textPayload."""
        self.add_log_record("text_payload", payload)

    def log_record(self) -> Dict[str, Any] | None:
        """Returns processed Google Cloud log entry."""
        if not self._log_record:
            return None
        return self._log_record

    def process_log_entry(self, log_line: str) -> Dict[str, Any] | None:
        """Process Google Cloud audit log entry."""
        if not log_line:
            return None

        try:
            log_entry = orjson.loads(log_line)
        except orjson.JSONDecodeError as err:
            logging.debug("Error converting log to JSON. %s", str(err))
            return None

        # Parse LogEntry common attributes.
        self.add_log_record("datetime", log_entry.get("timestamp"))
        self.add_log_record("timestamp_desc", "Event Recorded")

        self.add_log_record("severity", log_entry.get("severity"))
        self.add_log_record("log_name", log_entry.get("logName"))

        resource = log_entry.get("resource")
        if resource:
            self.add_log_record("resource_type", log_entry.get("type"))

            labels = log_entry.get("labels", {})
            for attribute, value in labels.items():
                if "/" in attribute:
                    attribute = attribute.replace("/", "_")
                self.add_log_record(attribute, value)

        # Google Cloug LogEntry is union of:
        # - protoPayload
        # - jsonPayload
        # - textPayload
        proto_payload = log_entry.get("protoPayload")
        json_payload = log_entry.get("jsonPayload")
        text_payload = log_entry.get("textPayload")

        if proto_payload:
            self.add_log_payload_type("protoPayload")
            self.process_proto_payload(proto_payload)

        if json_payload:
            self.add_log_payload_type("jsonPayload")
            self.process_json_payload(json_payload)

        if text_payload:
            self.add_log_payload_type("textPayload")
            self.process_text_payload(text_payload)

        self._build_message_string()

        return self.log_record()

    def _build_message_string(self) -> None:
        """Builds Timesketch message string."""
        if self._log_record.get("message"):
            return

        payload_type = self._log_record.get("payload_type")
        if payload_type == "textPayload":
            self.add_log_record("message", self._log_record.get("text_payload"))
            return

        requestor = "An unknown actor"
        action = "an unknown action"
        resource = "an unknown resource"

        # Requestor from most preferred to least preferred.
        for attribute in ["principal_email", "principal_subject", "user"]:
            if self._log_record.get(attribute):
                requestor = self._log_record.get(attribute)
                break

        # Action - most preferred to least
        for attribute in ["event_subtype", "method_name"]:
            if self._log_record.get(attribute):
                action = self._log_record.get(attribute)
                break

        # Resource preference: High to low.
        for attribute in ["resource_name", "resource_project_id"]:
            if self._log_record.get(attribute):
                resource = self._log_record.get(attribute)
                break

        message_string = f"{requestor} performed {action} on {resource}"

        self.add_log_record("message", message_string)

    def process_log_file(
        self,
        input_file: str,
        output_file: str,
        report_file: str = "",
        request_field: str = "",
        response_field: str = "",
    ) -> None:
        """Process Google Cloud log JSON (JSON-L) file."""
        log_stat = GoogleCloudLogStat(input_file)

        if request_field:
            if "all" in request_field:
                self.output_all_request_field = True
            else:
                self.request_fields = request_field.split(",")

        if response_field:
            if "all" in response_field:
                self.output_all_response_field = True
            else:
                self.response_fields = response_field.split(",")

        with open(output_file, "w", encoding="utf-8") as output_writer:
            with open(input_file, "r", encoding="utf-8") as input_reader:
                for log_line in input_reader:
                    log_entry = self.process_log_entry(log_line)
                    if not log_entry:
                        log_stat.increase_skip_log_counter()
                        continue

                    output_writer.write(orjson.dumps(log_entry).decode("utf-8"))
                    output_writer.write("\n")

                    if report_file:
                        log_stat.update_cloud_log_stat(log_entry)

        if report_file:
            with open(report_file, "w", encoding="utf-8") as report_writer:
                report_writer.write(log_stat.create_report())
