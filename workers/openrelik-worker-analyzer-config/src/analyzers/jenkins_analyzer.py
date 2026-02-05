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

from openrelik_worker_common.password_utils import bruteforce_password_hashes
from openrelik_worker_common.reporting import Priority, Report


def analyze_config(input_file: dict, task_config: dict) -> Report:
    """Extract security related configs from Jenkins configuration files.

    Args:
      input_file: The input file dictionary.
      task_config: The task configuration dictionary.

    Returns:
        report (Report): The analysis report.
    """
    version = None
    credentials = []
    # Read the input file to be analyzed.
    with open(input_file.get("path"), "r", encoding="utf-8") as fh:
        config = fh.read()

    extracted_version = _extract_jenkins_version(config)
    if extracted_version:
        version = extracted_version

    extracted_credentials = _extract_jenkins_credentials(config)
    credentials.extend(extracted_credentials)

    return analyze_jenkins(version, credentials, timeout=None)


def _extract_jenkins_version(config):
    """Extract version from Jenkins configuration files.

    Args:
      config (str): configuration file content.

    Returns:
      str: The version of Jenkins.
    """
    version = None
    version_re = re.compile("<version>(.*)</version>")
    version_match = re.search(version_re, config)

    if version_match:
        version = version_match.group(1)

    return version


def _extract_jenkins_credentials(config):
    """Extract credentials from Jenkins configuration files.

    Args:
      config (str): configuration file content.

    Returns:
      list: of tuples with username and password hash.
    """
    credentials = []
    password_hash_re = re.compile("<passwordHash>#jbcrypt:(.*)</passwordHash>")
    username_re = re.compile("<fullName>(.*)</fullName>")

    password_hash_match = re.search(password_hash_re, config)
    username_match = re.search(username_re, config)

    if username_match and password_hash_match:
        username = username_match.group(1)
        password_hash = password_hash_match.group(1)
        credentials.append((username, password_hash))

    return credentials


def analyze_jenkins(version, credentials, timeout=300):
    """Analyses a Jenkins configuration.

    Args:
      version (str): Version of Jenkins.
      credentials (list): of tuples with username and password hash.
      timeout (int): Time in seconds to run password bruteforcing.

    Returns:
      report (Report): The analysis report.
    """
    report = Report()
    details_section = report.add_section()

    credentials_registry = {hash: username for username, hash in credentials}

    # "3200" is "bcrypt $2*$, Blowfish (Unix)"
    weak_passwords = bruteforce_password_hashes(
        credentials_registry.keys(),
        tmp_dir=None,
        password_list_file_path="/openrelik/password.lst",
        password_rules_file_path="/openrelik/openrelik-password-cracking.rules",
        timeout=timeout,
        extra_args="-m 3200",
    )

    if not version:
        version = "Unknown"
    details_section.add_bullet(f"Jenkins version: {version:s}")

    if weak_passwords:
        report.priority = Priority.CRITICAL
        report.summary = "Jenkins analysis found potential issues"

        line = f"{len(weak_passwords):n} weak password(s) found:"
        details_section.add_bullet(line)
        for password_hash, plaintext in weak_passwords:
            line = 'User "{0:s}" with password "{1:s}"'.format(
                credentials_registry.get(password_hash), plaintext
            )
            details_section.add_bullet(line, level=2)
    elif credentials_registry or version != "Unknown":
        report.priority = Priority.MEDIUM
        report.summary = (
            f"Jenkins version {version} found with {len(credentials_registry)} "
            "credentials, but no issues detected"
        )
    else:
        report.priority = Priority.LOW
        report.summary = "No Jenkins instance found"

    return report
