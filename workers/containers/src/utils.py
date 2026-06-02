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

"""Utility for exporting containers."""

import logging
import os
import subprocess

from typing import Any, Optional

from openrelik_worker_common.file_utils import OutputFile

logger: logging.Logger = logging.getLogger(__name__)

CE_BINARY = "/opt/container-explorer/bin/ce"

# Container worker support inputs.
COMPATIBLE_INPUTS: dict[str, Any] = {
    "data_types": [],
    "mime_types": [],
    "filenames": ["*.img", "*.raw", "*.dd", "*.qcow3", "*.qcow2", "*.qcow"],
}


def log_entry(log_file: OutputFile, message: str) -> None:
    """Appends logs line to a log file.

    Args:
        log_file: log file.
        message: log message.
    """
    try:
        with open(log_file.path, "a", encoding="utf-8") as log_writer:
            log_writer.write(message)
            log_writer.write("\n")
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error("Failed to write to log file %s: %s", log_file.path, e)
        logger.info("Original log message: %s", message)


def _mount_containerd_container(
    container_id: str,
    container_namespace: str,
    container_root_dir: str,
    container_mount_dir: str,
) -> str | None:
    """Mounts specified containerd container and returns the container mount point.

    Args:
        container_id: ID of the container to be mounted.
        container_root_dir: Absolute path of container root.
        container_mount_dir: Path to mount container.

    Returns:
        Path where container is mounted or None.
    """
    containerd_mount_command: list[str] = [
        CE_BINARY,
        "--namespace",
        container_namespace,
        "--containerd-root",
        container_root_dir,
        "mount",
        container_id,
        container_mount_dir,
    ]
    logger.info(
        "Attempting to mount containerd container %s from %s to %s",
        container_id,
        container_root_dir,
        container_mount_dir,
    )
    logger.debug("Containerd mount command: %s", " ".join(containerd_mount_command))

    try:
        subprocess.run(
            containerd_mount_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )

        logger.info(
            "Successfully mounted containerd container %s at %s",
            container_id,
            container_mount_dir,
        )
        return container_mount_dir
    except FileNotFoundError as e:
        logger.error("Container explorer binary %s does not exist.", e.filename)
    except PermissionError:
        logger.error("Permission denied to execute container-explorer binary.")
    except subprocess.TimeoutExpired:
        logger.error(
            "Timeout expired while mounting containerd container %s from %s",
            container_id,
            container_root_dir,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            "Container explorer failed to mount containerd container %s at %s with error %s.",
            container_id,
            container_root_dir,
            e.stderr,
        )

    return None


