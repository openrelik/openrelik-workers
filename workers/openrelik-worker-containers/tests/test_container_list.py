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

"""Unit tests for container list."""

import hashlib
import json
import os
import unittest
import tempfile

from unittest.mock import patch, mock_open, MagicMock


from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.file_utils import OutputFile

from src.container_list import list_containers
from src.container_list import _read_json_file


class TestContainerListTask(unittest.TestCase):
    """Unit test for OpenRelik container list task."""

    def setUp(self):
        self.input_file = MagicMock()
        self.input_file.id = "disk.raw"
        self.input_file.path = "/fake/disk.raw"
        self.input_file.get.return_value = "disk.raw"

        self.output_path: str = tempfile.TemporaryDirectory().name
        self.log_file: OutputFile = create_output_file(
            self.output_path, display_name="container_list", extension="json"
        )

        os.makedirs(self.output_path, exist_ok=True)

    @patch("src.container_list.logger")
    @patch("src.container_list.os.mkdir")
    @patch("src.container_list._list_containerd_containers")
    @patch("src.container_list._list_docker_containers")
    @patch("src.container_list._read_json_file")
    @patch("src.container_list.os.path.exists")
    @patch("src.container_list.shutil.rmtree")
    def test_list_containers(
        self,
        mock_shutil_rmtree,
        mock_os_path_exists,
        mock_read_json_file,
        mock_list_docker_containers,
        mock_list_containerd_containers,
        mock_os_listdir,
        mock_logger,
    ) -> None:
        """Test listing docker containers."""
        with open(
            os.path.join("test_data", "container_list.json"), "r", encoding="utf-8"
        ) as fh:
            data = json.loads(fh.read())
        mock_read_json_file.return_value = data

        mountpoint: str = "/mnt/fake"

        result: OutputFile = list_containers(
            self.input_file, self.output_path, self.log_file, mountpoint
        )

        content: str = ""
        result_content_hash: str = ""

        with open(result.path, "r", encoding="utf-8") as fh:
            content = fh.read()
            result_content_hash: str = hashlib.md5(content.encode()).hexdigest()

        self.assertEqual(result_content_hash, "8d9f8b3851334af1b80b6676597c2359")

        # Four container info entries will be created.
        json_data = json.loads(content)
        self.assertEqual(len(json_data), 4)

    def test_read_json_file(self):
        """Tests supporting function _read_json_file."""
        json_file: str = os.path.join("test_data", "container_list.json")
        data: list[dict] = _read_json_file(json_file)

        content: str = json.dumps(data, indent=4)
        content_hash: str = hashlib.md5(content.encode()).hexdigest()

        # Expected hash is calculated by running md5sum test_data/container_list.json
        expected_hash: str = "3bc5afa979113b3f0e32cf216a2f9794"
        self.assertEqual(content_hash, expected_hash)


if __name__ == "__main__":
    unittest.main()
