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

"""Unit test for OpenRelik container utils."""

import logging
import os
import subprocess
import unittest


from unittest import mock
from unittest.mock import patch

from src.utils import _mount_containerd_container
from src.utils import _mount_docker_container
from src.utils import (
    _find_directory,
    _mount_container,
    CE_BINARY,
    container_root_exists,
    log_entry,
    mount_container,
    unmount_container,
)


class TestContainerWorkerUtils(unittest.TestCase):
    """Test container worker utils."""

    def setUp(self) -> None:
        """Set up test environment."""
        # Mock logger
        self.mock_logger = mock.MagicMock(specs=logging.Logger)
        self.patcher_logger = mock.patch("src.utils.logger", self.mock_logger)
        self.patcher_logger.start()

        # Mock log_entry
        self.mock_log_entry = mock.MagicMock()
        self.patcher_log_entry = mock.patch("src.utils.log_entry", self.mock_log_entry)
        self.patcher_log_entry.start()

        # Mock subprocess.run
        self.mock_subprocess_run = mock.MagicMock(specs=subprocess.run)
        self.patcher_subprocess = mock.patch(
            "src.utils.subprocess.run", self.mock_subprocess_run
        )
        self.patcher_subprocess.start()

        # Mock os.listdir
        self.mock_listdir = mock.MagicMock(specs=os.listdir)
        self.patcher_listdir = mock.patch("src.utils.os.listdir", self.mock_listdir)
        self.patcher_listdir.start()

        # Mock os.path.ismount
        self.mock_os_path_ismount = mock.MagicMock(specs=os.path.ismount)
        self.patcher_os_path_ismount = mock.patch(
            "src.utils.os.path.ismount", self.mock_os_path_ismount
        )
        self.patcher_os_path_ismount.start()

        # Mock os.path.exists
        self.mock_os_path_exists = mock.MagicMock(specs=os.path.exists)
        self.patcher_os_path_exists = mock.patch(
            "src.utils.os.path.exists", self.mock_os_path_exists
        )
        self.patcher_os_path_exists.start()
        self.mock_os_path_exists.return_value = True

    def tearDown(self) -> None:
        """Tear down test environment."""
        self.patcher_logger.stop()
        self.patcher_subprocess.stop()
        self.patcher_listdir.stop()
        self.patcher_os_path_ismount.stop()
        self.patcher_os_path_exists.stop()

    def test__mount_containerd_container_success(self) -> None:
        """Test successful containerd container mount."""
        container_id: str = "abc123edf"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        self.mock_subprocess_run.return_value = mock.MagicMock(
            returncode=0,
            stdout="mounted container",
            stderr="",
        )

        result: str | None = _mount_containerd_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertEqual(result, container_mount_dir)

        self.mock_subprocess_run.assert_called_once_with(
            [
                CE_BINARY,
                "--namespace",
                container_namespace,
                "--containerd-root",
                container_root_dir,
                "mount",
                container_id,
                container_mount_dir,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.info.assert_any_call(
            "Successfully mounted containerd container %s at %s",
            container_id,
            container_mount_dir,
        )

    def test__mount_containerd_container_failure(self) -> None:
        """Test failed containerd container mount."""
        container_id: str = "abc123edf"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--containerd-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        expected_stderr: str = "mount command failed internally"

        self.mock_subprocess_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=" ".join(container_command),
            stderr=expected_stderr,
        )

        result: str | None = _mount_containerd_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.error.assert_any_call(
            "Container explorer failed to mount containerd container %s at %s with error %s.",
            container_id,
            container_root_dir,
            expected_stderr,
        )

    def test__mount_containerd_container_timeout(self) -> None:
        """Test containerd container mount exceptions."""
        container_id: str = "abc123edf"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--containerd-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = subprocess.TimeoutExpired(
            cmd=" ".join(container_command), timeout=60
        )

        result: str | None = _mount_containerd_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once()
        self.mock_logger.error.assert_any_call(
            "Timeout expired while mounting containerd container %s from %s",
            container_id,
            container_root_dir,
        )

    def test__mount_containerd_container_file_not_found(self) -> None:
        """Test containerd container mount when subprocess.run raises FileNotFoundError."""
        container_id: str = "abc123edf"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--containerd-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = FileNotFoundError(
            2, "No such file or directory", CE_BINARY
        )

        result: str | None = _mount_containerd_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once_with(
            container_command, capture_output=True, check=True, text=True, timeout=60
        )
        self.mock_logger.error.assert_any_call(
            "Container explorer binary %s does not exist.", CE_BINARY
        )

    def test__mount_containerd_container_permission_error(self) -> None:
        """Test containerd container mount when subprocess.run raises PermissionError."""
        container_id: str = "abc123edf"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--containerd-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = PermissionError("Permission denied")

        result: str | None = _mount_containerd_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.error.assert_any_call(
            "Permission denied to execute container-explorer binary."
        )

    def test__mount_containerd_container_exception(self) -> None:
        """Test containerd container mount exceptions."""
        container_id: str = "abc123edf"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        expected_exception = Exception("A very generic unhandled test exception")

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--containerd-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = expected_exception

        with self.assertRaises(Exception) as context_manager:
            _mount_containerd_container(
                container_id,
                container_namespace,
                container_root_dir,
                container_mount_dir,
            )

        self.assertIs(context_manager.exception, expected_exception)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )

    def test__mount_docker_container_success(self) -> None:
        """Test successful Docker container mount."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        self.mock_subprocess_run.return_value = mock.MagicMock(
            returncode=0,
            stdout="mounted container",
            stderr="",
        )

        result: str | None = _mount_docker_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertEqual(result, container_mount_dir)

        self.mock_subprocess_run.assert_called_once_with(
            [
                CE_BINARY,
                "--namespace",
                container_namespace,
                "--docker-managed",
                "--docker-root",
                container_root_dir,
                "mount",
                container_id,
                container_mount_dir,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.info.assert_any_call(
            "Successfully mounted Docker container %s at %s",
            container_id,
            container_mount_dir,
        )

    def test__mount_docker_container_failure(self) -> None:
        """Test failed Docker container mount."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--docker-managed",
            "--docker-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        expected_stderr: str = "mount command failed internally"

        self.mock_subprocess_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=" ".join(container_command), stderr=expected_stderr
        )

        result: str | None = _mount_docker_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.error.assert_any_call(
            "Container explorer failed to mount Docker container %s at %s with error %s.",
            container_id,
            container_root_dir,
            expected_stderr,
        )

    def test__mount_docker_container_timeout(self) -> None:
        """Test failed Docker container mount."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--docker-managed",
            "--docker-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = subprocess.TimeoutExpired(
            cmd=" ".join(container_command), timeout=60
        )

        result: str | None = _mount_docker_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once()
        self.mock_logger.error.assert_any_call(
            "Timeout expired while mounting Docker container %s from %s",
            container_id,
            container_root_dir,
        )

    def test__mount_docker_container_file_not_found(self) -> None:
        """Test Docker container mount when subprocess.run raises FileNotFoundError."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--docker-managed",
            "--docker-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = FileNotFoundError(
            2, "No such file or directory", CE_BINARY
        )

        result: str | None = _mount_docker_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.error.assert_any_call(
            "Container explorer binary %s does not exist.", CE_BINARY
        )

    def test__mount_docker_container_permission_error(self) -> None:
        """Test Docker container mount when subprocess.run raises PermissionError."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--docker-managed",
            "--docker-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = PermissionError("Permission denied")

        result: str | None = _mount_docker_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.error.assert_any_call(
            "Permission denied to execute container-explorer binary."
        )

    def test__mount_docker_container_exception(self) -> None:
        """Test Docker container mount exception."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        expected_exception = Exception("A very generic unhandled test exception")

        container_command: list[str] = [
            CE_BINARY,
            "--namespace",
            container_namespace,
            "--docker-managed",
            "--docker-root",
            container_root_dir,
            "mount",
            container_id,
            container_mount_dir,
        ]

        self.mock_subprocess_run.side_effect = expected_exception

        with self.assertRaises(Exception) as context_manager:
            _mount_docker_container(
                container_id,
                container_namespace,
                container_root_dir,
                container_mount_dir,
            )
        self.assertIs(context_manager.exception, expected_exception)

        self.mock_subprocess_run.assert_called_once_with(
            container_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )

    @patch("src.utils._mount_containerd_container")
    @patch("src.utils._mount_docker_container")
    def test__mount_container_containerd_success(
        self, mock_mount_docker_container, mock_mount_containerd_container
    ) -> None:
        """Test successful container mount."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/containerd"
        container_mount_dir: str = "/mnt/aabbcc"

        mock_mount_containerd_container.return_value = container_mount_dir

        result: str | None = _mount_container(
            container_id,
            container_namespace,
            container_root_dir,
            container_mount_dir,
        )

        self.assertEqual(result, container_mount_dir)
        self.mock_os_path_exists.assert_called_once_with(container_root_dir)
        mock_mount_containerd_container.assert_called_once_with(
            container_id,
            container_namespace,
            container_root_dir,
            container_mount_dir,
        )
        mock_mount_docker_container.assert_not_called()

    @patch("src.utils._mount_containerd_container")
    @patch("src.utils._mount_docker_container")
    def test__mount_container_docker_success(
        self, mock_mount_docker_container, mock_mount_containerd_container
    ) -> None:
        """Test successful container mount."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        mock_mount_containerd_container.return_value = None
        mock_mount_docker_container.return_value = container_mount_dir

        result: str | None = _mount_container(
            container_id,
            container_namespace,
            container_root_dir,
            container_mount_dir,
        )

        self.assertEqual(result, container_mount_dir)
        self.mock_os_path_exists.assert_called_once_with(container_root_dir)
        mock_mount_docker_container.assert_called_once_with(
            container_id,
            container_namespace,
            container_root_dir,
            container_mount_dir,
        )

    @patch("src.utils._mount_containerd_container")
    @patch("src.utils._mount_docker_container")
    def test__mount_container_failure(
        self, mock_mount_docker_container, mock_mount_containerd_container
    ) -> None:
        """Test _mount_container failure."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        mock_mount_containerd_container.return_value = None
        mock_mount_docker_container.return_value = None

        result: str | None = _mount_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)
        self.mock_os_path_exists.assert_called_once_with(container_root_dir)

    @patch("src.utils._mount_containerd_container")
    @patch("src.utils._mount_docker_container")
    def test__mount_container_invalid_root_dir(
        self, mock_mount_docker_container, mock_mount_containerd_container
    ) -> None:
        """Test _mount_container failure."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        container_root_dir: str = "/mnt/abcdef/var/lib/docker"
        container_mount_dir: str = "/mnt/aabbcc"

        self.mock_os_path_exists.return_value = False

        result: str | None = _mount_container(
            container_id, container_namespace, container_root_dir, container_mount_dir
        )
        self.assertIsNone(result)

        self.mock_logger.debug.assert_any_call(
            "Container root directory %s does not exist, skipping mount attempt.",
            container_root_dir,
        )

    @patch("src.utils._mount_container")
    def test_mount_container_success(self, mock__mount_container) -> None:
        """Tests mount_container success."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        disk_mount_dir: str = "/mnt/disk_mount_dir"
        container_mount_dir: str = "/mnt/container_mount_dir"

        mock__mount_container.return_value = container_mount_dir

        result: str | None = mount_container(
            container_id, container_namespace, disk_mount_dir, container_mount_dir
        )

        self.assertEqual(result, container_mount_dir)

    @patch("src.utils._mount_container")
    def test_mount_container_failure_when_all_defaults_fail(
        self, mock_internal_mount_container
    ) -> None:
        """Tests mount_container returns None when all default mount attempts fail."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        disk_mount_dir: str = "/mnt/disk_mount_dir"
        container_mount_dir: str = "/mnt/container_mount_dir"

        # Simulate _mount_container failing for all attempts
        mock_internal_mount_container.return_value = None

        result: str | None = mount_container(
            container_id,
            container_namespace,
            disk_mount_dir,
            container_mount_dir,
            container_root_dir=None,  # Explicitly test default path logic
        )

        self.assertIsNone(result)

        # Check that _mount_container was called for default containerd and docker paths
        expected_containerd_root = os.path.join(
            disk_mount_dir, "var", "lib", "containerd"
        )
        expected_docker_root = os.path.join(disk_mount_dir, "var", "lib", "docker")

        calls = [
            mock.call(
                container_id,
                container_namespace,
                expected_containerd_root,
                container_mount_dir,
            ),
            mock.call(
                container_id,
                container_namespace,
                expected_docker_root,
                container_mount_dir,
            ),
        ]
        mock_internal_mount_container.assert_has_calls(calls, any_order=False)
        self.assertEqual(mock_internal_mount_container.call_count, 2)

        self.mock_logger.error.assert_any_call(
            "Failed to mount container %s using default paths.", container_id
        )
        self.mock_logger.info.assert_any_call(
            "Trying default containerd root path: %s", expected_containerd_root
        )
        self.mock_logger.info.assert_any_call(
            "Mount attempt failed for default containerd path %s",
            expected_containerd_root,
        )
        self.mock_logger.info.assert_any_call(
            "Trying default Docker root path: %s", expected_docker_root
        )
        self.mock_logger.info.assert_any_call(
            "Mount attempt failed for default Docker path %s", expected_docker_root
        )

    @patch("src.utils._mount_container")
    def test_mount_container_custom_container_root_dir_valid(
        self, mock_internal_mount_container
    ) -> None:
        """Test mount_container with a custom container root directory."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        disk_mount_dir: str = "/mnt/disk_mount_dir"
        container_mount_dir: str = "/mnt/container_mount_dir"
        custom_container_root_dir: str = "/data/docker"

        mock_internal_mount_container.return_value = container_mount_dir

        result: str | None = mount_container(
            container_id,
            container_namespace,
            disk_mount_dir,
            container_mount_dir,
            custom_container_root_dir,
        )

        self.assertEqual(result, container_mount_dir)

        expected_custom_path: str = os.path.join(
            disk_mount_dir, custom_container_root_dir
        )

        mock_internal_mount_container.assert_called_once_with(
            container_id,
            container_namespace,
            expected_custom_path,
            container_mount_dir,
        )

        self.mock_logger.info.assert_any_call(
            "Using custom container root path: %s", expected_custom_path
        )

    @patch("src.utils._mount_container")
    def test_mount_container_custom_container_root_dir_invalid(
        self, mock_internal_mount_container
    ) -> None:
        """Test mount_container with an invalid custom container root directory."""
        container_id: str = "abc123def"
        container_namespace: str = "default"
        disk_mount_dir: str = "/mnt/disk_mount_dir"
        container_mount_dir: str = "/mnt/container_mount_dir"
        custom_container_root_dir: str = "/data/docker"

        mock_internal_mount_container.return_value = None

        result: str | None = mount_container(
            container_id,
            container_namespace,
            disk_mount_dir,
            container_mount_dir,
            custom_container_root_dir,
        )

        self.assertIsNone(result)

        expected_custom_path: str = os.path.join(
            disk_mount_dir, custom_container_root_dir
        )

        mock_internal_mount_container.assert_called_once_with(
            container_id,
            container_namespace,
            expected_custom_path,
            container_mount_dir,
        )

        self.mock_logger.error.assert_any_call(
            "Failed to mount container %s from custom path %s",
            container_id,
            custom_container_root_dir,
        )

    @patch("src.utils.os.walk")
    def test_find_directory_found(self, mock_os_walk) -> None:
        """Test _find_directory when directory is found."""
        root_dir: str = "/test"
        find_dirname: str = "target_dir"
        mock_os_walk.return_value = [
            ("/test", ["subdir", "target_dir"], ["file1"]),
            ("/test/subdir", [], ["file2"]),
            ("/test/target_dir", [], ["file3"]),
        ]
        expected_path: str = os.path.join(root_dir, find_dirname)

        result: list[str] = _find_directory(root_dir, find_dirname)
        self.assertEqual(result, [expected_path])
        mock_os_walk.assert_called_once_with(root_dir)

    @patch("src.utils.os.walk")
    def test_find_directory_found_multiple(self, mock_os_walk) -> None:
        """Test _find_directory when directory is found multiple times."""
        root_dir: str = "/test"
        find_dirname: str = "target_dir"
        mock_os_walk.return_value = [
            ("/test", ["subdir1", "target_dir"], ["file1"]),
            ("/test/subdir1", ["target_dir"], ["file2"]),
            ("/test/target_dir", [], ["file_in_root_target"]),
            ("/test/subdir1/target_dir", [], ["file_in_subdir_target"]),
        ]
        expected_paths: list[str] = [
            os.path.join(root_dir, find_dirname),
            os.path.join(root_dir, "subdir1", find_dirname),
        ]

        result: list[str] = _find_directory(root_dir, find_dirname)
        self.assertEqual(sorted(result), sorted(expected_paths))
        mock_os_walk.assert_called_once_with(root_dir)

    @patch("src.utils.os.walk")
    def test_find_directory_not_found(self, mock_os_walk) -> None:
        """Test _find_directory when directory is not found."""
        root_dir: str = "/test"
        find_dirname: str = "non_existent_dir"
        mock_os_walk.return_value = [
            ("/test", ["subdir"], ["file1"]),
            ("/test/subdir", [], ["file2"]),
        ]

        result: list[str] = _find_directory(root_dir, find_dirname)
        self.assertEqual(result, [])
        mock_os_walk.assert_called_once_with(root_dir)

    @patch("src.utils.os.walk")
    def test_find_directory_empty_root(self, mock_os_walk) -> None:
        """Test _find_directory with an empty root directory."""
        root_dir: str = "/empty_test"
        find_dirname: str = "target_dir"
        mock_os_walk.return_value = []  # Simulates os.walk on an empty or non-existent dir

        result: list[str] = _find_directory(root_dir, find_dirname)
        self.assertEqual(result, [])
        mock_os_walk.assert_called_once_with(root_dir)

    @patch("src.utils._find_directory")
    @patch("src.utils.os.listdir")
    def test_container_root_exists_docker_valid(
        self, mock_os_listdir, mock_find_directory
    ) -> None:
        """Test container_root_exists finds a valid Docker root."""
        mountpoint: str = "/mnt/disk1"
        docker_root_path: str = os.path.join(mountpoint, "var", "lib", "docker")

        mock_find_directory.side_effect = lambda mp, dirname: (
            [docker_root_path] if dirname == "docker" else []
        )
        mock_os_listdir.return_value = ["containers", "other_stuff"]

        result: bool = container_root_exists(mountpoint)
        self.assertTrue(result)
        mock_find_directory.assert_any_call(mountpoint, "docker")
        mock_os_listdir.assert_called_once_with(docker_root_path)

    @patch("src.utils._find_directory")
    @patch("src.utils.os.listdir")
    def test_container_root_exists_containerd_valid_containers_dir(
        self, mock_os_listdir, mock_find_directory
    ) -> None:
        """Test container_root_exists finds a valid containerd root with 'containers' dir."""
        mountpoint: str = "/mnt/disk1"
        containerd_root_path: str = os.path.join(mountpoint, "var", "lib", "containerd")

        mock_find_directory.side_effect = lambda mp, dirname: (
            [containerd_root_path] if dirname == "containerd" else []
        )
        mock_os_listdir.return_value = ["containers", "other_stuff"]

        result: bool = container_root_exists(mountpoint)
        self.assertTrue(result)
        mock_find_directory.assert_any_call(mountpoint, "containerd")
        mock_os_listdir.assert_called_once_with(containerd_root_path)

    @patch("src.utils._find_directory")
    @patch("src.utils.os.listdir")
    def test_container_root_exists_containerd_valid_content_dir(
        self, mock_os_listdir, mock_find_directory
    ) -> None:
        """Test container_root_exists finds a valid containerd root with content dir."""
        mountpoint: str = "/mnt/disk1"
        containerd_root_path: str = os.path.join(mountpoint, "var", "lib", "containerd")

        mock_find_directory.side_effect = lambda mp, dirname: (
            [containerd_root_path] if dirname == "containerd" else []
        )
        mock_os_listdir.return_value = [
            "io.containerd.content.v1.content",
            "other_stuff",
        ]

        result: bool = container_root_exists(mountpoint)
        self.assertTrue(result)
        mock_find_directory.assert_any_call(mountpoint, "containerd")
        mock_os_listdir.assert_called_once_with(containerd_root_path)

    @patch("src.utils._find_directory")
    @patch("src.utils.os.listdir")
    def test_container_root_exists_docker_invalid_content(
        self, mock_os_listdir, mock_find_directory
    ) -> None:
        """Test container_root_exists with Docker root but no 'containers' dir."""
        mountpoint: str = "/mnt/disk1"
        docker_root_path: str = os.path.join(mountpoint, "var", "lib", "docker")

        mock_find_directory.side_effect = lambda mp, dirname: (
            [docker_root_path] if dirname == "docker" else []
        )
        mock_os_listdir.return_value = ["other_stuff"]

        result: bool = container_root_exists(mountpoint)
        self.assertFalse(result)
        mock_find_directory.assert_any_call(mountpoint, "docker")
        mock_os_listdir.assert_called_once_with(docker_root_path)

    @patch("src.utils._find_directory")
    @patch("src.utils.os.listdir")
    def test_container_root_exists_no_valid_markers(
        self, mock_os_listdir, mock_find_directory
    ) -> None:
        """Test container_root_exists when found dir has no valid markers."""
        mountpoint: str = "/mnt/disk1"
        containerd_root_path: str = os.path.join(mountpoint, "var", "lib", "containerd")

        mock_find_directory.side_effect = lambda mp, dirname: (
            [containerd_root_path] if dirname == "containerd" else []
        )
        mock_os_listdir.return_value = ["some_other_dir"]

        result: bool = container_root_exists(mountpoint)
        self.assertFalse(result)

    @patch("src.utils._find_directory")
    @patch("src.utils.os.listdir")
    def test_container_root_exists_none_found(
        self, mock_os_listdir, mock_find_directory
    ) -> None:
        """Test container_root_exists when _find_directory returns no paths."""
        mountpoint: str = "/mnt/disk1"
        mock_find_directory.return_value = []

        result: bool = container_root_exists(mountpoint)
        self.assertFalse(result)
        self.assertEqual(mock_find_directory.call_count, 2)  # docker and containerd
        mock_os_listdir.assert_not_called()

    def test_unmount_container_success(self) -> None:
        """Test successful unmount_container."""
        container_id: str = "test_id"
        container_mount_dir: str = "/mnt/container123"
        self.mock_os_path_ismount.return_value = True
        self.mock_subprocess_run.return_value = mock.MagicMock(returncode=0)

        unmount_container(container_id, container_mount_dir)

        self.mock_os_path_ismount.assert_called_once_with(container_mount_dir)
        self.mock_subprocess_run.assert_called_once_with(
            ["umount", container_mount_dir],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.info.assert_any_call(
            "Successfully unmounted container mountpoint %s", container_mount_dir
        )
        self.mock_log_entry.assert_not_called()

    def test_unmount_container_not_a_mountpoint(self) -> None:
        """Test unmount_container when path is not a mountpoint."""
        container_id: str = "test_id"
        container_mount_dir: str = "/mnt/not_mounted"
        self.mock_os_path_ismount.return_value = False

        unmount_container(container_id, container_mount_dir)

        self.mock_os_path_ismount.assert_called_once_with(container_mount_dir)
        self.mock_subprocess_run.assert_not_called()
        self.mock_logger.debug.assert_any_call(
            "Container mountpoint %s for container %s does not exist",
            container_mount_dir,
            container_id,
        )
        self.mock_log_entry.assert_not_called()

    def test_unmount_container_empty_mount_dir(self) -> None:
        """Test unmount_container with an empty mount directory string."""
        container_id: str = "test_id"
        unmount_container(container_id, "")
        self.mock_os_path_ismount.assert_not_called()
        self.mock_subprocess_run.assert_not_called()
        self.mock_logger.debug.assert_any_call(
            "Container mountpoint %s for container %s does not exist",
            "",
            container_id,
        )

    def test_unmount_container_none_mount_dir(self) -> None:
        """Test unmount_container with None as mount directory string."""
        container_id: str = "test_id"
        unmount_container(container_id, None)  # type: ignore
        self.mock_os_path_ismount.assert_not_called()
        self.mock_subprocess_run.assert_not_called()
        self.mock_logger.debug.assert_any_call(
            "Container mountpoint %s for container %s does not exist",
            None,
            container_id,
        )

    def test_unmount_container_failure(self) -> None:
        """Test unmount_container when umount command fails."""
        container_id: str = "test_id"
        container_mount_dir: str = "/mnt/container123"
        self.mock_os_path_ismount.return_value = True

        unmount_command: list[str] = [
            "umount",
            container_mount_dir,
        ]

        expected_stderr: str = "umount command failed internally"

        self.mock_subprocess_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=" ".join(unmount_command), stderr=expected_stderr
        )

        unmount_container(container_id, container_mount_dir)

        self.mock_subprocess_run.assert_called_once_with(
            unmount_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        self.mock_logger.error.assert_any_call(
            "Exception occurred while unmounting: %s: %s",
            container_mount_dir,
            expected_stderr,
        )

    def test_unmount_container_timeout(self) -> None:
        """Test unmount_container when umount command times out."""
        container_id: str = "test_id"
        container_mount_dir: str = "/mnt/container123"
        self.mock_os_path_ismount.return_value = True
        self.mock_subprocess_run.side_effect = subprocess.TimeoutExpired(
            cmd="umount", timeout=60
        )

        unmount_container(container_id, container_mount_dir)

        self.mock_subprocess_run.assert_called_once()
        self.mock_logger.error.assert_any_call(
            "Timeout expired while unmounting %s",
            container_mount_dir,
        )
        self.mock_log_entry.assert_not_called()

    @patch("src.utils.open", new_callable=mock.mock_open)
    def test_log_entry_success(self, mock_open_file) -> None:
        """Test successful log_entry."""
        mock_log_file_instance = mock.MagicMock()
        mock_log_file_instance.path = "/fake/output/test.log"
        message: str = "This is a test log message."

        log_entry(mock_log_file_instance, message)

        mock_open_file.assert_called_once_with(
            mock_log_file_instance.path, "a", encoding="utf-8"
        )
        # Check that write was called with the message and then with a newline
        mock_open_file().write.assert_any_call(message)
        mock_open_file().write.assert_any_call("\n")
        self.mock_logger.error.assert_not_called()

    @patch("src.utils.open", new_callable=mock.mock_open)
    def test_log_entry_file_not_found_error(self, mock_open_file) -> None:
        """Test log_entry with FileNotFoundError."""
        mock_log_file_instance = mock.MagicMock()
        mock_log_file_instance.path = "/fake/output/non_existent_dir/test.log"
        message: str = "This message won't be written due to FileNotFoundError."
        exception_instance = FileNotFoundError("File not found")

        mock_open_file.side_effect = exception_instance

        log_entry(mock_log_file_instance, message)

        mock_open_file.assert_called_once_with(
            mock_log_file_instance.path, "a", encoding="utf-8"
        )
        self.mock_logger.error.assert_called_once_with(
            "Failed to write to log file %s: %s",
            mock_log_file_instance.path,
            exception_instance,
        )
        self.mock_logger.info.assert_called_once_with(
            "Original log message: %s", message
        )

    @patch("src.utils.open", new_callable=mock.mock_open)
    def test_log_entry_permission_error(self, mock_open_file) -> None:
        """Test log_entry with PermissionError."""
        mock_log_file_instance = mock.MagicMock()
        mock_log_file_instance.path = "/fake/output/permission_denied.log"
        message: str = "This message won't be written due to PermissionError."
        exception_instance = PermissionError("Permission denied")

        mock_open_file.side_effect = exception_instance

        log_entry(mock_log_file_instance, message)

        mock_open_file.assert_called_once_with(
            mock_log_file_instance.path, "a", encoding="utf-8"
        )
        self.mock_logger.error.assert_called_once_with(
            "Failed to write to log file %s: %s",
            mock_log_file_instance.path,
            exception_instance,
        )
        self.mock_logger.info.assert_called_once_with(
            "Original log message: %s", message
        )

    @patch("src.utils.open", new_callable=mock.mock_open)
    def test_log_entry_os_error(self, mock_open_file) -> None:
        """Test log_entry with a generic OSError."""
        mock_log_file_instance = mock.MagicMock()
        mock_log_file_instance.path = "/fake/output/os_error.log"
        message: str = "This message won't be written due to OSError."
        exception_instance = OSError("Some OS error")

        mock_open_file.side_effect = exception_instance

        log_entry(mock_log_file_instance, message)

        mock_open_file.assert_called_once_with(
            mock_log_file_instance.path, "a", encoding="utf-8"
        )
        self.mock_logger.error.assert_called_once_with(
            "Failed to write to log file %s: %s",
            mock_log_file_instance.path,
            exception_instance,
        )
        self.mock_logger.info.assert_called_once_with(
            "Original log message: %s", message
        )


if __name__ == "__main__":
    unittest.main()
