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

import unittest
import unittest.mock

from openrelik_worker_common import file_utils, task_utils


class Utils(unittest.TestCase):
    """Test the utils helper functions."""

    def test_dict_to_b64_string(self):
        """Test dict_to_b64_string function."""
        result = task_utils.encode_dict_to_base64({"a": "b"})
        self.assertEqual(result, "eyJhIjogImIifQ==")

    def test_get_input_files_input(self):
        """Test get_input_files function for input_files."""
        input_file = []
        input_file.append(file_utils.create_output_file("test/test"))

        result = task_utils.get_input_files(pipe_result=None, input_files=input_file)
        self.assertEqual(result, input_file)

    def test_get_input_files_pipe(self):
        """Test get_input_files function for pipe_result."""
        pipe_input = "eyJvdXRwdXRfZmlsZXMiOiAiL3Rlc3QvdGVzdCJ9"
        result = task_utils.get_input_files(pipe_result=pipe_input, input_files=None)
        expected = "/test/test"
        self.assertEqual(result, expected)

    def test_get_input_files_multiple_pipes(self):
        """Test get_input_files aggregates output files across pipe results."""
        first = task_utils.encode_dict_to_base64({"output_files": [{"path": "/a"}]})
        second = task_utils.encode_dict_to_base64({"output_files": [{"path": "/b"}]})

        result = task_utils.get_input_files(
            pipe_result=[first, second], input_files=None
        )
        self.assertEqual(result, [{"path": "/a"}, {"path": "/b"}])

    def test_create_task_result(self):
        """Test create_task_result function."""
        output_files = ["a", "b"]
        workflow_id = "1234456789"
        command = "/bin/command"
        meta = {"key": "value"}

        expected = {
            "output_files": output_files,
            "workflow_id": workflow_id,
            "task_files": [],
            "command": command,
            "meta": meta,
            "file_reports": [],
            "task_report": None,
        }

        result = task_utils.create_task_result(
            output_files=output_files,
            workflow_id=workflow_id,
            task_files=[],
            command=command,
            meta=meta,
            file_reports=[],
            task_report=None,
        )
        self.assertEqual(result, task_utils.encode_dict_to_base64(expected))

    input_files = [
        {
            "data_type": "image/jpeg",
            "mime_type": "image/jpeg",
            "display_name": "image.jpg",
            "extension": "jpg",
        },
        {
            "data_type": "text/plain",
            "mime_type": "text/plain",
            "display_name": "document.txt",
            "extension": "txt",
        },
    ]

    def test_filter_compatible_files_data_type_match(self):
        filter_dict = {"data_types": ["image/*"]}
        expected_result = [
            {
                "data_type": "image/jpeg",
                "mime_type": "image/jpeg",
                "display_name": "image.jpg",
                "extension": "jpg",
            },
        ]
        self.assertEqual(
            task_utils.filter_compatible_files(self.input_files, filter_dict),
            expected_result,
        )

    def test_filter_compatible_files_mime_type_match(self):
        filter_dict = {"mime_types": ["text/*"]}
        expected_result = [
            {
                "data_type": "text/plain",
                "mime_type": "text/plain",
                "display_name": "document.txt",
                "extension": "txt",
            },
        ]
        self.assertEqual(
            task_utils.filter_compatible_files(self.input_files, filter_dict),
            expected_result,
        )

    def test_filter_compatible_files_filename_match(self):
        filter_dict = {"filenames": ["image.*"]}
        expected_result = [
            {
                "data_type": "image/jpeg",
                "mime_type": "image/jpeg",
                "display_name": "image.jpg",
                "extension": "jpg",
            },
        ]
        self.assertEqual(
            task_utils.filter_compatible_files(self.input_files, filter_dict),
            expected_result,
        )

    def test_filter_compatible_files_no_match(self):
        filter_dict = {"data_types": ["video/*"]}
        expected_result = []
        self.assertEqual(
            task_utils.filter_compatible_files(self.input_files, filter_dict),
            expected_result,
        )

    def test_filter_compatible_files_empty_input(self):
        input_files = []
        filter_dict = {"data_types": ["image/*"]}
        expected_result = []
        self.assertEqual(
            task_utils.filter_compatible_files(input_files, filter_dict),
            expected_result,
        )

    def test_filter_compatible_files_empty_filter(self):
        filter_dict = {}
        expected_result = []
        self.assertEqual(
            task_utils.filter_compatible_files(self.input_files, filter_dict),
            expected_result,
        )


if __name__ == "__main__":
    unittest.main()
