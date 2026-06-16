# Copyright 2025 Google LLC
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

import os
import re
import logging
from openrelik_worker_common.file_utils import create_output_file, is_disk_image
from openrelik_worker_common.mount_utils import BlockDevice

logger = logging.getLogger(__name__)

# Common extensions to manually catch raw images if OpenRelik's internal tag is missing
DISK_IMAGE_EXTENSIONS = ('.dd', '.raw', '.e01', '.aff4', '.qcow2', '.vmdk', '.vdi', '.ova', '.iso')

# Matches standard ISO 8601 dates, Syslog formats, and common log level prefixes.
LOG_PATTERN_REGEX = re.compile(
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|'  
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}|'
    r'\[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL|FATAL|NOTICE)\]|'
    r'^(?:DEBUG|INFO|WARNING|ERROR|CRITICAL|FATAL|NOTICE):',
    re.IGNORECASE
)

def is_binary(filepath: str) -> bool:
    """
    Quickly checks for the presence of null bytes in the file header.
    This prevents the worker from wasting CPU cycles running regex over 
    compiled executables, media files, or proprietary binary databases.
    """
    try:
        with open(filepath, 'rb') as f:
            return b'\0' in f.read(1024)
    except IOError:
        return True

class LogDiscoveryAnalyzer:
    """
    Analyzes raw file contents to discover unparsed plaintext logs based on timestamp density.
    This enables log recovery when file extensions are missing or misleading.
    """
    def __init__(self, threshold: float, mount_disk_images: bool):
        self.threshold = threshold
        self.mount_disk_images = mount_disk_images

    def check_file(self, file_path: str, formatted_path: str, path_list: list):
        """Scans a single file's contents and appends it to the path list if it meets the density threshold."""
        
        # Explicitly skip nested disk images to prevent recursive "Russian Doll" mounting/analysis
        if file_path.lower().endswith(DISK_IMAGE_EXTENSIONS):
            return

        # Skip compiled binaries or media files
        if is_binary(file_path):
            return
            
        try:
            match_count = 0
            line_count = 0
            
            # Process line-by-line to prevent memory exhaustion on massive files
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line_count += 1
                    if LOG_PATTERN_REGEX.search(line):
                        match_count += 1
                        
                    # Performance Cap: A genuine log file will demonstrate its density 
                    # well within the first 500 lines. 
                    if line_count >= 500: 
                        break 
                        
            # Flag the file if the ratio of log-like lines meets the user's defined threshold
            if line_count > 0 and (match_count / line_count) >= self.threshold:
                path_list.append(formatted_path)
                
        except Exception as e:
            logger.warning(f"Log discovery failed to read {file_path}: {e}")

    def analyze(self, input_files: list, output_path: str) -> tuple:
        """Main orchestration loop: Mounts disks, walks directories, and generates the discovery report."""
        discovered_data = [] 
        disks_mounted = [] 
        output_files = []
        total_logs = 0

        try:
            for input_file in input_files:
                path = input_file.get('path')
                base_name = input_file.get('display_name', path)
                evidence_id = input_file.get('uuid', input_file.get('id', 'UNKNOWN_UUID'))
                
                current_evidence = {
                    'id': evidence_id,
                    'name': base_name,
                    'paths': []
                }

                # Evaluate mounting requirement based on OpenRelik metadata OR standard file extensions
                is_disk = is_disk_image(input_file) or path.lower().endswith(DISK_IMAGE_EXTENSIONS)

                # Scenario A: Native disk image mounting
                if self.mount_disk_images and is_disk:
                    logger.info(f"Mounting disk image for log discovery: {base_name}")
                    bd = BlockDevice(path, min_partition_size=1)
                    bd.setup()
                    mountpoints = bd.mount()
                    disks_mounted.append(bd)

                    if not mountpoints:
                        logger.warning(f"Failed to mount viable partitions in {base_name}")
                        continue

                    for mountpoint in mountpoints:
                        for root, _, files in os.walk(mountpoint):
                            for filename in files:
                                full_path = os.path.join(root, filename)
                                formatted_path = "/" + os.path.relpath(full_path, mountpoint)
                                self.check_file(full_path, formatted_path, current_evidence['paths'])

                # Scenario B: Extracted directory structures
                elif os.path.isdir(path):
                    for root, _, files in os.walk(path):
                        for filename in files:
                            full_path = os.path.join(root, filename)
                            formatted_path = "/" + os.path.relpath(full_path, path)
                            self.check_file(full_path, formatted_path, current_evidence['paths'])
                            
                # Scenario C: Direct single-file evaluation
                elif os.path.isfile(path):
                    self.check_file(path, "/" + os.path.basename(path), current_evidence['paths'])

                if current_evidence['paths']:
                    discovered_data.append(current_evidence)

        finally:
            # Critical cleanup: Ensure all active BlockDevices are unmounted even if the worker crashes
            for blockdevice in disks_mounted:
                if blockdevice:
                    logger.info(f"Unmounting image: {blockdevice.image_path}")
                    blockdevice.umount()

        # Output Generation
        if discovered_data:
            report_file = create_output_file(
                output_path,
                display_name="potential_logs_report.txt",
                data_type="openrelik:report"
            )
            with open(report_file.path, 'w') as f:
                for data in discovered_data:
                    f.write(f"Evidence ID: {data['id']}\n")
                    f.write(f"Evidence Name: {data['name']}\n\n")
                    f.write("Potential Log Files Discovered:\n")
                    f.write("-" * 50 + "\n")
                    
                    for p in sorted(data['paths']):
                        clean_path = p.replace("//", "/")
                        f.write(f"{clean_path}\n")
                    
                    f.write("\n" + "="*50 + "\n\n")
                    total_logs += len(data['paths'])
                    
            output_files.append(report_file.to_dict())

        return output_files, total_logs
