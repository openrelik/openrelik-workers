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

import base64
import os
import unittest
from unittest.mock import patch, MagicMock, call, ANY
from uuid import uuid4

from openrelik_worker_common.file_utils import create_output_file

from src.container_export import (
    export_container,
    export_all_containers,
)

mock_log_file_instance = MagicMock()
mock_log_file_instance.path = "/fake/output/container_export.log"
mock_log_file_instance.to_dict.return_value = {
    "path": "/fake/output/container_export.log",
    "display_name": "container_export",
}


class TestContainerExport(unittest.TestCase):
    """Unit test for OpenRelik container export."""

    def setUp(self):
        self.input_file = MagicMock()
        self.input_file.id = "disk.raw"
        self.input_file.path = "/fake/disk.raw"
        self.input_file.get.return_value = "disk.raw"

        self.output_path = "/fake/output"
        self.log_file = mock_log_file_instance
        self.disk_mount_dir = "/mnt/disk"
        self.container_id = "container_abcdef"
        self.workflow_id = "test_workflow_id"
        self.task_config = {"export_image": True, "export_archive": None}

    @patch("src.container_export.logger")
    @patch("src.container_export.os.path.join")
    @patch("src.container_export.os.mkdir")
    @patch("src.container_export.os.listdir")
    @patch("src.container_export.create_output_file")
    @patch("src.container_export.subprocess.run")
    @patch("src.container_export.shutil.move")
    @patch("src.container_export.log_entry")
    @patch("src.container_export.shutil.rmtree")
    def test_export_container_success(
        self,
        mock_shutil_rmtree,
        mock_log_entry,
        mock_shutil_move,
        mock_subprocess_run,
        mock_create_output_file,
        mock_os_listdir,
        mock_os_mkdir,
        mock_os_path_join,
        mock_logger,
    ):
        """Test successful container export."""
        exported_file = f"{self.container_id}.raw"
        mock_output_file = MagicMock()
        mock_output_file.path = "/fake/output/container_abcdef.raw"
        mock_output_file.return_value = "container_abcdef.raw"
        mock_output_file.display_name = "container_abcdef.raw"
        mock_output_file.to_dict.return_value = {
            "path": "/fake/output/container_abcdef.raw",
            "display_name": "container_abcdef",
            "id": "disk.raw",
        }

        mock_os_path_join.return_value = "/fake/output/container_export_dir"
        mock_os_listdir.return_value = [exported_file]
        mock_subprocess_run.return_value = MagicMock(returncode=0, stderr="")
        mock_create_output_file.return_value = mock_output_file

        result = export_container(
            self.input_file,
            self.output_path,
            self.log_file,
            self.disk_mount_dir,
            self.container_id,
            self.task_config,
        )

        mock_create_output_file.assert_called_once_with(
            self.output_path,
            display_name=exported_file,
            data_type="image",
            extension="raw",
            source_file_id="disk.raw",
        )

        self.assertEqual(result, [mock_output_file])

    @patch("src.container_export.logger")
    @patch("src.container_export.os.path.join")
    @patch("src.container_export.os.mkdir")
    @patch("src.container_export.os.listdir")
    @patch("src.container_export.create_output_file")
    @patch("src.container_export.subprocess.run")
    @patch("src.container_export.shutil.move")
    @patch("src.container_export.log_entry")
    @patch("src.container_export.shutil.rmtree")
    def test_export_container_failure(
        self,
        mock_shutil_rmtree,
        mock_log_entry,
        mock_shutil_move,
        mock_subprocess_run,
        mock_create_output_file,
        mock_os_listdir,
        mock_os_mkdir,
        mock_os_path_join,
        mock_logger,
    ):
        """Test failure container export."""
        exported_file = f"{self.container_id}.raw"
        mock_output_file = MagicMock()
        mock_output_file.path = "/fake/output/container_abcdef.raw"
        mock_output_file.return_value = "container_abcdef.raw"
        mock_output_file.display_name = "container_abcdef.raw"
        mock_output_file.to_dict.return_value = {
            "path": "/fake/output/container_abcdef.raw",
            "display_name": "container_abcdef",
            "id": "disk.raw",
        }

        mock_os_path_join.return_value = "/fake/output/container_export_dir"
        mock_os_listdir.return_value = [exported_file]
        mock_subprocess_run.return_value = MagicMock(
            returncode=1, stdout="out", stderr="err"
        )
        mock_create_output_file.return_value = mock_output_file

        result = export_container(
            self.input_file,
            self.output_path,
            self.log_file,
            self.disk_mount_dir,
            self.container_id,
            self.task_config,
        )

        container_id = self.container_id
        disk_name = self.input_file.get("id")

        mock_log_file = mock_log_file_instance
        mock_log_entry.assert_called_once_with(
            mock_log_file,
            f"Error exporting container {container_id}",
        )

        self.assertEqual(result, [])

    @patch("src.container_export.logger")
    @patch("src.container_export.os.path.join")
    @patch("src.container_export.os.mkdir")
    @patch("src.container_export.os.listdir")
    @patch("src.container_export.create_output_file")
    @patch("src.container_export.subprocess.run")
    @patch("src.container_export.shutil.move")
    @patch("src.container_export.log_entry")
    @patch("src.container_export.shutil.rmtree")
    def test_export_all_containers_success(
        self,
        mock_shutil_rmtree,
        mock_log_entry,
        mock_shutil_move,
        mock_subprocess_run,
        mock_create_output_file,
        mock_os_listdir,
        mock_os_mkdir,
        mock_os_path_join,
        mock_logger,
    ):
        """Test successful container export."""
        mock_output_file_1 = MagicMock(
            path="/fake/output/container_1.raw",
            display_name="container_1.raw",
            id="disk.raw",
        )
        mock_output_file_1.to_dict.return_value = {
            "path": "/fake/output/container_1.raw",
            "display_name": "container_1.raw",
            "id": "disk.raw",
        }

        mock_output_file_2 = MagicMock(
            path="/fake/output/container_2.raw",
            display_name="container_2.raw",
            id="disk.raw",
        )
        mock_output_file_2.to_dict.return_value = {
            "path": "/fake/output/container_2.raw",
            "display_name": "container_2.raw",
            "id": "disk.raw",
        }

        exported_file_1 = "container_1.raw"
        exported_file_2 = "container_2.raw"

        mock_os_path_join.return_value = "/fake/output/container_export_dir"
        mock_os_listdir.return_value = [exported_file_1, exported_file_2]

        mock_subprocess_run.return_value = MagicMock(returncode=0, stderr="")
        mock_create_output_file.side_effect = [mock_output_file_1, mock_output_file_2]

        result = export_all_containers(
            self.input_file,
            self.output_path,
            self.log_file,
            self.disk_mount_dir,
            self.task_config,
        )

        self.assertEqual(result, [mock_output_file_1, mock_output_file_2])


if __name__ == "__main__":
    unittest.main()