def _mount_docker_container(
    container_id: str,
    container_namespace: str,
    container_root_dir: str,
    container_mount_dir: str,
) -> str | None:
    """Mounts specified containerd container and returns the container mount point.

    Args:
        container_id: ID of the container to be mounted.
        container_root_dir: Absolute path of container root.
        container_mount_dir: Path to mount container.

    Returns:
        Path where container is mounted or None.
    """
    docker_mount_command: list[str] = [
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
    logger.info(
        "Attempting to mount Docker container %s from %s to %s",
        container_id,
        container_root_dir,
        container_mount_dir,
    )
    logger.debug("Docker mount command: %s", " ".join(docker_mount_command))

    try:
        subprocess.run(
            docker_mount_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )

        logger.info(
            "Successfully mounted Docker container %s at %s",
            container_id,
            container_mount_dir,
        )
        return container_mount_dir
    except FileNotFoundError as e:
        logger.error("Container explorer binary %s does not exist.", e.filename)
    except PermissionError:
        logger.error("Permission denied to execute container-explorer binary.")
    except subprocess.TimeoutExpired:
        logger.error(
            "Timeout expired while mounting Docker container %s from %s",
            container_id,
            container_root_dir,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            "Container explorer failed to mount Docker container %s at %s with error %s.",
            container_id,
            container_root_dir,
            e.stderr,
        )

    return None


def _mount_container(
    container_id: str,
    container_namespace: str,
    container_root_dir: str,
    container_mount_dir: str,
) -> str | None:
    """Mounts specified container ID and returns the container mount point.

    Args:
        container_id: ID of the container to be mounted.
        container_root_dir: Absolute path of container root.
        container_mount_dir: Path to mount container.

    Returns:
        Path where container is mounted or None.
    """
    if not os.path.exists(container_root_dir):
        logger.debug(
            "Container root directory %s does not exist, skipping mount attempt.",
            container_root_dir,
        )
        return None

    # Try mounting as containerd container
    returned_container_mount_dir: str | None = _mount_containerd_container(
        container_id, container_namespace, container_root_dir, container_mount_dir
    )
    if returned_container_mount_dir:
        return returned_container_mount_dir

    # Try mounting as Docker container
    returned_container_mount_dir = _mount_docker_container(
        container_id, container_namespace, container_root_dir, container_mount_dir
    )
    if returned_container_mount_dir:
        return returned_container_mount_dir

    return None


def mount_container(
    container_id: str,
    container_namespace: str,
    disk_mount_dir: str,
    container_mount_dir: str,
    container_root_dir: Optional[str] = None,
) -> str | None:
    """Mounts specified container ID and returns the container mount point.

    Args:
        container_id: ID of the container to be mounted.
        disk_mount_dir: Mount point of the disk containing the container.
        container_mount_dir: Path to mount the container.
        container_root_dir: Absolute path of the container root directory in the disk.
            If this value is not present, default directory is used for containerd and Docker.

    Returns:
        Path where container is mounted or None.
    """
    logger.info("Attempting to mount container ID: %s", container_id)

    container_root_path = None

    # Mounting container located at custom directory.
    if container_root_dir:
        container_root_path = os.path.join(disk_mount_dir, container_root_dir)
        logger.info("Using custom container root path: %s", container_root_path)

        _container_mount_dir: str | None = _mount_container(
            container_id, container_namespace, container_root_path, container_mount_dir
        )
        if _container_mount_dir:
            return _container_mount_dir

        # If custom container_root_dir is provided, we are not going to check
        # the default locations for Docker and containerd paths.
        logger.error(
            "Failed to mount container %s from custom path %s",
            container_id,
            container_root_path,
        )
        return None

    # Attempt mounting as containerd container.
    container_root_path = os.path.join(disk_mount_dir, "var", "lib", "containerd")
    logger.info("Trying default containerd root path: %s", container_root_path)
    _container_mount_dir = _mount_container(
        container_id, container_namespace, container_root_path, container_mount_dir
    )
    if _container_mount_dir:
        return _container_mount_dir
    logger.info(
        "Mount attempt failed for default containerd path %s", container_root_path
    )

    # Attempt mounting as Docker container.
    container_root_path = os.path.join(disk_mount_dir, "var", "lib", "docker")
    logger.info("Trying default Docker root path: %s", container_root_path)
    _container_mount_dir = _mount_container(
        container_id, container_namespace, container_root_path, container_mount_dir
    )
    if _container_mount_dir:
        return _container_mount_dir
    logger.info("Mount attempt failed for default Docker path %s", container_root_path)

    logger.error("Failed to mount container %s using default paths.", container_id)
    return None


def unmount_container(
    container_id: str, container_mount_dir: str, log_file: Optional[OutputFile] = None
) -> None:
    """Safely unmounts a container mount points."""
    if not container_mount_dir or not os.path.ismount(container_mount_dir):
        logger.debug(
            "Container mountpoint %s for container %s does not exist",
            container_mount_dir,
            container_id,
        )
        return None

    logger.info("Unmounting container mountpoint %s", container_mount_dir)
    unmount_command: list[str] = ["umount", container_mount_dir]
    try:
        subprocess.run(
            unmount_command,
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )

        logger.info(
            "Successfully unmounted container mountpoint %s", container_mount_dir
        )
    except subprocess.TimeoutExpired:
        logger.error("Timeout expired while unmounting %s", container_mount_dir)
    except subprocess.CalledProcessError as e:
        logger.error(
            "Exception occurred while unmounting: %s: %s",
            container_mount_dir,
            e.stderr,
        )

    return None


def _find_directory(root_dir: str, find_dirname: str) -> list[str]:
    """Find a directory name in the specified path."""
    potential_root_dirs: list[str] = []

    for dirpath, dirnames, _ in os.walk(root_dir):
        if find_dirname in dirnames:
            potential_root_dirs.append(os.path.join(dirpath, find_dirname))
    return potential_root_dirs


def container_root_exists(mountpoint: str) -> bool:
    """Checks if mountpoint has default containerd or Docker root directory."""
    container_root_dirnames: list[str] = ["docker", "containerd"]

    for container_root_dirname in container_root_dirnames:
        container_root_paths: list[str] = _find_directory(
            mountpoint, container_root_dirname
        )

        # Containerd and Docker default root directories are /var/lib/containerd and /var/lib/docker
        # Handling edge case where /var is a dedicated Linux partition.
        for container_root_path in container_root_paths:
            if f"lib/{container_root_dirname}" in container_root_path:
                container_root_files: list[str] = os.listdir(container_root_path)
                if (
                    "containers" in container_root_files
                    or "io.containerd.content.v1.content" in container_root_files
                ):
                    logger.debug(
                        "Container root directory identified %s", container_root_path
                    )
                    return True
    return False
