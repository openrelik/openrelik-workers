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

import os
import tempfile
import unittest
import shutil
import xml.etree.ElementTree as xml_tree

from src.utils import (
    check_xml_attrib,
    generate_summary_report,
    extract_non_empty_files,
)

class TestBulkExtractorTask(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_file = os.path.join(self.temp_dir, "input.txt")
        self.output_path = os.path.join(self.temp_dir, "output")
        with open(self.input_file, "w") as f:
            f.write("This is a test file.")


    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def create_sample_xml(self, tmp_artifacts_dir, missing_field=None):
        """Helper function to create a sample XML file for testing."""
        report_path = os.path.join(tmp_artifacts_dir, "report.xml")
        root = xml_tree.Element("report")
        xml_tree.SubElement(root, "creator")
        xml_tree.SubElement(root.find("creator"), "program").text = "BULK_EXTRACTOR"
        xml_tree.SubElement(root.find("creator"), "version").text = "2.1.1"

        execution_environment = xml_tree.SubElement(root.find("creator"), "execution_environment")
        xml_tree.SubElement(execution_environment, "command_line").text = "bulk_extractor -o output input.txt"
        xml_tree.SubElement(execution_environment, "start_time").text = "2023-10-27T10:00:00"
        xml_tree.SubElement(root, "elapsed_seconds").text = "10"

        feature_files = xml_tree.SubElement(root, "feature_files")
        feature_file = xml_tree.SubElement(feature_files, "feature_file")
        xml_tree.SubElement(feature_file, "name").text = "email.txt"
        xml_tree.SubElement(feature_file, "count").text = "5"

        if missing_field:
          if missing_field == "feature_files":
            root.remove(feature_files)
          else:
            for element in root.findall('.//' + missing_field):
              parent = root.find('.//' + missing_field + '/..')
              parent.remove(element)

        tree = xml_tree.ElementTree(root)
        tree.write(report_path)

        # Create dummy feature files.
        dummy_file_path = os.path.join(tmp_artifacts_dir, "email.txt")
        with open(dummy_file_path, 'w') as f:
          f.write("sample content")
        return report_path

    def test_check_xml_attrib_exists(self):
        tmp_dir = tempfile.mkdtemp()
        report_path = self.create_sample_xml(tmp_dir)
        xml_file = xml_tree.parse(report_path)
        result = check_xml_attrib(xml_file, "creator/program")
        self.assertEqual(result, "BULK_EXTRACTOR")
        shutil.rmtree(tmp_dir)

    def test_check_xml_attrib_not_exists(self):
        tmp_dir = tempfile.mkdtemp()
        report_path = self.create_sample_xml(tmp_dir)
        xml_file = xml_tree.parse(report_path)
        result = check_xml_attrib(xml_file, "nonexistent_tag")
        self.assertEqual(result, "N/A")
        shutil.rmtree(tmp_dir)

    def test_generate_summary_report_success(self):
        tmp_dir = tempfile.mkdtemp()
        self.create_sample_xml(tmp_dir)
        report = generate_summary_report(tmp_dir)
        self.assertIn("5 artifacts have been extracted.", report.summary)
        self.assertIn("Bulk Extractor Results", report.title)
        self.assertIn("Scanner Results", report.to_markdown())
        self.assertIn("email.txt", report.to_markdown())
        shutil.rmtree(tmp_dir)

    def test_generate_summary_report_no_report(self):
        tmp_dir = tempfile.mkdtemp()
        report, summary = generate_summary_report(tmp_dir)
        expected_report = "Execution successful, but the report is not available."
        self.assertEqual(report, expected_report)
        self.assertEqual(summary, expected_report)
        shutil.rmtree(tmp_dir)

    def test_generate_summary_report_missing_fields(self):
        tmp_dir = tempfile.mkdtemp()
        self.create_sample_xml(tmp_dir, "elapsed_seconds")
        report = generate_summary_report(tmp_dir)
        self.assertIn("N/A", report.to_markdown())
        shutil.rmtree(tmp_dir)

    def test_generate_summary_report_no_features(self):
        tmp_dir = tempfile.mkdtemp()
        self.create_sample_xml(tmp_dir, "feature_files")
        report = generate_summary_report(tmp_dir)
        self.assertIn("There are no findings to report.", report.to_markdown())
        shutil.rmtree(tmp_dir)

    def test_extract_non_empty_files(self):
        # Create a sample directory structure with some empty and some non-empty files
        tmp_dir = tempfile.mkdtemp()
        artifact_dir = os.path.join(tmp_dir, 'artifacts')
        os.makedirs(artifact_dir)

        with open(os.path.join(artifact_dir, "empty.txt"), "w") as f:
            pass  # Create an empty file

        with open(os.path.join(artifact_dir, "non_empty.txt"), "w") as f:
            f.write("This file is not empty.")

        with open(os.path.join(artifact_dir, "another_non_empty.txt"), "w") as f:
            f.write("Another non-empty file.")

        # Call the function
        output_path = os.path.join(tmp_dir, "output_path")
        os.makedirs(output_path, exist_ok=True)
        result = extract_non_empty_files(artifact_dir, output_path)

        # Check that only non-empty files are returned
        self.assertEqual(len(result), 2)
        self.assertTrue(any(d["display_name"] == "non_empty.txt" for d in result))
        self.assertTrue(any(d["display_name"] == "another_non_empty.txt" for d in result))

        # Check that the output files exist
        for r in result:
            print(r)
            self.assertTrue(os.path.exists(os.path.join(output_path, r["uuid"] + r["extension"])))
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    unittest.main()