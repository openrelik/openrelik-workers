import unittest
from unittest.mock import patch, MagicMock
from openrelik_worker_common.archive_utils import extract_archive
import os
import shutil
import subprocess
from uuid import uuid4


class TestArchiveUtils(unittest.TestCase):
    output_folder = "/tmp"
    log_file = "/tmp/log.txt"
    file_filter = ["*.txt", "*.evtx"]

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tgz(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file, self.output_folder, self.log_file, self.file_filter
        )
        self.assertIn("tar -vxzf", result[0])
        self.assertIn("*.txt", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tgz_no_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(input_file, self.output_folder, self.log_file)
        self.assertIn("tar -vxzf", result[0])
        self.assertNotIn("--wildcards", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file, self.output_folder, self.log_file, self.file_filter
        )
        self.assertIn("7z x", result[0])
        self.assertIn("*.txt", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tar_includes_password(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.tar.gz", "display_name": "archive.tar.gz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file, self.output_folder, self.log_file, self.file_filter, "Openrelik123!"
        )
        self.assertIn("tar -vxzf", result[0])
        self.assertNotIn("-pOpenrelik123!", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_includes_password(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file, self.output_folder, self.log_file, self.file_filter, "Openrelik123!"
        )
        self.assertIn("7z x", result[0])
        self.assertIn("*.txt", result[0])
        self.assertIn("-pOpenrelik123!", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_no_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(input_file, self.output_folder, self.log_file)
        self.assertIn("7z x", result[0])
        self.assertNotIn("-r", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    def test_extract_archive_error(self, mock_check_output, mock_subprocess_call):
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_subprocess_call.return_value = 1

        with self.assertRaises(RuntimeError):
            extract_archive(
                input_file, self.output_folder, self.log_file, self.file_filter
            )

    @patch("subprocess.check_output")
    def test_extract_archive_7z_not_found(self, mock_check_output):
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""

        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                extract_archive(
                    input_file, self.output_folder, self.log_file, self.file_filter
                )

    @patch("os.makedirs")
    @patch("shutil.which")
    def test_extract_archive_mkdir_error(self, mock_which, mock_makedirs):
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_makedirs.side_effect = OSError("Mocked error")
        mock_which.return_value = True

        with self.assertRaises(OSError):
            extract_archive(
                input_file, self.output_folder, self.log_file, self.file_filter
            )

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_ignore_prompts(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            self.file_filter,
            ignore_prompts=True,
        )
        self.assertIn("7z x", result[0])
        self.assertIn(" -y", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_no_ignore_prompts(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            self.file_filter,
            ignore_prompts=False,
        )
        self.assertIn("7z x", result[0])
        self.assertNotIn(" -y", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tgz_ignore_prompts_ignored(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            self.file_filter,
            ignore_prompts=True,
        )
        self.assertIn("tar -vxzf", result[0])
        self.assertNotIn(" -y", result[0])
        self.assertIn(self.output_folder, result[1])

    def test_malformed_input_file(self):
        input_file = {}

        with self.assertRaises(RuntimeError):
            extract_archive(
                input_file, self.output_folder, self.log_file, self.file_filter
            )

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tgz_exclusion_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        """Test that file_exclusion_filter applies --exclude flags for tar."""
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            file_exclusion_filter=["*.log", "tmp/*"],
        )
        self.assertIn("tar -vxzf", result[0])
        self.assertIn("--exclude=*.log", result[0])
        self.assertIn("--exclude=tmp/*", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tgz_no_exclusion_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        """Test that no --exclude flags are added when file_exclusion_filter is empty."""
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(input_file, self.output_folder, self.log_file)
        self.assertIn("tar -vxzf", result[0])
        self.assertNotIn("--exclude=", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_exclusion_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        """Test that file_exclusion_filter applies -xr! flags for 7z."""
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            file_exclusion_filter=["*.log", "secret/*"],
        )
        self.assertIn("7z x", result[0])
        self.assertIn("-xr!*.log", result[0])
        self.assertIn("-xr!secret/*", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_no_exclusion_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        """Test that no -xr! flags are added when file_exclusion_filter is empty."""
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(input_file, self.output_folder, self.log_file)
        self.assertIn("7z x", result[0])
        self.assertNotIn("-xr!", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_tgz_filter_and_exclusion_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        """Test that file_filter and file_exclusion_filter work together for tar."""
        input_file = {"path": "/path/to/archive.tgz", "display_name": "archive.tgz"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            file_filter=["*.evtx"],
            file_exclusion_filter=["*.log"],
        )
        self.assertIn("tar -vxzf", result[0])
        self.assertIn("*.evtx", result[0])
        self.assertIn("--exclude=*.log", result[0])
        self.assertIn(self.output_folder, result[1])

    @patch("subprocess.call")
    @patch("subprocess.check_output")
    @patch("shutil.which")
    def test_extract_archive_zip_filter_and_exclusion_filter(
        self, mock_which, mock_check_output, mock_subprocess_call
    ):
        """Test that file_filter and file_exclusion_filter work together for 7z."""
        input_file = {"path": "/path/to/archive.zip", "display_name": "archive.zip"}
        mock_check_output.return_value = b""
        mock_which.return_value = True
        mock_subprocess_call.return_value = 0

        result = extract_archive(
            input_file,
            self.output_folder,
            self.log_file,
            file_filter=["*.evtx"],
            file_exclusion_filter=["*.log"],
        )
        self.assertIn("7z x", result[0])
        self.assertIn("*.evtx", result[0])
        self.assertIn("-xr!*.log", result[0])
        self.assertIn(self.output_folder, result[1])


if __name__ == "__main__":
    unittest.main()
