# Copyright 2024 Google LLC
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

from .analyzers.llm_analyzer import analyze_text_content
from .factory import task_factory
from openrelik_ai_common.providers import config

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-analyzer-config.tasks.llm_analyzer"
TASK_NAME_SHORT = "llm_analyzer"

LLM_ARTIFACTS = [
    # Keep sorted
    "*:artifact:ApacheAccessLogs",
    "*:artifact:ApacheConfigurationFolder",
    "*:artifact:BashShellConfigurationFile",
    "*:artifact:BashShellHistoryFile",
    "*:artifact:BashShellSessionFile",
    "*:artifact:BourneShellHistoryFile",
    "*:artifact:CShellConfigurationFile",
    "*:artifact:ContainerdConfig",
    "*:artifact:ContainerdLogs",
    "*:artifact:DNSResolvConfFile",
    "*:artifact:DockerContainerConfig",
    "*:artifact:ElasticsearchAccessLog",
    "*:artifact:ElasticsearchAuditLog",
    "*:artifact:ElasticsearchLogs",
    "*:artifact:ElasticsearchServerLog",
    "*:artifact:FishShellConfigurationFile",
    "*:artifact:FishShellHistoryFile",
    "*:artifact:GKEDockerContainerLogs",
    "*:artifact:HadoopAppLogs",
    "*:artifact:HadoopYarnLogs",
    "*:artifact:JupyterConfigFile",
    "*:artifact:KornShellConfigurationFile",
    "*:artifact:LinuxAuthLogs",
    "*:artifact:LinuxCronLogs",
    "*:artifact:LoginPolicyConfiguration",
    "*:artifact:MicrosoftIISLogs",
    "*:artifact:MongoDBConfigurationFile",
    "*:artifact:MongoDBLogFiles",
    "*:artifact:MySQLConfigurationFiles",
    "*:artifact:MySQLHistoryFile",
    "*:artifact:MySQLLogFiles",
    "*:artifact:NfsExportsFile",
    "*:artifact:NginxAccessLogs",
    "*:artifact:OpenSearchLogFiles",
    "*:artifact:PostgreSQLConfigurationFiles",
    "*:artifact:PostgreSQLHistoryFile",
    "*:artifact:PostgreSQLLogFiles",
    "*:artifact:PythonHistoryFile",
    "*:artifact:RedisConfigFile",
    "*:artifact:RedisConfigurationFile",
    "*:artifact:RedisLogFiles",
    "*:artifact:RootUserShellConfigs",
    "*:artifact:RootUserShellHistory",
    "*:artifact:SSHAuthorizedKeysFiles",
    "*:artifact:SambaConfigFile",
    "*:artifact:ShellConfigurationFile",
    "*:artifact:ShellHistoryFile",
    "*:artifact:ShellLogoutFile",
    "*:artifact:ShellProfileFile",
    "*:artifact:SshUserConfigFile",
    "*:artifact:SshdConfigFile",
    "*:artifact:TeeShellConfigurationFile",
    "*:artifact:WindowsScheduledTasks",
    "*:artifact:WordpressConfigFile",
    "*:artifact:ZShellConfigurationFile",
    "*:artifact:ZShellHistoryFile",
]

COMPATIBLE_INPUTS = {
    "data_types": LLM_ARTIFACTS,
    "mime_types": [
        "text/plain",
        "application/xml",
        "text/xml",
        "application/xml",
        "application/atom+xml",
        "application/svg+xml",
        "application/json",
        "text/yaml",
        "application/x-yaml",
        "application/toml",
        "text/plain",
        "text/csv",
    ],
    "filenames": ["config.xml", "config.yaml"],
}

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "LLM Analyzer",
    "description": "Analyze config, log and history text-files using LLM",
    "compatible_inputs": COMPATIBLE_INPUTS,
    "task_config": [
        {
            "name": "llm_provider",
            "label": "LLM Provider",
            "description": "Select one and only one LLM provider. Selected provider configs must be provided. Default is 'googleai'.",
            "type": "autocomplete",
            "items": config.PROVIDER_CONFIG,
            "required": False,
        },
        {
            "name": "llm_model",
            "label": "LLM Model",
            "description": "Specify an LLM model. If empty, then per provider default is extracted from configs.",
            "type": "text",
            "required": False,
        },
        {
            "name": "model_max_input_tokens",
            "label": "LLM Model maximum allowed input tokens",
            "description": "Specify max. allowed input tokens of the model. If empty model limit will be used except if ollama is used then a hardcoded limit applies for all models.",
            "type": "text",
            "required": False,
        },
    ],
}


logger.info("LLM Analyzer task starts!")

task_factory(
    task_name=TASK_NAME,
    task_name_short=TASK_NAME_SHORT,
    compatible_inputs=COMPATIBLE_INPUTS,
    task_metadata=TASK_METADATA,
    analysis_function=analyze_text_content,
    task_report_function=None,
)
