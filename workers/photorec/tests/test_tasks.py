# Copyright 2026 Google LLC
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
"""Tests for the PhotoRec carving task."""

import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src import tasks


def _decode(encoded):
    return json.loads(base64.b64decode(encoded.encode()).decode())


class TestBuildCommand(unittest.TestCase):
    def test_freespace_default_and_formats(self):
        command = tasks._build_command("/in/disk.raw", "/out", ["elf", "txt"], False)
        cmd_string = command[-1]
        self.assertEqual(command[0], "photorec")
        self.assertIn("freespace", cmd_string)
        self.assertNotIn("wholespace", cmd_string)
        self.assertIn("everything,disable", cmd_string)
        self.assertIn("elf,enable", cmd_string)
        self.assertIn("txt,enable", cmd_string)
        self.assertTrue(cmd_string.endswith("search"))

    def test_wholespace(self):
        command = tasks._build_command("/in/disk.raw", "/out", ["elf"], True)
        self.assertIn("wholespace", command[-1])


class TestCarveTask(unittest.TestCase):
    def _run(self, task_config=None, carved=("f0000120.elf", "f0002100.txt")):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        image = os.path.join(tmp.name, "disk.raw")
        with open(image, "wb") as fh:
            fh.write(b"\x00" * 1024)

        def fake_popen(command, **kwargs):
            dest = command[command.index("/d") + 1]
            # PhotoRec writes to SIBLING dirs suffixed .1, not into dest.
            recup = f"{dest}.1"
            os.makedirs(recup, exist_ok=True)
            for name in carved:
                with open(os.path.join(recup, name), "wb") as fh:
                    fh.write(b"carved-bytes")
            with open(os.path.join(recup, "report.xml"), "w") as fh:
                fh.write("<report/>")

            class P:
                returncode = 0
                stderr = None
                def poll(self):
                    return 0
            return P()

        with patch.object(tasks.subprocess, "Popen", side_effect=fake_popen):
            encoded = tasks.photorec_carve.run(
                input_files=[{"path": image, "display_name": "disk.raw", "uuid": "u1"}],
                output_path=tmp.name,
                workflow_id="wf-1",
                task_config=task_config or {},
            )
        return _decode(encoded)

    def test_carved_files_registered_with_data_type(self):
        result = self._run()
        names = [f["display_name"] for f in result["output_files"]]
        self.assertIn("disk.raw.carved.f0000120.elf", names)
        self.assertIn("disk.raw.carved.f0002100.txt", names)
        self.assertTrue(all(
            f["data_type"] == "openrelik:worker:photorec:carved_file"
            for f in result["output_files"]
        ))
        self.assertEqual(result["meta"]["carved_total"], 2)
        # report.xml is metadata, not evidence.
        self.assertFalse(any("report.xml" in n for n in names))
        self.assertIn("Extension", result["task_report"]["content"])

    def test_max_files_cap(self):
        result = self._run(
            task_config={"max_files": "1"},
            carved=("f1.elf", "f2.elf", "f3.elf"),
        )
        self.assertEqual(len(result["output_files"]), 1)
        self.assertEqual(result["meta"]["skipped_over_cap"], 2)
        self.assertEqual(result["meta"]["carved_total"], 3)
        self.assertIn("over the cap", result["task_report"]["summary"])


if __name__ == "__main__":
    unittest.main()
