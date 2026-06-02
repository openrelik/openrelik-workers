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

from openrelik_worker_common.reporting import Report, Priority
from openrelik_worker_common.password_utils import bruteforce_password_hashes


def analyze_accts(file_content: str, file_name: str = "shadow") -> Report:
    """Extract accounts from Linux shadow files.

    Args:
      file_content (str): file content.
      file_name (str): Original file name (and optionally path)

    Returns:
        report (Report): The analysis report.
    """
    version = None
    shadow = file_content.split('\n')

    extracted_credentials = _extract_linux_credentials(shadow)

    return analyse_shadow_file(shadow=shadow,
                               path=file_name,
                               hashes=extracted_credentials)


def _extract_linux_credentials(shadow):
    """Extract credentials from a Linux shadow files.

    Args:
        shadow (list): shadow file contents (list of str).

    Returns:
        dict: of hash against username.
    """
    hash_names = {}
    for line in shadow:
        try:
            (username, password_hash, _) = line.split(':', maxsplit=2)
        except ValueError:
            continue
        hash_names[password_hash] = username
    return hash_names


def analyse_shadow_file(shadow, path, hashes, timeout=300):
    """Analyses a Linux shadow file.

    Args:
      shadow (list): shadow file content (list of str).
      path (str): File path that these hashes came from.
      hashes (dict): dict of hashes to usernames
      timeout (int): Time in seconds to run password bruteforcing.

    Returns:
      Report
    """
    report = Report("Linux Account Analyzer")
    summary_section = report.add_section()
    details_section = report.add_section()
    priority = Priority.LOW

    weak_passwords = bruteforce_password_hashes(
        shadow,
        tmp_dir=None,
        password_list_file_path="/openrelik/password.lst",
        password_rules_file_path="/openrelik/openrelik-password-cracking.rules",
        timeout=timeout)

    if weak_passwords:
        priority = Priority.CRITICAL
        report.summary = f'Shadow file analysis of {path} found {len(weak_passwords):n} weak password(s)'
        line = f'{len(weak_passwords):n} weak password(s) found:'
        details_section.add_bullet(line)
        for password_hash, plaintext in weak_passwords:
            line = f"""User '{hashes[password_hash]:s}' with password '{plaintext:s}'"""
            details_section.add_bullet(line, level=2)
    else:
        report.summary = "No weak passwords found"

    summary_section.add_paragraph(report.summary)
    return report
