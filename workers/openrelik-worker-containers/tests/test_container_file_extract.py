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

"""Unit tests for OpenRelik container_drift task."""

import logging
import os
import shutil
import unittest
from unittest.mock import patch, MagicMock

from typing import Any

from src.container_file_extract import (
    _archive_and_extract_directory,
    _extract_regular_file,
    _extract_file_and_directory,
    _get_containers_info,
    run_container_file_extraction,
)

logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TestContainerFileExtract(unittest.TestCase):
    """Unit test for OpenRelik container file extract."""

    def _build_container_content(self, container_mount_dir: str) -> None:
        """Build a mock container content"""
        test_data_dir: str = os.path.join("test_data", "etc")

        logger.debug("Copying %s to %s", test_data_dir, container_mount_dir)
        shutil.copytree(
            test_data_dir, os.path.join(container_mount_dir, "etc"), dirs_exist_ok=True
        )

    def test_archive_and_export_directory_success(self) -> None:
        """Test archive and export directory"""
        logger.debug("TestCase: Archive and export of a valid directory")

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_container_mount_dir: str = "/tmp/mock/container_mount_dir"
        if os.path.exists(mock_container_mount_dir):
            shutil.rmtree(mock_container_mount_dir)
        os.makedirs(mock_container_mount_dir)
        logger.debug("Mock container_mount_dir: %s", mock_container_mount_dir)

        mock_original_path: str = "/etc"
        logger.debug("Mock original_path: %s", mock_original_path)

        # Update the mock container mountpoint with some files and directories.
        self._build_container_content(mock_container_mount_dir)

        mock_file_path: str = os.path.join(
            mock_container_mount_dir, mock_original_path.strip("/")
        )
        logger.debug("Mock file_path: %s", mock_file_path)

        output_file: dict[str, Any] = _archive_and_extract_directory(
            output_path=mock_output_path,
            file_path=mock_file_path,
            original_path=mock_original_path,
        )

        self.assertIsNotNone(output_file)
        self.assertEqual(output_file.get("display_name"), "etc.tar")

    def test_archive_and_export_directory_invalid_path(self) -> None:
        """Test archive and export directory"""
        logger.debug("TestCase: Archive and export of an invalid directory path")

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_container_mount_dir: str = "/tmp/mock/container_mount_dir"
        if os.path.exists(mock_container_mount_dir):
            shutil.rmtree(mock_container_mount_dir)
        os.makedirs(mock_container_mount_dir)
        logger.debug("Mock container_mount_dir: %s", mock_container_mount_dir)

        mock_original_path: str = "/invalid_path"
        logger.debug("Mock original_path: %s", mock_original_path)

        # Update the mock container mountpoint with some files and directories.
        self._build_container_content(mock_container_mount_dir)

        mock_file_path: str = os.path.join(
            mock_container_mount_dir, mock_original_path.strip("/")
        )
        logger.debug("Mock file_path: %s", mock_file_path)

        output_file: dict[str, Any] = _archive_and_extract_directory(
            output_path=mock_output_path,
            file_path=mock_file_path,
            original_path=mock_original_path,
        )

        self.assertRaises(FileNotFoundError)
        self.assertDictEqual(output_file, {})

    def test_archive_and_export_directory_generic_exception(self) -> None:
        """Test archive and export directory"""
        logger.debug(
            "TestCase: Archive and export of a directory with generic exception"
        )

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_container_mount_dir: str = "/tmp/mock/container_mount_dir"
        if os.path.exists(mock_container_mount_dir):
            shutil.rmtree(mock_container_mount_dir)
        os.makedirs(mock_container_mount_dir)
        logger.debug("Mock container_mount_dir: %s", mock_container_mount_dir)

        mock_original_path: str = "/invalid_path"
        logger.debug("Mock original_path: %s", mock_original_path)

        # Update the mock container mountpoint with some files and directories.
        self._build_container_content(mock_container_mount_dir)

        mock_file_path: str = os.path.join(
            mock_container_mount_dir, mock_original_path.strip("/")
        )
        logger.debug("Mock file_path: %s", mock_file_path)

        output_file: dict[str, Any] = _archive_and_extract_directory(
            output_path=mock_output_path,
            file_path=mock_file_path,
            original_path=mock_original_path,
            archive_format="invalid_format",
        )

        self.assertDictEqual(output_file, {})

    def test_export_regular_file_success(self) -> None:
        """Test export of a regular file"""
        logger.debug("TestCase: Successful export of a regular file.")

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_container_mount_dir: str = "/tmp/mock/container_mount_dir"
        if os.path.exists(mock_container_mount_dir):
            shutil.rmtree(mock_container_mount_dir)
        os.makedirs(mock_container_mount_dir)
        logger.debug("Mock container_mount_dir: %s", mock_container_mount_dir)

        mock_original_path: str = "/etc/passwd"
        logger.debug("Mock original_path: %s", mock_original_path)

        # Update the mock container mountpoint with some files and directories.
        self._build_container_content(mock_container_mount_dir)

        mock_file_path: str = os.path.join(
            mock_container_mount_dir, mock_original_path.strip("/")
        )
        logger.debug("Mock file_path: %s", mock_file_path)

        output_file: dict[str, Any] = _extract_regular_file(
            output_path=mock_output_path,
            file_path=mock_file_path,
            original_path=mock_original_path,
        )

        self.assertIsNotNone(output_file)
        self.assertEqual(output_file.get("display_name"), "passwd")
        self.assertEqual(output_file.get("original_path"), "/etc/passwd")

    def test_export_regular_file_invalid_path(self) -> None:
        """Test export of an invalid path"""
        logger.debug("TestCase: Export of an invalid path")

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_container_mount_dir: str = "/tmp/mock/container_mount_dir"
        if os.path.exists(mock_container_mount_dir):
            shutil.rmtree(mock_container_mount_dir)
        os.makedirs(mock_container_mount_dir)
        logger.debug("Mock container_mount_dir: %s", mock_container_mount_dir)

        mock_original_path: str = "/etc/invalid_file"
        logger.debug("Mock original_path: %s", mock_original_path)

        # Update the mock container mountpoint with some files and directories.
        self._build_container_content(mock_container_mount_dir)

        mock_file_path: str = os.path.join(
            mock_container_mount_dir, mock_original_path.strip("/")
        )
        logger.debug("Mock file_path: %s", mock_file_path)

        output_file: dict[str, Any] = _extract_regular_file(
            output_path=mock_output_path,
            file_path=mock_file_path,
            original_path=mock_original_path,
        )

        self.assertIsNotNone(output_file)
        self.assertEqual(output_file.get("display_name"), None)
        self.assertEqual(output_file.get("original_path"), None)

    def test_extract_file_and_directory(self) -> None:
        """Test extract files and directories"""
        logger.debug("TestCase: Successful extraction of files and directories.")

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path, exist_ok=True)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_mountpoint: str = "/tmp/mock/mountpoint"
        if os.path.exists(mock_mountpoint):
            shutil.rmtree(mock_mountpoint)
        os.makedirs(mock_mountpoint)
        logger.debug("Mock mountpoint: %s", mock_mountpoint)

        # Path of files to extract.
        mock_file_paths: list[str] = ["/etc/invalid_file", "/etc/passwd", "/etc/pam.d"]
        logger.debug("Mock original_path: %s", ", ".join(mock_file_paths))

        # Update the mock container mountpoint with some files and directories.
        self._build_container_content(mock_mountpoint)

        output_files: list[dict[str, Any]] = _extract_file_and_directory(
            output_path=mock_output_path,
            mountpoint=mock_mountpoint,
            file_paths=mock_file_paths,
        )

        self.assertEqual(len(output_files), 2)

        display_names: list[str] = [
            output_file.get("display_name", "") for output_file in output_files
        ]
        self.assertIn("passwd", display_names)
        self.assertIn("pam.d.tar", display_names)

    @patch("src.container_file_extract.list_containers")
    def test_get_containers_info_success(self, mock_list_containers) -> None:
        """Test getting container information"""
        logger.debug("TestCase: Successfully get containers information.")

        mock_output_file: MagicMock = MagicMock(__spec__="OutputFile")
        mock_output_file.path = os.path.join("test_data", "container_list.json")

        logger.debug("Mock output_path: %s", mock_output_file.path)

        mock_list_containers.return_value = mock_output_file

        mock_input_file: dict[str, Any] = {
            "id": "sample.raw",
            "path": "/tmp/mock/sample.raw",
            "display_name": "sample.raw",
            "extension": "raw",
        }

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path, exist_ok=True)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_log_file: MagicMock = MagicMock(__spec__="OutputFile")
        mock_log_file.path = os.path.join(
            mock_output_path, "container_file_extract.log"
        )
        mock_log_file.display_name = "container_file_extract"
        mock_log_file.extension = "log"

        mock_mountpoint: str = "/tmp/mock/mountpoint"

        containers: dict[str, Any] = _get_containers_info(
            input_file=mock_input_file,
            output_path=mock_output_path,
            log_file=mock_log_file,
            mountpoint=mock_mountpoint,
        )

        self.assertEqual(len(containers), 2)

        container_ids: list[str] = list(containers.keys())
        self.assertListEqual(
            container_ids,
            [
                "containerd_drift",
                "3062389c72cd1485dd7caa96bf5877623665f00e74d72c15cf35876af850a2cd",
            ],
        )

    @patch("src.container_file_extract.list_containers")
    def test_get_containers_info_invalid_list_container_file(
        self, mock_list_containers
    ) -> None:
        """Test getting containers information failure."""
        logger.debug("TestCase: Failed to get containers information.")
        mock_output_file: MagicMock = MagicMock(__spec__="OutputFile")
        mock_output_file.path = os.path.join("test_data", "invalid_container_list.json")

        logger.debug("Mock output_path: %s", mock_output_file.path)

        mock_list_containers.return_value = mock_output_file

        mock_input_file: dict[str, Any] = {
            "id": "sample.raw",
            "path": "/tmp/mock/sample.raw",
            "display_name": "sample.raw",
            "extension": "raw",
        }

        mock_output_path: str = "/tmp/mock/output_path"
        if os.path.exists(mock_output_path):
            shutil.rmtree(mock_output_path)
        os.makedirs(mock_output_path, exist_ok=True)
        logger.debug("Mock output_path: %s", mock_output_path)

        mock_log_file: MagicMock = MagicMock(__spec__="OutputFile")
        mock_log_file.path = os.path.join(
            mock_output_path, "container_file_extract.log"
        )
        mock_log_file.display_name = "container_file_extract"
        mock_log_file.extension = "log"

        mock_mountpoint: str = "/tmp/mock/mountpoint"

        containers: dict[str, Any] = _get_containers_info(
            input_file=mock_input_file,
            output_path=mock_output_path,
            log_file=mock_log_file,
            mountpoint=mock_mountpoint,
        )

        self.assertEqual(len(containers), 0)
        self.assertDictEqual(containers, {})

    @patch("src.container_file_extract._get_containers_info")
    @patch("src.container_file_extract.uuid4")
    @patch("src.container_file_extract.os.mkdir")
    @patch("src.container_file_extract.shutil.rmtree")
    @patch("src.container_file_extract.mount_container")
    @patch("src.container_file_extract.unmount_container")
    @patch("src.container_file_extract._extract_file_and_directory")
    def test_run_container_file_extraction(
        self,
        mock_extract_file_and_directory,
        mock_unmount_container,
        mock_mount_container,
        mock_shutil_rmtree,
        mock_os_mkdir,
        mock_uuid4,
        mock_get_containers_info,
    ) -> None:
        """Test successful execution of run_container_file_extraction."""
        logger.debug("TestCase: Successful run_container_file_extraction")

        # 1. Setup Mocks
        mock_input_file_id = "test_disk.raw"
        mock_input_file_display_name = "Test Disk Image"
        mock_input_file: dict[str, Any] = {
            "id": mock_input_file_id,
            "display_name": mock_input_file_display_name,
            # Other fields like 'path', 'extension' are not directly used by run_container_file_extraction
        }

        mock_output_path: str = "/tmp/test_output"
        mock_log_file: MagicMock = MagicMock(
            spec_set=["path", "display_name", "extension"]
        )
        mock_log_file.path = os.path.join(mock_output_path, "test_task.log")
        mock_disk_mountpoint: str = "/mnt/mock_disk"

        container_id_to_process = "container_abc123"
        container_namespace_to_process = "test_namespace"
        mock_container_ids_to_process: list[str] = [container_id_to_process]
        mock_file_paths_to_extract: list[str] = ["/etc/passwd", "/var/log/messages"]

        # Mock for _get_containers_info
        mock_containers_data: dict[str, dict[str, str]] = {
            container_id_to_process: {
                "ID": container_id_to_process,
                "Namespace": container_namespace_to_process,
            },
            "other_container": {"ID": "other_container", "Namespace": "other_ns"},
        }
        mock_get_containers_info.return_value = mock_containers_data

        # Mock for uuid4 and temporary container mount directory
        mock_uuid_hex = "abcdef123456"
        mock_uuid4.return_value = MagicMock(hex=mock_uuid_hex)
        expected_temp_container_mount_dir: str = os.path.join(
            mock_output_path, mock_uuid_hex[:6]
        )

        # Mock for mount_container
        mock_mount_container.return_value = expected_temp_container_mount_dir

        # Mock for _extract_file_and_directory
        mock_extracted_output_files_data: list[dict[str, str]] = [
            {
                "id": "file1",
                "path": "/tmp/test_output/passwd",
                "display_name": "passwd",
            },
            {
                "id": "file2",
                "path": "/tmp/test_output/messages.tar",
                "display_name": "messages.tar",
            },
        ]
        mock_extract_file_and_directory.return_value = mock_extracted_output_files_data

        # 2. Call the function
        extracted_files: list[dict[str, Any]] = run_container_file_extraction(
            input_file=mock_input_file,
            output_path=mock_output_path,
            log_file=mock_log_file,
            disk_mountpoint=mock_disk_mountpoint,
            container_ids=mock_container_ids_to_process,
            file_paths=mock_file_paths_to_extract,
        )

        # 3. Assertions
        mock_get_containers_info.assert_called_once_with(
            mock_input_file, mock_output_path, mock_log_file, mock_disk_mountpoint
        )
        mock_uuid4.assert_called_once()
        mock_os_mkdir.assert_called_once_with(expected_temp_container_mount_dir)
        mock_mount_container.assert_called_once_with(
            container_id_to_process,
            container_namespace_to_process,
            mock_disk_mountpoint,
            expected_temp_container_mount_dir,
        )
        mock_extract_file_and_directory.assert_called_once_with(
            mock_output_path,
            expected_temp_container_mount_dir,
            mock_file_paths_to_extract,
        )
        mock_unmount_container.assert_called_once_with(
            container_id_to_process, expected_temp_container_mount_dir
        )
        mock_shutil_rmtree.assert_called_once_with(expected_temp_container_mount_dir)

        self.assertEqual(extracted_files, mock_extracted_output_files_data)


if __name__ == "__main__":
    unittest.main()
