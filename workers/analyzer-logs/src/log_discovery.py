# Copyright 2026 Google LLC
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

import json
import logging
import os
import posixpath
import re
from openrelik_worker_common.file_utils import create_output_file, is_disk_image
from openrelik_worker_common.mount_utils import BlockDevice

logger = logging.getLogger(__name__)

DISK_IMAGE_EXTENSIONS = (
    ".dd",
    ".raw",
    ".e01",
    ".aff4",
    ".qcow2",
    ".vmdk",
    ".vdi",
    ".ova",
    ".iso",
)

# Common timestamp and log level patterns (ISO 8601, syslog, and standard log levels).
LOG_PATTERN_REGEX = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}|"
    r"\[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL|FATAL|NOTICE)\]|"
    r"^(?:DEBUG|INFO|WARNING|ERROR|CRITICAL|FATAL|NOTICE):",
    re.IGNORECASE,
)


def is_binary(filepath: str) -> bool:
    """Check if a file is binary by looking for null bytes in the first 1024 bytes."""
    try:
        with open(filepath, "rb") as f:
            return b"\0" in f.read(1024)
    except IOError:
        return True


class LogDiscoveryAnalyzer:
    """Scan text files to find potential log files based on timestamp density."""

    def __init__(self, threshold: float):
        self.threshold = threshold

    def check_file(self, file_path: str, formatted_path: str, path_list: list):
        """Check a single file and add its path to path_list if it matches the threshold."""
        if file_path.lower().endswith(DISK_IMAGE_EXTENSIONS):
            return

        if is_binary(file_path):
            return

        try:
            match_count = 0
            line_count = 0

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_count += 1
                    if LOG_PATTERN_REGEX.search(line):
                        match_count += 1

                    # Sample up to the first 500 lines per file.
                    if line_count >= 500:
                        break

            if line_count > 0 and (match_count / line_count) >= self.threshold:
                path_list.append(formatted_path)

        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")

    def analyze(self, input_files: list, output_path: str) -> tuple:
        """Analyze input files or disk images and write the JSON discovery report."""
        discovered_data = []
        disks_mounted = []
        output_files = []
        total_logs = 0

        try:
            for input_file in input_files:
                path = input_file.get("path")
                base_name = input_file.get("display_name", path)
                evidence_id = input_file.get("uuid", input_file.get("id", "UNKNOWN_UUID"))

                current_evidence = {
                    "id": evidence_id,
                    "name": base_name,
                    "paths": [],
                }

                is_disk = is_disk_image(input_file) or path.lower().endswith(DISK_IMAGE_EXTENSIONS)

                if is_disk:
                    logger.info(f"Mounting disk image: {base_name}")
                    bd = BlockDevice(path, min_partition_size=1)
                    bd.setup()
                    mountpoints = bd.mount()
                    disks_mounted.append(bd)

                    if not mountpoints:
                        logger.warning(f"No mountpoints found for {base_name}")
                        continue

                    for mountpoint in mountpoints:
                        for root, _, files in os.walk(mountpoint):
                            for filename in files:
                                full_path = os.path.join(root, filename)
                                formatted_path = "/" + os.path.relpath(full_path, mountpoint)
                                self.check_file(full_path, formatted_path, current_evidence["paths"])

                elif os.path.isdir(path):
                    for root, _, files in os.walk(path):
                        for filename in files:
                            full_path = os.path.join(root, filename)
                            formatted_path = "/" + os.path.relpath(full_path, path)
                            self.check_file(full_path, formatted_path, current_evidence["paths"])

                elif os.path.isfile(path):
                    self.check_file(path, "/" + os.path.basename(path), current_evidence["paths"])

                if current_evidence["paths"]:
                    discovered_data.append(current_evidence)

        finally:
            for blockdevice in disks_mounted:
                if blockdevice:
                    logger.info(f"Unmounting image: {blockdevice.image_path}")
                    blockdevice.umount()

        if discovered_data:
            report_file = create_output_file(
                output_path,
                display_name="potential_logs_report.json",
                data_type="openrelik:report",
            )
            payload = [
                {
                    "evidence_id": item["id"],
                    "evidence_name": item["name"],
                    "log_paths": sorted(
                        posixpath.normpath(path) for path in item.get("paths", [])
                    ),
                }
                for item in discovered_data
            ]
            total_logs += sum(len(entry["log_paths"]) for entry in payload)
            with open(report_file.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            output_files.append(report_file.to_dict())

        return output_files, total_logs
