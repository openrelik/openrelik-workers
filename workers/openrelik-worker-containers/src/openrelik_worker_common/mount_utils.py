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

import json
import logging
import os
import pathlib
import redis
import shutil
import socket
import subprocess
import time

from uuid import uuid4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BlockDevice:
    """BlockDevice provides functionality to map a disk image file to block devices
    and mount them. The default minimum partition size that gets mounted is 100MB.
    NOTE: If running in a container the container needs:
    * to be privileged (due to mounting)
    * needs access to /dev/loop* and /dev/nbd* devices
    * sudo, fdisk, qemu-utils and ntfs-3g packages installed (debian)

    Usage:
        ```
        try:
            bd = BlockDevice('/folder/path_to_disk_image.dd', min_partition_size=1)
            bd.setup()
            mountpoints = bd.mount()
            # Do the things you need to do :)
        except:
            # Handle your errors here.
        finally:
            bd.umount()
    """

    MIN_PARTITION_SIZE_BYTES = 100 * 1024 * 1024  #: Default 100 MB
    MAX_NBD_DEVICES = 10  #: Default 10
    LOCK_TIMEOUT_SECONDS = 6 * 60 * 60  #: Default 6 hours
    MAX_MOUNTPATH_SIZE = 500  #: Default 500

    def __init__(
        self,
        image_path: str,
        min_partition_size: int = MIN_PARTITION_SIZE_BYTES,
        max_mountpath_size: int = MAX_MOUNTPATH_SIZE,
    ):
        """Initialize BlockDevice class instance.

        Args:
            image_path (str): path to the image file to map and mount.
            min_partition_size (int): minimum partition size, default MIN_PARTITION_SIZE_BYTES
            max_mountpath_size (int): maximum root mount path length, default MAX_MOUNTPATH_SIZE
        """
        self.image_path = image_path
        self.min_partition_size = min_partition_size
        self.blkdevice = None
        self.blkdeviceinfo = None
        self.partitions = []
        self.mountpoints = []
        self.mountroot = "/mnt"
        self.max_mountpath_size = max_mountpath_size
        self.supported_fstypes = ["dos", "xfs", "ext2", "ext3", "ext4", "ntfs", "vfat"]
        self.supported_qcowtypes = ["qcow3", "qcow2", "qcow"]

        self.REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"
        self.redis_client = None
        self.redis_lock = None

    def setup(self):
        """Setup BlockDevice instance

        The setup function will check if the required tools are available, setup the relevant
        block device (loop or nbd) depending on image format and scan the paritions available.
        """

        # Log minimum partitions size
        logger.info(
            f"Minimum partition size {self.min_partition_size} Bytes, partitions smaller will be ignored!"
        )

        # Check if image_path exists
        image_path = pathlib.Path(self.image_path)
        if not pathlib.Path.exists(image_path):
            raise RuntimeError(f"image_path does not exist: {self.image_path}")

        # Check if required tools are available
        self._required_tools_available()

        # Check the required kernel modules are available
        self._required_modules_loaded()

        # Setup the block device
        ext = image_path.suffix.strip(".")
        if ext.lower() in self.supported_qcowtypes:
            self.redis_client = redis.Redis.from_url(self.REDIS_URL)
            self.blkdevice = self._nbdsetup()
        else:
            self.blkdevice = self._losetup()

        # Parse block device info
        self.blkdeviceinfo = self._blkinfo()

        # Parse partition information
        self.partitions = self._parse_partitions()

    def _losetup(self) -> str:
        """Map image file to loopback device using losetup.

        Returns:
            str: block device created by losetup

        Raises:
            RuntimeError: if there was an error running losetup.
        """
        losetup_command = [
            "sudo",
            "losetup",
            "--find",
            "--partscan",
            "--show",
            "--read-only",
            self.image_path,
        ]

        process = subprocess.run(
            losetup_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            blkdevice = process.stdout.strip()
            logger.info(f"losetup: success creating {blkdevice} for {self.image_path}")
        else:
            logger.error(
                f"losetup: failed creating blockdevice for {self.image_path}: {process.stderr} {process.stdout}"
            )
            raise RuntimeError(f"Error: {process.stderr} {process.stdout}")

        return blkdevice

    def _get_hostname(self):
        """Return hostname from environment variable NODENAME or OS hostname. Can be used to
        get the hostname of the node the container is running on or the OS hostname if empty.

        Returns:
            str: hostname of node or container.
        """
        hostname = os.environ.get("NODENAME")
        if not hostname:
            hostname = socket.gethostname()

        return hostname

    def _get_free_nbd_device(self):
        """Find and lock free NBD device until unlocked or timeout.
        NOTE: if running this in a container (e.g. Docker or k8s) the NBD device assignment is
        done in kernel space. This means that the locks need to done on the kernel namespace level and
        not on the container level. To make sure this works you need to set the environment variable
        NODENAME on container startup to the name of the host the container runtime engine is running on.
        For k8s that is the Node and for Docker that is the actual host the docker engine runs on.

        Returns:
            str: NBD device name

        Raises:
            RuntimeError: if no free nbd device was found.
        """
        hostname = self._get_hostname()
        for device_number in range(self.MAX_NBD_DEVICES + 1):
            devname = f"/dev/nbd{device_number}"
            lock = self.redis_client.lock(
                name=f"{hostname}-{devname}",
                timeout=self.LOCK_TIMEOUT_SECONDS,
                blocking=False,
            )
            if lock.acquire():
                self.redis_lock = lock
                logger.info(
                    f"Redis lock succesfully set: {lock.name} for {hostname}-{devname}"
                )
                return devname

        raise RuntimeError("Error getting free NBD device: All NBD devices locked!")

    def _nbdsetup(self):
        """Map QCOW image file to NBD device using qemu-nbd and probe partitions.

        Returns:
            str: block device created by qemu-nbd

        Raises:
            RuntimeError: if there was an error running qemu-nbd or fdisk.
        """
        # Get and lock a free nbd device
        self.blkdevice = self._get_free_nbd_device()
        nbdsetup_command = [
            "sudo",
            "qemu-nbd",
            "--read-only",
            "--connect",
            self.blkdevice,
            self.image_path,
        ]

        process = subprocess.run(
            nbdsetup_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            logger.info(
                f"qemu-nbd: success creating {self.blkdevice} for {self.image_path}"
            )
        else:
            logger.error(
                f"qemu-nbd: failed creating {self.blkdevice} for {self.image_path}: {process.stderr} {process.stdout}"
            )
            raise RuntimeError(
                f"Error running qemu-nbd: {process.stderr} {process.stdout}"
            )

        # This sleep is needed for qemu-nbd to activate the nbd device
        time.sleep(0.2)

        # Probe partitions with fdisk
        fdisk_command = [
            "sudo",
            "fdisk",
            "-l",
            self.blkdevice.strip(),
        ]

        process = subprocess.run(
            fdisk_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            logger.info(
                f"fdisk: success probing {self.blkdevice} for {self.image_path}"
            )
        else:
            logger.error(
                f"fdisk: failed probing {self.blkdevice} for {self.image_path}: {process.stderr} {process.stdout}"
            )
            raise RuntimeError(
                f"Error fdisk: failed probing: {process.stderr} {process.stdout}"
            )

        return self.blkdevice

    def _required_modules_loaded(self) -> None:
        """Checks if a required kernel module is loaded.

        The following modules are checked:
        * nbd  (For mounting qcow disk images)

        Raises:
            RuntimeError: as soon as we find a module that isn't loaded.
        """

        for module in ["nbd"]:
            try:
                subprocess.check_call(
                        ["/usr/bin/grep", "-E", f"^{module}\\s", "/proc/modules"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                  raise RuntimeError(
                          f"Required kernel module {module} is not loaded. "
                          f"Load it with '/sbin/modprobe {module}' on the Host.")

    def _required_tools_available(self) -> bool:
        """Check if required cli tools are available.

        Required tools can be installed on Debian by adding apt installing the
        following packages:
        * fdisk
        * qemu-utils
        * ntfs-3g
        * sudo

        Returns:
            tuple: tuple of return bool and error message
        """
        tools = ["lsblk", "blkid", "mount", "qemu-nbd", "sudo", "fdisk", "ntfsinfo"]
        missing_tools = [tool for tool in tools if not shutil.which(tool)]

        if missing_tools:
            raise RuntimeError(
                f"Missing required tools: {' '.join(missing_tools)}. Make sure you have the fdisk, qemu-utils and ntfs-3g packages installed!"
            )

        return True

    def _blkinfo(self) -> dict:
        """Extract device and partition information using blkinfo.

        Returns:
            dict: lsblk json serialized dict

        Raises:
            RuntimeError: if there was an error running lsblk or parsing the json output.
        """
        lsblk_command = ["sudo", "lsblk", "-ba", "-J", self.blkdevice]

        process = subprocess.run(
            lsblk_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            try:
                lsblk_json_output = process.stdout.strip()
                blkdeviceinfo = json.loads(lsblk_json_output)
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing lsblk json output: {lsblk_json_output}")
                raise RuntimeError(
                    f"Error parsing lsblk json output: {lsblk_json_output}: {e}"
                )
        else:
            logger.error(
                f"Error running lsblk on {self.blkdevice}: {process.stderr} {process.stdout}"
            )
            raise RuntimeError(f"Error lsblk: {process.stderr} {process.stdout}")

        logger.info(f"Success parsing lsblk info: {blkdeviceinfo}")
        return blkdeviceinfo

    def _parse_partitions(self) -> list:
        """Parse partition information from block device details.

        Returns:
            list[str]: a list of partitions
        """
        partitions = []
        if "blockdevices" not in self.blkdeviceinfo:
            raise RuntimeError("_parse_partitions: self.blkdeviceinfo malformed")
        if len(self.blkdeviceinfo.get("blockdevices")) == 0:
            logger.warning("_parse_partitions: blkdeviceinfo.blockdevices had 0 length")
            return partitions
        bd = self.blkdeviceinfo.get("blockdevices")[0]
        if "children" not in bd:
            # No partitions on this disk.
            return partitions
        for children in bd.get("children"):
            partition = f"/dev/{children['name']}"
            if self._is_important_partition(children):
                partitions.append(partition)

        return partitions

    def _is_important_partition(self, partition: dict):
        """Decides if we will process a partition. We process the partition if:
        * > 100Mbyte in size
        * contains a filesystem type ext*, dos, vfat, xfs, ntfs

        Args:
            partition (dict): Partition details from lsblk.

        Returns:
            bool: True or False for importance of partition.
        """
        if partition["size"] < self.min_partition_size:
            logger.info(
                f"Ignoring partion {partition['name']} as size < {self.min_partition_size}"
            )
            return False
        fs_type = self._get_fstype(f"/dev/{partition['name']}")
        if fs_type == "":
            logger.warning(
                f"Ignoring partition {partition['name']} as fs type not available!"
            )
            return False

        if fs_type not in self.supported_fstypes:
            logger.warning(
                f"Ignoring partition {partition['name']} as fs type {fs_type} not supported!"
            )
            return False

        return True

    def _get_fstype(self, devname: str):
        """Analyses the file system type of a block device or partition.

        Args:
            devname (str): block device or partitions device name.

        Returns:
            str: The filesystem type.

        Raises:
          RuntimeError: If there was an error running blkid.
        """
        blkid_command = ["sudo", "blkid", "-s", "TYPE", "-o", "value", f"{devname}"]

        process = subprocess.run(
            blkid_command, capture_output=True, check=False, text=True
        )
        if process.returncode == 0:
            return process.stdout.strip()
        else:
            logger.error(
                f"Error running blkid on {devname}: {process.stderr} {process.stdout}"
            )
            raise RuntimeError(
                f"Error running blkid on {devname}: {process.stderr} {process.stdout}"
            )

    def _select_partitions_to_mount(self, partition_name: str = "") -> list:
        """Select partitions to mount.

        Args:
            partitions_name (str): Name of specific partition to mount.

        Returns:
            list: A list of partitions to mount.
        """
        to_mount = []

        if partition_name and partition_name not in self.partitions:
            logger.error(
                f"Error running mount: partition name {partition_name} not found"
            )
            raise RuntimeError(
                f"Error running mount: partition name {partition_name} not found"
            )

        if partition_name:
            # Mount the specific partition requested
            to_mount.append(partition_name)
        elif not self.partitions:
            # No partitions found, mount the whole block device
            to_mount.append(self.blkdevice)
        elif self.partitions:
            # Mount all detected partitions
            to_mount = self.partitions

        return to_mount

    def _get_mount_path(self) -> str:
        """Generates a mount path using max_mountpath_size.

        Returns:
            str: The generated mount path.

        Raises:
          RuntimeError: If the max_mountpath_size is too small.
        """
        if (
            self.max_mountpath_size <= len(self.mountroot) + 1
        ):  # as we add a "/" in between root and the uuid part
            raise RuntimeError(
                f"Error generating mount path: the max_mount_path size ({self.max_mountpath_size}) is too short, please choose a larger maximum mountpath size, minimum is self.mountroot + 1"
            )

        max_uuid_size = (
            self.max_mountpath_size - len(self.mountroot) - 1
        )  # as we add a "/" in between root and the uuid part
        uuid_path_part = uuid4().hex[:max_uuid_size]

        return f"{self.mountroot}/{uuid_path_part}"

    def mount(self, partition_name: str = ""):
        """Mounts a disk or one or more partititions on a mountpoint.

        Args:
            partitions_name (str): Name of specific partition to mount.

        Returns:
            list: A list of paths the disk/partitions have been mounted on.

        Raises:
          RuntimeError: If there was an error running mount.
        """
        to_mount = self._select_partitions_to_mount(partition_name)

        for mounttarget in to_mount:
            logger.info(f"Trying to mount {mounttarget}")
            mount_command = ["sudo", "mount"]
            fstype = self._get_fstype(mounttarget)
            if fstype == "xfs":
                mount_command.extend(["-o", "ro,norecovery"])
            elif fstype in ["ext2", "ext3", "ext4"]:
                mount_command.extend(["-o", "ro,noload"])
            else:
                mount_command.extend(["-o", "ro"])

            mount_command.append(mounttarget)

            mount_folder = self._get_mount_path()
            os.makedirs(mount_folder)

            mount_command.append(mount_folder)

            process = subprocess.run(
                mount_command, capture_output=True, check=False, text=True
            )
            if process.returncode == 0:
                logger.info(f"Mounted {mounttarget} to {mount_folder}")
                self.mountpoints.append(mount_folder)
            else:
                logger.error(
                    f"Error running mount on {mounttarget}: {process.stderr} {process.stdout}"
                )
                raise RuntimeError(
                    f"Error running mount on {mounttarget}: {process.stderr} {process.stdout}"
                )
        return self.mountpoints

    def _umount_all(self):
        """Umounts all registered mount_points.

        Returns: None

        Raises:
            RuntimeError: If there was an error running umount.
        """
        removed = []
        for mountpoint in self.mountpoints:
            umount_command = ["sudo", "umount", f"{mountpoint}"]

            process = subprocess.run(
                umount_command, capture_output=True, check=False, text=True
            )
            if process.returncode == 0:
                logger.info(f"umount {mountpoint} success")
                os.rmdir(mountpoint)
                removed.append(mountpoint)
            else:
                logger.error(
                    f"Error running umount on {mountpoint}: {process.stderr} {process.stdout}"
                )
                raise RuntimeError(
                    f"Error running umount on {mountpoint}: {process.stderr} {process.stdout}"
                )

        for mountpoint in removed:
            self.mountpoints.remove(mountpoint)

    def _detach_device(self):
        """Cleanup block devices for BlockDevice instance.

        Returns: None

        Raises:
            RuntimeError: If there was an error running losetup or qemu-nbd.
        """
        if not self.blkdevice:
            return
            
        if "nbd" in self.blkdevice:
            command = ["sudo", "qemu-nbd", "--disconnect", self.blkdevice]
        else:
            command = ["sudo", "losetup", "--detach", self.blkdevice]

        process = subprocess.run(command, capture_output=True, check=False, text=True)
        if process.returncode == 0:
            logger.info(f"Detached {self.blkdevice} succes!")
            self.blkdevice = None
        else:
            logger.error(f"Detached {self.blkdevice} failed!")
            raise RuntimeError(
                f"Error detaching block device: {process.stderr} {process.stdout}"
            )

    def umount(self):
        """Unmounts all mounted file systems and detaches the block device.

        This method first attempts to unmount all file systems that were previously
        mounted by the `mount()` method. After successfully unmounting, it detaches
        the underlying block device (loop or NBD). If a Redis lock was acquired
        for an NBD device, this lock is also released.

        Raises:
            RuntimeError: If unmounting any of the mount points fails, or if
                          detaching the block device fails.
        """
        self._umount_all()
        self._detach_device()
        if self.redis_lock:
            self.redis_lock.release()
            logger.info(f"Redis lock released: {self.redis_lock.name}")
