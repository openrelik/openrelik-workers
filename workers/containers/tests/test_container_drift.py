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

"""Unit tests for container drift task."""

import json
import os
import unittest

from typing import Any
from unittest.mock import patch, MagicMock

from src.container_drift import (
    create_task_report,
    _create_drift_output_files,
    run_container_drift,
    _run_containerd_drift,
    _run_docker_drift,
    _run_container_explorer,
    _get_container_drift_data,
    _flattern_container_drift_data,
    _create_drift_record,
)
from openrelik_worker_common.file_utils import OutputFile
from openrelik_worker_common.reporting import Report

from src.utils import CE_BINARY

EXPECTED_DOCKER_DRIFT: list[dict[str, Any]] = [
    {
        "container_id": "3062389c72cd1485dd7caa96bf5877623665f00e74d72c15cf35876af850a2cd",
        "container_type": "docker",
        "drift_status": "File added or modified",
        "file_name": "malware.conf",
        "file_path": "/malware.conf",
        "file_size": "26",
        "file_type": "-",
        "file_modified": "2024-12-16T00:11:41.650684303Z",
        "file_accessed": "2024-12-16T00:11:41.650684303Z",
        "file_changed": "2024-12-16T00:11:41.650684303Z",
        "file_birth": "2024-12-16T00:11:41.650684303Z",
        "file_sha256": "2b892ddd641eaa40a2a1e5471d9445a297b48a1795d5661fe387f83a56e2e6bf",
    },
    {
        "container_id": "3062389c72cd1485dd7caa96bf5877623665f00e74d72c15cf35876af850a2cd",
        "container_type": "docker",
        "drift_status": "File added or modified",
        "file_name": ".bash_history",
        "file_path": "/root/.bash_history",
        "file_size": "151",
        "file_type": "-",
        "file_modified": "2024-12-16T00:11:41.646684303Z",
        "file_accessed": "2024-12-16T00:11:41.646684303Z",
        "file_changed": "2024-12-16T00:11:41.646684303Z",
        "file_birth": "2024-12-16T00:11:41.646684303Z",
        "file_sha256": "7123e9b091819bf47ac5f2a8857d83e5bd956400f86b39deebf90ebc90e68f15",
    },
    {
        "container_id": "3062389c72cd1485dd7caa96bf5877623665f00e74d72c15cf35876af850a2cd",
        "container_type": "docker",
        "drift_status": "File added or modified",
        "file_name": "malware.bin",
        "file_path": "/root/malware.bin",
        "file_size": "1125408",
        "file_type": "executable",
        "file_modified": "2024-12-16T00:11:41.650684303Z",
        "file_accessed": "2024-12-16T00:11:41.646684303Z",
        "file_changed": "2024-12-16T00:11:41.650684303Z",
        "file_birth": "2024-12-16T00:11:41.650684303Z",
        "file_sha256": "5fd74cf5f131896d17f49ae0f6ac2a6d2ea433620650418ee879afa262259078",
    },
    {
        "container_id": "3062389c72cd1485dd7caa96bf5877623665f00e74d72c15cf35876af850a2cd",
        "container_type": "docker",
        "drift_status": "File deleted",
        "file_name": "btmp",
        "file_path": "/var/log/btmp",
        "file_size": "0",
        "file_type": "-",
        "file_modified": "2024-12-16T00:11:41.650684303Z",
        "file_accessed": "2024-12-16T00:11:41.650684303Z",
        "file_changed": "2024-12-16T00:11:41.650684303Z",
        "file_birth": "2024-12-16T00:11:41.650684303Z",
        "file_sha256": "-",
    },
]

EXPECTED_CONTAINERD_DRIFT: list[dict[str, Any]] = [
    {
        "container_id": "containerd_drift",
        "container_type": "containerd",
        "drift_status": "File added or modified",
        "file_name": "default.conf",
        "file_path": "/etc/nginx/conf.d/default.conf",
        "file_size": "1093",
        "file_type": "-",
        "file_modified": "2024-12-16T00:11:32.574684501Z",
        "file_accessed": "2024-12-16T00:11:32.574684501Z",
        "file_changed": "2024-12-16T00:11:32.574684501Z",
        "file_birth": "2024-12-16T00:11:32.574684501Z",
        "file_sha256": "efa188be1737505f5a060f88ad942f605920f227dddd9b49bcfb75a97a334ec2",
    },
    {
        "container_id": "containerd_drift",
        "container_type": "containerd",
        "drift_status": "File added or modified",
        "file_name": "malware.bin",
        "file_path": "/root/malware.bin",
        "file_size": "52280",
        "file_type": "executable",
        "file_modified": "2024-12-16T00:11:32.574684501Z",
        "file_accessed": "2024-12-16T00:11:32.574684501Z",
        "file_changed": "2024-12-16T00:11:32.574684501Z",
        "file_birth": "2024-12-16T00:11:32.574684501Z",
        "file_sha256": "7480f7cb7110af0f45b6e04b50f8d1fb2c6392cf911cb3a28c516ef1b725823e",
    },
    {
        "container_id": "containerd_drift",
        "container_type": "containerd",
        "drift_status": "File deleted",
        "file_name": "btmp",
        "file_path": "/var/log/btmp",
        "file_size": "0",
        "file_type": "-",
        "file_modified": "2024-12-16T00:11:32.574684501Z",
        "file_accessed": "2024-12-16T00:11:32.574684501Z",
        "file_changed": "2024-12-16T00:11:32.574684501Z",
        "file_birth": "2024-12-16T00:11:32.574684501Z",
        "file_sha256": "-",
    },
]


