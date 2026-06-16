# -*- coding: utf-8 -*-
# Copyright 2024 Google LLC
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
"""Unit tests for OpenRelik leveldb task."""
import os
import tempfile
import unittest
from unittest import mock


with mock.patch.dict(os.environ, {"REDIS_URL": "redis://"}, clear=True):
    from src.leveldb import command


class LevelDBTest(unittest.TestCase):
    """Unit tests for the OpenRelik leveldb task."""

    def test_no_input_files(self):
        """Tests no input files."""
        pipe_result = None
        input_files = []
        workflow_id = "fake_workflow_id"
        task_config = {
            "record_type": "physical_records",
            "output_format": "JSON"
        }
        output_path = "/fake/path"

        result = command.s(
            pipe_result=pipe_result,
            input_files=input_files,
            output_path=output_path,
            workflow_id=workflow_id,
            task_config=task_config
        ).apply()

        with self.assertRaisesRegex(RuntimeError, "No supported files"):
            result.get()
        self.assertEqual(result.status, "FAILURE")

    @mock.patch("subprocess.Popen")
    @mock.patch("celery.result")
    def test_input_files(self, mock_result, mock_popen):
        """Tests a single input file."""
        pipe_result = None
        input_files = [
            {
                "id": 1,
                "uuid": "6b5856b3ddf3463aa74197dffbc88f95",
                "display_name": "000005.ldb",
                "extension": "ldb",
                "data_type": "file:generic",
                "path": "./test_data/leveldb/000005.ldb"
            }
        ]
        workflow_id = "fake_workflow_id"
        task_config = {
            "record_type": "blocks",
            "output_format": "JSON"
        }

        with tempfile.TemporaryDirectory() as output_path:
            result = command.s(
                pipe_result=pipe_result,
                input_files=input_files,
                output_path=output_path,
                workflow_id=workflow_id,
                task_config=task_config
            ).apply()

            _ = result.get()
        mock_popen.assert_called_once_with(
            [
                "dfleveldb", "ldb",
                "-s", "./test_data/leveldb/000005.ldb",
                "-t", "blocks",
                "-o", "json"
            ],
            stdout=mock.ANY, stderr=mock.ANY
        )


if __name__ == "__main__":
    unittest.main()
