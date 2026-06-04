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

import sys
import unittest
import subprocess
from fakeredis import FakeStrictRedis
from pathlib import Path
from unittest.mock import patch

from openrelik_worker_common import mount_utils


@unittest.skipIf(sys.platform != "linux", "Linux-only integration tests requiring loop/NBD devices and root/sudo privileges")
class Utils(unittest.TestCase):
    """Test the mount utils functions."""

    mountroot = "./mnt"
    ewf_image_path = "/mock/evidence.E01"
    redis_client = None

    @classmethod
    def setUpClass(self):
        # Setup fake redis client
        self.redis_client = FakeStrictRedis(server_type="redis")

    def SetUp(self):
        pass

    def assertFileExists(self, path):
        """Helper function to check if file exists."""
        if not Path(path).resolve().is_file():
            raise AssertionError(f"File does not exist: {path}")

    def assertFileDoesNotExists(self, path):
        """Helper function to check if file does not exists."""
        if Path(path).resolve().is_file():
            raise AssertionError(f"File exists: {path}")

    def test_BlkInfo(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        self.assertEqual(
            str(bd.blkdeviceinfo),
            "{'blockdevices': [{'name': 'loop0', 'maj:min': '7:0', 'rm': False, 'size': 1048576, 'ro': True, 'type': 'loop', 'mountpoints': [None]}]}",
        )

    @patch("openrelik_worker_common.mount_utils.BlockDevice._losetup")
    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    def test_BlkInfoError(self, mock_subprocess, mock_losetup):
        mock_losetup.return_value = "/dev/loop0"
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="this is not valid JSON", returncode=0
        )
        with self.assertRaises(RuntimeError):
            mount_utils.BlockDevice("./test_data/image_vfat.img").setup()

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stderr="device not found /dev/loop0", returncode=1
        )
        with self.assertRaises(RuntimeError) as e:
            mount_utils.BlockDevice("./test_data/image_vfat.img").setup()
        self.assertEqual(
            str(e.exception),
            "Error lsblk: device not found /dev/loop0 None",
        )

    def test_GetFsTypeVfat(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        self.assertEqual(bd._get_fstype(bd.blkdevice), "vfat")

    def test_GetFsTypeExt4MultiplePartitions(self):
        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.img")
        bd.setup()
        for partition in bd.partitions:
            t = bd._get_fstype(partition.strip())
            self.assertEqual(t, "ext4")

    @patch("openrelik_worker_common.mount_utils.BlockDevice._get_hostname")
    @patch("openrelik_worker_common.mount_utils.redis.Redis.from_url")
    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_GetFreeNbDevice(self, mock_partition, mock_redisclient, mock_get_hostname):
        mock_partition.return_value = True
        mock_redisclient.return_value = self.redis_client
        mock_get_hostname.return_value = "random_host_name"

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.qcow2")
        bd.setup()
        self.assertEqual(bd.blkdevice, "/dev/nbd0")
        self.assertIsNotNone(bd.redis_lock)
        self.assertEqual(bd.redis_lock.name, "random_host_name-/dev/nbd0")
        self.assertEqual(
            bd.redis_client.get("random_host_name-/dev/nbd0"), bd.redis_lock.local.token
        )

        bd2 = mount_utils.BlockDevice("./test_data/image_with_partitions.qcow2")
        bd2.setup()
        self.assertEqual(bd2.blkdevice, "/dev/nbd1")
        self.assertIsNotNone(bd2.redis_lock)
        self.assertEqual(bd2.redis_lock.name, "random_host_name-/dev/nbd1")
        self.assertEqual(
            bd2.redis_client.get("random_host_name-/dev/nbd1"),
            bd2.redis_lock.local.token,
        )

        bd.redis_lock.release()
        self.assertIsNone(bd.redis_client.get("random_host_name-/dev/nbd0"))
        bd2.redis_lock.release()
        self.assertIsNone(bd2.redis_client.get("random_host_name-/dev/nbd1"))

    @patch("openrelik_worker_common.mount_utils.BlockDevice._get_hostname")
    @patch("openrelik_worker_common.mount_utils.redis.Redis.from_url")
    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_GetFreeNbDeviceNoDevicesAvailable(
        self, mock_partition, mock_redisclient, mock_get_hostname
    ):
        mock_partition.return_value = True
        mock_redisclient.return_value = self.redis_client
        mock_get_hostname.return_value = "random_host_name"

        # lock all devices
        for device_number in range(mount_utils.BlockDevice.MAX_NBD_DEVICES + 1):
            devname = f"/dev/nbd{device_number}"
            lock = self.redis_client.lock(
                name=f"random_host_name-{devname}",
                timeout=mount_utils.BlockDevice.LOCK_TIMEOUT_SECONDS,
                blocking=False,
            )
            lock.acquire()

        with self.assertRaises(RuntimeError) as e:
            bd = mount_utils.BlockDevice("./test_data/image_with_partitions.qcow2")
            bd.setup()
        self.assertEqual(
            str(e.exception),
            "Error getting free NBD device: All NBD devices locked!",
        )

    @patch("openrelik_worker_common.mount_utils.socket.gethostname")
    def test_GetHostNameSocket(self, mock_socket):
        mock_socket.return_value = "myhostname"
        hostname = mount_utils.BlockDevice._get_hostname(None)
        self.assertEqual(hostname, "myhostname")

    @patch("openrelik_worker_common.mount_utils.os.environ.get")
    def test_GetHostNameENV(self, mock_env):
        mock_env.return_value = "mynodename"
        hostname = mount_utils.BlockDevice._get_hostname(None)
        self.assertEqual(hostname, "mynodename")

    def test_NbdSetup(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        self.assertEqual(bd.blkdevice, "/dev/loop0")

    def test_LoSetup(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        self.assertEqual(bd.blkdevice, "/dev/loop0")

    def test_LoSetupFail(self):
        with self.assertRaises(RuntimeError) as e:
            mount_utils.BlockDevice("imagedoesnotexist").setup()
        self.assertEqual(
            str(e.exception),
            "image_path does not exist: imagedoesnotexist",
        )

    def test_MountNoPartitions(self):
        bd = mount_utils.BlockDevice("./test_data/image_without_partitions.img")
        bd.setup()
        bd.mountroot = self.mountroot
        bd.mount()

        for folder in bd.mountpoints:
            self.assertFileExists(f"{folder}/testfile.txt")
        bd.umount()

    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_MountWithPartitions(self, mock_important):
        mock_important.return_value = True

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.img")
        bd.setup()
        bd.mountroot = self.mountroot
        bd.mount()

        for folder in bd.mountpoints:
            self.assertFileExists(f"{folder}/testfile.txt")

        bd.umount()

    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    @patch.object(mount_utils.BlockDevice, "_get_free_nbd_device")
    def test_MountWithQCOW2Partitions(self, mock_nbd, mock_important):
        mock_important.return_value = True
        mock_nbd.return_value = "/dev/nbd0"

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.qcow2")
        bd.setup()
        bd.mountroot = self.mountroot
        bd.mount()

        for folder in bd.mountpoints:
            self.assertFileExists(f"{folder}/testfile.txt")

        bd.umount()

    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    @patch("openrelik_worker_common.mount_utils.pathlib.Path.exists")
    @patch.object(mount_utils.BlockDevice, "_get_free_nbd_device")
    def test_MountWithQCOW2Error(self, mock_nbd, mock_pathlib, mock_subprocess):
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="not a qcow file", returncode=1
        )
        mock_pathlib.returnvalue = True
        mock_nbd.return_value = "/dev/nbd0"

        with self.assertRaises(RuntimeError) as e:
            mount_utils.BlockDevice("./test_data/nonexistent_qcow2_image.qcow2").setup()
        self.assertEqual(
            str(e.exception),
            "Error running qemu-nbd: None not a qcow file",
        )

    @patch.object(mount_utils.BlockDevice, "_parse_partitions")
    @patch.object(mount_utils.BlockDevice, "_blkinfo")
    @patch.object(mount_utils.BlockDevice, "_losetup")
    @patch.object(mount_utils.BlockDevice, "_required_modules_loaded")
    @patch.object(mount_utils.BlockDevice, "_required_tools_available")
    @patch.object(mount_utils.BlockDevice, "_ewfmount")
    @patch("openrelik_worker_common.mount_utils.pathlib.Path.exists")
    def test_EwfSetupUsesLoopDeviceWithoutNbdModuleCheck(
        self,
        mock_path_exists,
        mock_ewfmount,
        mock_tools,
        mock_modules,
        mock_losetup,
        mock_blkinfo,
        mock_parse_partitions,
    ):
        mock_path_exists.return_value = True
        mock_ewfmount.return_value = "/mnt/openrelik-ewf-test/ewf1"
        mock_losetup.return_value = "/dev/loop0"
        mock_blkinfo.return_value = {"blockdevices": []}
        mock_parse_partitions.return_value = []

        bd = mount_utils.BlockDevice(self.ewf_image_path)
        bd.setup()

        mock_ewfmount.assert_called_once_with()
        mock_modules.assert_not_called()
        mock_losetup.assert_called_once_with()
        self.assertEqual(bd.original_image_path, self.ewf_image_path)
        self.assertEqual(bd.image_path, "/mnt/openrelik-ewf-test/ewf1")
        self.assertEqual(bd.blkdevice, "/dev/loop0")

    @patch.object(mount_utils.BlockDevice, "_ewfumount")
    @patch.object(mount_utils.BlockDevice, "_losetup")
    @patch.object(mount_utils.BlockDevice, "_required_tools_available")
    @patch.object(mount_utils.BlockDevice, "_ewfmount")
    @patch("openrelik_worker_common.mount_utils.pathlib.Path.exists")
    def test_EwfSetupCleansUpEwfMountOnFailure(
        self,
        mock_path_exists,
        mock_ewfmount,
        mock_tools,
        mock_losetup,
        mock_ewfumount,
    ):
        mock_path_exists.return_value = True
        mock_losetup.side_effect = RuntimeError("losetup failed")

        bd = mount_utils.BlockDevice(self.ewf_image_path)

        def _ewfmount():
            bd.ewf_mount_path = "/mnt/openrelik-ewf-test"
            return "/mnt/openrelik-ewf-test/ewf1"

        mock_ewfmount.side_effect = _ewfmount

        with self.assertRaises(RuntimeError) as e:
            bd.setup()

        self.assertEqual(str(e.exception), "losetup failed")
        mock_ewfumount.assert_called_once_with()

    @patch.object(mount_utils.BlockDevice, "_ewfumount")
    @patch.object(mount_utils.BlockDevice, "_detach_device")
    @patch.object(mount_utils.BlockDevice, "_parse_partitions")
    @patch.object(mount_utils.BlockDevice, "_blkinfo")
    @patch.object(mount_utils.BlockDevice, "_losetup")
    @patch.object(mount_utils.BlockDevice, "_required_tools_available")
    @patch.object(mount_utils.BlockDevice, "_ewfmount")
    @patch("openrelik_worker_common.mount_utils.pathlib.Path.exists")
    def test_EwfSetupCleansUpBlockDeviceAndEwfMountOnFailure(
        self,
        mock_path_exists,
        mock_ewfmount,
        mock_tools,
        mock_losetup,
        mock_blkinfo,
        mock_parse_partitions,
        mock_detach_device,
        mock_ewfumount,
    ):
        mock_path_exists.return_value = True
        mock_losetup.return_value = "/dev/loop0"
        mock_blkinfo.side_effect = RuntimeError("lsblk failed")

        bd = mount_utils.BlockDevice(self.ewf_image_path)

        def _ewfmount():
            bd.ewf_mount_path = "/mnt/openrelik-ewf-test"
            return "/mnt/openrelik-ewf-test/ewf1"

        mock_ewfmount.side_effect = _ewfmount

        with self.assertRaises(RuntimeError) as e:
            bd.setup()

        self.assertEqual(str(e.exception), "lsblk failed")
        mock_detach_device.assert_called_once_with()
        mock_ewfumount.assert_called_once_with()
        mock_parse_partitions.assert_not_called()

    @patch.object(mount_utils.BlockDevice, "_ewfumount")
    @patch.object(mount_utils.BlockDevice, "_losetup")
    @patch.object(mount_utils.BlockDevice, "_required_tools_available")
    @patch.object(mount_utils.BlockDevice, "_ewfmount")
    @patch("openrelik_worker_common.mount_utils.pathlib.Path.exists")
    def test_EwfSetupReportsOriginalErrorWhenCleanupFails(
        self,
        mock_path_exists,
        mock_ewfmount,
        mock_tools,
        mock_losetup,
        mock_ewfumount,
    ):
        mock_path_exists.return_value = True
        mock_losetup.side_effect = RuntimeError("losetup failed")
        mock_ewfumount.side_effect = RuntimeError("cleanup failed")

        bd = mount_utils.BlockDevice(self.ewf_image_path)

        def _ewfmount():
            bd.ewf_mount_path = "/mnt/openrelik-ewf-test"
            return "/mnt/openrelik-ewf-test/ewf1"

        mock_ewfmount.side_effect = _ewfmount

        with self.assertLogs("openrelik_worker_common.mount_utils", level="ERROR"):
            with self.assertRaises(RuntimeError) as e:
                bd.setup()

        self.assertEqual(str(e.exception), "losetup failed")
        mock_ewfumount.assert_called_once_with()

    @patch("openrelik_worker_common.mount_utils.tempfile.mkdtemp")
    @patch("openrelik_worker_common.mount_utils.shutil.which")
    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    @patch("openrelik_worker_common.mount_utils.os.path.exists")
    def test_EwfMountUsesMountroot(
        self, mock_exists, mock_subprocess, mock_which, mock_mkdtemp
    ):
        mock_which.return_value = "/usr/bin/ewfmount"
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="", stderr="", returncode=0
        )
        mock_mkdtemp.return_value = "/custom-mnt/openrelik-ewf-test"
        mock_exists.return_value = True

        bd = mount_utils.BlockDevice(self.ewf_image_path)
        bd.mountroot = "/custom-mnt"
        raw_image_path = bd._ewfmount()

        mock_mkdtemp.assert_called_once_with(
            prefix="openrelik-ewf-", dir="/custom-mnt"
        )
        self.assertEqual(raw_image_path, "/custom-mnt/openrelik-ewf-test/ewf1")

    @patch("openrelik_worker_common.mount_utils.shutil.rmtree")
    @patch("openrelik_worker_common.mount_utils.time.sleep")
    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    @patch("openrelik_worker_common.mount_utils.shutil.which")
    def test_EwfUmountKeepsMountPathOnFailure(
        self, mock_which, mock_subprocess, mock_sleep, mock_rmtree
    ):
        mock_which.return_value = "/usr/bin/tool"
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="", stderr="target is busy", returncode=1
        )

        bd = mount_utils.BlockDevice(self.ewf_image_path)
        bd.ewf_mount_path = "/mnt/openrelik-ewf-test"

        with self.assertRaises(RuntimeError) as e:
            bd._ewfumount()

        self.assertIn("Error unmounting EWF image mount", str(e.exception))
        self.assertEqual(bd.ewf_mount_path, "/mnt/openrelik-ewf-test")
        mock_sleep.assert_called_once_with(0.2)
        mock_rmtree.assert_not_called()

    @patch.object(mount_utils.BlockDevice, "_parse_partitions")
    @patch.object(mount_utils.BlockDevice, "_blkinfo")
    @patch.object(mount_utils.BlockDevice, "_nbdsetup")
    @patch.object(mount_utils.BlockDevice, "_required_modules_loaded")
    @patch.object(mount_utils.BlockDevice, "_required_tools_available")
    @patch("openrelik_worker_common.mount_utils.redis.Redis.from_url")
    @patch("openrelik_worker_common.mount_utils.pathlib.Path.exists")
    def test_QcowSetupChecksNbdModule(
        self,
        mock_path_exists,
        mock_redis,
        mock_tools,
        mock_modules,
        mock_nbdsetup,
        mock_blkinfo,
        mock_parse_partitions,
    ):
        mock_path_exists.return_value = True
        mock_nbdsetup.return_value = "/dev/nbd0"
        mock_blkinfo.return_value = {"blockdevices": []}
        mock_parse_partitions.return_value = []

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.qcow2")
        bd.setup()

        mock_modules.assert_called_once_with()
        mock_nbdsetup.assert_called_once_with()
        self.assertEqual(bd.blkdevice, "/dev/nbd0")

    @patch.object(mount_utils.BlockDevice, "_ewfumount")
    @patch.object(mount_utils.BlockDevice, "_detach_device")
    @patch.object(mount_utils.BlockDevice, "_umount_all")
    def test_UmountCleansUpEwfMount(
        self, mock_umount_all, mock_detach_device, mock_ewfumount
    ):
        bd = mount_utils.BlockDevice(self.ewf_image_path)
        bd.blkdevice = "/dev/loop0"
        bd.ewf_mount_path = "/mnt/openrelik-ewf-test"

        bd.umount()

        mock_umount_all.assert_called_once_with()
        mock_detach_device.assert_called_once_with()
        mock_ewfumount.assert_called_once_with()

    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_MountWithNonExistingPartition(self, mock_important):
        mock_important.return_value = True

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.img")
        bd.setup()
        bd.mountroot = self.mountroot

        with self.assertRaises(RuntimeError) as e:
            bd.mount(partition_name="/dev/loop0p999")
        self.assertEqual(
            str(e.exception),
            "Error running mount: partition name /dev/loop0p999 not found",
        )

        bd.umount()

    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_MountWithNamedPartition(self, mock_important):
        mock_important.return_value = True

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.img")
        bd.setup()
        bd.mountroot = self.mountroot
        bd.mount(partition_name="/dev/loop0p1")

        for folder in bd.mountpoints:
            self.assertFileExists(f"{folder}/testfile.txt")

        bd.umount()

    def test_MountNothingTodo(self):
        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.img")
        bd.setup()

        bd.blkdevice = "/dev/doesnotexist"
        bd.partitions = ""

        with self.assertRaises(RuntimeError) as e:
            bd.mount()
        self.assertEqual(
            str(e.exception),
            "Error running blkid on /dev/doesnotexist:  ",
        )

    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_ParsePartitionsEmpty(self, mock_important):
        mock_important.return_value = True

        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        self.assertEqual(bd.partitions, [])

    @patch.object(mount_utils.BlockDevice, "_is_important_partition")
    def test_ParsePartitions(self, mock_important):
        mock_important.return_value = True

        bd = mount_utils.BlockDevice("./test_data/image_with_partitions.img")
        bd.setup()
        self.assertEqual(bd.partitions, ["/dev/loop0p1", "/dev/loop0p2"])

    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    def test_DetachDevice(self, mock_subprocess):
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="Device does not exist", stderr="", returncode=1
        )
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.blkdevice = "/dev/nbd0"
        with self.assertRaises(RuntimeError) as e:
            bd._detach_device()
        self.assertEqual(
            str(e.exception),
            "Error detaching block device:  Device does not exist",
        )

    def test_Umount(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        bd.mountroot = self.mountroot
        bd.mount()
        mountpoints = bd.mountpoints.copy()
        bd.umount()

        self.assertEqual(bd.mountpoints, [])
        for folder in mountpoints:
            self.assertFileDoesNotExists(folder)

    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    def test_UmountFail(self, mock_subprocess):
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="", stderr="umount failed.", returncode=1
        )
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.mountpoints = ["/mnt/folder"]

        with self.assertRaises(RuntimeError) as e:
            bd._umount_all()
        self.assertEqual(
            str(e.exception),
            "Error running umount on /mnt/folder: umount failed. ",
        )

    @patch.object(mount_utils.BlockDevice, "_get_fstype")
    def test_IsImportantPartition(self, mock_fstype):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.setup()
        partition = {"name": "loop0p1", "size": 1000000000}

        mock_fstype.return_value = "ext4"
        self.assertTrue(bd._is_important_partition(partition))

        mock_fstype.return_value = "typenotsupported"
        self.assertFalse(bd._is_important_partition(partition))

    @patch("openrelik_worker_common.mount_utils.shutil.which")
    def test_RequiredToolsAvailable_all_tools_available(self, mock_which):
        mock_which.return_value = "/path/to/tool"
        result = mount_utils.BlockDevice._required_tools_available(None)
        self.assertTrue(result)

    @patch("openrelik_worker_common.mount_utils.shutil.which")
    def test_RequiredToolsAvailable_no_tools_available(self, mock_which):
        mock_which.return_value = None
        with self.assertRaises(
            RuntimeError,
        ) as e:
            mount_utils.BlockDevice._required_tools_available(None)
        self.assertEqual(
            str(e.exception),
            "Missing required tools: lsblk blkid mount qemu-nbd sudo fdisk ntfsinfo. Make sure you have the fdisk, qemu-utils and ntfs-3g packages installed!",
        )

    @patch("openrelik_worker_common.mount_utils.shutil.which")
    def test_RequiredToolsAvailable__some_tools_available(self, mock_which):
        mock_which.side_effect = [
            "/path/to/lsblk",
            None,
            "/path/to/mount",
            None,
            None,
            "/path/to/partprobe",
            "/path/to/ntfsinfo",
        ]
        with self.assertRaises(
            RuntimeError,
        ) as e:
            mount_utils.BlockDevice._required_tools_available(None)
        self.assertEqual(
            str(e.exception),
            "Missing required tools: blkid qemu-nbd sudo. Make sure you have the fdisk, qemu-utils and ntfs-3g packages installed!",
        )

    def test_GetMountPath_default(self):
        bd = mount_utils.BlockDevice(
            "./test_data/image_vfat.img", max_mountpath_size=10
        )
        bd.mountroot = "/mnt"  # length = 4
        mountpath = bd._get_mount_path()

        self.assertEqual(len(mountpath), 10)  # path == "/mnt/{uuid}", length == 10

    def test_GetMountPath_max(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        bd.mountroot = "/mnt"  # length = 4
        mountpath = bd._get_mount_path()

        self.assertEqual(len(mountpath), 37)  # path == "/mnt/{uuid}", length == 37

    def test_GetMountPath_error(self):
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img", max_mountpath_size=5)
        bd.mountroot = "/mnt"  # length = 4

        with self.assertRaises(
            RuntimeError,
        ) as e:
            bd._get_mount_path()
        self.assertEqual(
            str(e.exception),
            "Error generating mount path: the max_mount_path size (5) is too short, please choose a larger maximum mountpath size, minimum is self.mountroot + 1",
        )

    @patch("openrelik_worker_common.mount_utils.subprocess.run")
    def test_IsImportantPartitionNone(self, mock_subprocess):
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], stdout="", stderr="", returncode=0
        )
        bd = mount_utils.BlockDevice("./test_data/image_vfat.img")
        partition = {"name": "test_partition_name", "size": 1000000000}
        with self.assertLogs(
            "openrelik_worker_common.mount_utils", level="WARNING"
        ) as cm:
            bd._is_important_partition(partition)
            self.assertEqual(
                cm.output,
                [
                    "WARNING:openrelik_worker_common.mount_utils:Ignoring partition test_partition_name as fs type not available!"
                ],
            )

    def tearDown(self):
        # Cleanup any left over loop/nbd devices
        losetup_command = ["sudo", "losetup", "-D"]
        subprocess.run(losetup_command, capture_output=False, check=False)
        for dnr in range(11):
            nbd_command = ["sudo", "qemu-nbd", "-d", f"/dev/nbd{dnr}"]
            subprocess.run(
                nbd_command,
                capture_output=False,
                check=False,
                stdout=subprocess.DEVNULL,
            )

    @classmethod
    def tearDownClass(self):
        pass


if __name__ == "__main__":
    unittest.main()