class TestContainerDrift(unittest.TestCase):
    """Unit tests for helper functions in container_drift.py."""

    def test_create_drift_record(self) -> None:
        """Tests _create_drift_record."""
        file_info_full: dict[str, Any] = {
            "file_name": "malware.bin",
            "full_path": "/root/malware.bin",
            "file_size": "1125408",
            "file_type": "executable",
            "file_modified": "2024-12-16T00:11:41.650684303Z",
            "file_accessed": "2024-12-16T00:11:41.646684303Z",
            "file_changed": "2024-12-16T00:11:41.650684303Z",
            "file_birth": "2024-12-16T00:11:41.650684303Z",
            "file_sha256": "5fd74cf5f131896d17f49ae0f6ac2a6d2ea433620650418ee879afa262259078",
        }
        record: dict[str, Any] = _create_drift_record(
            "3062389c72cd1485dd7caa96bf5877623665f00e74d72c15cf35876af850a2cd",
            "docker",
            "File added or modified",
            file_info_full,
        )
        self.assertDictEqual(record, EXPECTED_DOCKER_DRIFT[2])

        file_info_partial: dict[str, Any] = {
            "file_name": "btmp",
            "full_path": "/var/log/btmp",
            "file_size": "0",
            "file_modified": "2024-12-16T00:11:32.574684501Z",
            "file_accessed": "2024-12-16T00:11:32.574684501Z",
            "file_changed": "2024-12-16T00:11:32.574684501Z",
            "file_birth": "2024-12-16T00:11:32.574684501Z",
        }
        record = _create_drift_record(
            "containerd_drift",
            "containerd",
            "File deleted",
            file_info_partial,
        )
        self.assertDictEqual(record, EXPECTED_CONTAINERD_DRIFT[2])

    def test_flattern_container_drift_data(self) -> None:
        """Tests _flattern_container_drift_data."""
        path: str = os.path.join("test_data", "containerd_drift.json")

        with open(path, "r", encoding="utf-8") as file_handler:
            data: list[dict[str, Any]] = json.loads(file_handler.read())

            flatterned_data: list[dict[str, Any]] = _flattern_container_drift_data(data)
            self.assertEqual(len(flatterned_data), 3)
            self.assertListEqual(flatterned_data, EXPECTED_CONTAINERD_DRIFT)

    def test_get_container_drift_data(self) -> None:
        """Tests _get_container_drift_data."""
        path: str = os.path.join("test_data", "docker_drift.json")

        data: list[dict[str, Any]] = _get_container_drift_data(path)
        self.assertEqual(len(data), 4)
        self.assertListEqual(data, EXPECTED_DOCKER_DRIFT)

        path = os.path.join("test_data", "containerd_drift.json")
        data = _get_container_drift_data(path)
        self.assertEqual(len(data), 3)
        self.assertListEqual(data, EXPECTED_CONTAINERD_DRIFT)

    @patch("src.container_drift.subprocess.run")
    def test_run_container_explorer(self, mock_subprocess_run: MagicMock) -> None:
        """Tests _run_container_explorer."""
        command: list[str] = [CE_BINARY, "fake", "command"]
        output_file_path: str = os.path.join("test_data", "containerd_drift.json")

        mock_subprocess_run.return_value = MagicMock(returncode=0)

        data: list[dict[str, Any]] = _run_container_explorer(command, output_file_path)
        mock_subprocess_run.assert_called_once_with(
            command, capture_output=True, check=False, text=True
        )

        self.assertEqual(len(data), 3)
        self.assertListEqual(data, EXPECTED_CONTAINERD_DRIFT)

    @patch("src.container_drift.create_output_file")
    @patch("src.container_drift._run_container_explorer")
    def test_run_docker_drift(
        self, mock_run_container_explorer: MagicMock, mock_output_file: MagicMock
    ) -> None:
        """Tests _run_docker_drift."""
        mountpoint: str = "/fake/mountpoint"
        temp_dir: str = "test_data"

        mock_run_container_explorer.return_value = _get_container_drift_data(
            os.path.join("test_data", "docker_drift.json")
        )

        data: list[dict[str, Any]] = _run_docker_drift(mountpoint, temp_dir)
        self.assertEqual(len(data), 4)
        self.assertListEqual(data, EXPECTED_DOCKER_DRIFT)

    @patch("src.container_drift.create_output_file")
    @patch("src.container_drift._run_container_explorer")
    def test_run_containerd_drift(
        self, mock_run_container_explorer: MagicMock, mock_output_file: MagicMock
    ) -> None:
        """Tests _run_docker_drift."""
        mountpoint: str = "/fake/mountpoint"
        temp_dir: str = "test_data"

        mock_run_container_explorer.return_value = _get_container_drift_data(
            os.path.join("test_data", "containerd_drift.json")
        )

        data: list[dict[str, Any]] = _run_containerd_drift(mountpoint, temp_dir)
        self.assertEqual(len(data), 3)
        self.assertListEqual(data, EXPECTED_CONTAINERD_DRIFT)

    @patch("src.container_drift.os.mkdir")
    @patch("src.container_drift._run_containerd_drift")
    @patch("src.container_drift._run_docker_drift")
    @patch("src.container_drift.os.path.exists")
    @patch("src.container_drift.shutil.rmtree")
    def test_run_container_drift_success(
        self,
        mock_shutil_rmtree,
        mock_path_exists,
        mock_run_docker_drift,
        mock_run_containerd_drift,
        mock_os_mkdir,
    ) -> None:
        """Tests run_container_drift."""
        mock_path_exists.return_value = True

        input_file: dict[str, Any] = {
            "path": "/fake/path",
            "id": "disk1.raw",
        }
        output_path: str = "/fake/output/path"
        mountpoint: str = "/fake/mountpoint"

        log_file: MagicMock = MagicMock(spec=OutputFile)
        log_file.path = "/fake/log/path"

        # Get _run_containerd_drift output
        mock_run_containerd_drift.return_value = _get_container_drift_data(
            os.path.join("test_data", "containerd_drift.json")
        )
        # Get _run_docker_drift output
        mock_run_docker_drift.return_value = _get_container_drift_data(
            os.path.join("test_data", "docker_drift.json")
        )

        data: list[dict[str, Any]] = run_container_drift(
            input_file, output_path, log_file, mountpoint
        )
        self.assertEqual(len(data), 7)
        self.assertListEqual(data, EXPECTED_CONTAINERD_DRIFT + EXPECTED_DOCKER_DRIFT)

    @patch("src.container_drift.shutil.rmtree")
    @patch("src.container_drift.os.path.exists")
    @patch("src.container_drift._run_docker_drift")
    @patch("src.container_drift._run_containerd_drift")
    @patch("src.container_drift.os.mkdir")
    @patch("src.container_drift.os.path.join")
    @patch("src.container_drift.uuid4")
    def test_run_container_drift_no_data(
        self,
        mock_uuid4: MagicMock,
        mock_os_path_join: MagicMock,
        mock_os_mkdir: MagicMock,
        mocK_run_containerd_drift: MagicMock,
        mock_run_docker_drift: MagicMock,
        mock_os_path_exists: MagicMock,
        mock_shutuil_rmtree: MagicMock,
    ) -> None:
        """Tests run_container_drift with no data."""
        mocK_run_containerd_drift.return_value = []
        mock_run_docker_drift.return_value = []
        mock_os_path_exists.return_value = True

        input_file: dict[str, Any] = {
            "path": "/fake/path",
            "id": "disk1.raw",
        }

        output_path: str = "/fake/output/path"
        mountpoint: str = "/fake/mountpoint"

        log_file: MagicMock = MagicMock(spec=OutputFile)
        log_file.path = "/fake/log/path"

        result: list[dict] = run_container_drift(
            input_file, output_path, log_file, mountpoint
        )
        self.assertListEqual(result, [])
        mock_shutuil_rmtree.assert_called_once()

    def test_create_drift_output_files(self) -> None:
        """Tests _create_drift_output_files."""
        output_path: str = "/tmp/container_drift"
        os.makedirs(output_path, exist_ok=True)

        data: list[dict[str, Any]] = EXPECTED_CONTAINERD_DRIFT + EXPECTED_DOCKER_DRIFT

        result: list[dict[str, Any]] = _create_drift_output_files(output_path, data)
        self.assertEqual(len(result), 2)

        result_filepaths: list[str] = [r.get("display_name", "") for r in result]
        expected_filepaths: list[str] = [
            "container_drift.json",
            "container_drift.csv",
        ]
        self.assertListEqual(result_filepaths, expected_filepaths)

    def test_create_task_report(self) -> None:
        """Tests create_task_report."""
        output_path: str = "/tmp/container_drift"
        os.makedirs(output_path, exist_ok=True)

        data: list[dict[str, Any]] = EXPECTED_CONTAINERD_DRIFT + EXPECTED_DOCKER_DRIFT

        output_files: list[dict[str, Any]] = _create_drift_output_files(
            output_path, data
        )

        report: Report = create_task_report(output_files)
        self.assertEqual(len(report.sections), 1)

        expected_markdown_report: str = """# Container Drift Report

* 2 output files created
* 7 files added, modified, or deleted"""
        self.assertEqual(str(report.to_markdown()), expected_markdown_report)


if __name__ == "__main__":
    unittest.main()
