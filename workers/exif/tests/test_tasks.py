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

"""Tests tasks."""

import json as stdjson  # Alias to avoid conflict with exiftool -json
from pathlib import Path
from unittest.mock import patch, MagicMock

import piexif
import pytest
from PIL import Image

from src.tasks import command  # The Celery task function


@pytest.fixture
def jpeg_with_exif(tmp_path: Path) -> Path:
    """
    Fixture to generate a JPEG file with embedded EXIF data.

    This test:
    1. Creates a simple image using Pillow.
    2. Defines sample EXIF data (0th, Exif, and GPS IFDs).
    3. Dumps this data into EXIF byte format using piexif.
    4. Saves the image as a JPEG, embedding the EXIF data.
    5. Verifies that the file was created.
    6. Loads the EXIF data back from the saved JPEG using piexif.
    7. Asserts that key pieces of the written EXIF data are present and correct.

    Returns:
        Path to the generated JPEG file.
    """
    # 1. Define output path for the JPEG within the temporary directory
    output_jpeg_path = tmp_path / "test_image_with_exif.jpg"

    # 2. Create a simple image using Pillow
    img = Image.new("RGB", (100, 50), color="skyblue")

    # 3. Prepare EXIF data
    # EXIF data is structured in IFD (Image File Directory) dictionaries.
    # Tag names are constants from piexif.ImageIFD, piexif.ExifIFD, etc.
    # String-like tag values must be bytes.
    zeroth_ifd = {
        piexif.ImageIFD.Make: b"TestCameraCorp",
        piexif.ImageIFD.Model: b"TestModelX1",
        piexif.ImageIFD.Software: b"PytestEXIFGenerator/1.0",
        piexif.ImageIFD.DateTime: b"2023:10:28 10:30:00",
    }
    exif_ifd = {
        piexif.ExifIFD.DateTimeOriginal: b"2023:10:28 10:29:00",
        piexif.ExifIFD.LensModel: b"TestLens 50mm f/1.8",
        piexif.ExifIFD.ISOSpeedRatings: 400,
        piexif.ExifIFD.FNumber: (18, 10),  # Represents F1.8
    }
    gps_ifd = {
        piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        # Latitude: 34 deg 5 min 30.12 sec North
        piexif.GPSIFD.GPSLatitude: ((34, 1), (5, 1), (3012, 100)),
        piexif.GPSIFD.GPSLongitudeRef: b"W",
        # Longitude: 118 deg 10 min 15.34 sec West
        piexif.GPSIFD.GPSLongitude: ((118, 1), (10, 1), (1534, 100)),
    }

    exif_dict = {"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": gps_ifd}

    # Convert the EXIF dictionary to bytes
    try:
        exif_bytes = piexif.dump(exif_dict)
    except Exception as e:
        pytest.fail(f"Failed to dump EXIF data to bytes: {e}")

    # 4. Save the image with EXIF data
    try:
        img.save(str(output_jpeg_path), format="jpeg", exif=exif_bytes)
    except Exception as e:
        pytest.fail(f"Failed to save image with EXIF data: {e}")

    # 5. Verify the EXIF data was written
    assert output_jpeg_path.exists(), "JPEG file with EXIF data was not created."

    loaded_exif_dict = piexif.load(str(output_jpeg_path))

    assert loaded_exif_dict["0th"][piexif.ImageIFD.Make] == b"TestCameraCorp"
    assert loaded_exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] == 400
    assert loaded_exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] == b"N"
    assert loaded_exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] == (
        (34, 1),
        (5, 1),
        (3012, 100),
    )
    return output_jpeg_path


class TestCommandTask:
    """
    Tests for the Celery 'command' task in src.tasks.
    """

    @pytest.mark.parametrize(
        "task_config_override, expected_exiftool_args, expected_extension, expected_data_type",
        [
            (  # Test case 1: JSON output enabled
                {"json_output": True},
                ["exiftool", "-json"],
                ".json",
                "application/json",
            ),
            (  # Test case 2: JSON output disabled (default)
                {"json_output": False},
                ["exiftool"],
                ".txt",
                "text/plain",
            ),
            (  # Test case 3: task_config is None
                None,
                ["exiftool"],
                ".txt",
                "text/plain",
            ),
        ],
    )
    @patch("src.tasks.subprocess.Popen")
    @patch("src.tasks.create_output_file")
    @patch("src.tasks.get_input_files")
    @patch("src.tasks.create_task_result")
    def test_command_task_execution(
        self,  # Added self for class method
        mock_create_task_result: MagicMock,
        mock_get_input_files: MagicMock,
        mock_create_output_file: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
        jpeg_with_exif: Path,  # Use the fixture
        task_config_override: dict,
        expected_exiftool_args: list,
        expected_extension: str,
        expected_data_type: str,
    ):
        """Tests the main command task logic with various configurations."""
        # --- Setup Mocks ---
        # Mock get_input_files
        mock_input_file_dict = {
            "path": str(jpeg_with_exif),
            "display_name": jpeg_with_exif.name,
        }
        mock_get_input_files.return_value = [mock_input_file_dict]

        # Mock create_output_file
        mock_output_file_obj = MagicMock()
        # Simulate the path where the output file would be written
        output_file_name = f"output{expected_extension}"
        mock_output_file_obj.path = str(tmp_path / output_file_name)
        mock_output_file_obj.to_dict.return_value = {
            "path": str(tmp_path / output_file_name),
            "display_name": jpeg_with_exif.name,
            "data_type": expected_data_type,
        }
        mock_create_output_file.return_value = mock_output_file_obj

        # Mock subprocess.Popen
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"Simulated exiftool output", b"")
        mock_popen.return_value = mock_process

        # Mock create_task_result
        expected_final_result = "base64_encoded_task_result"
        mock_create_task_result.return_value = expected_final_result

        # --- Call the task function ---
        output_path_str = str(tmp_path / "outputs")
        workflow_id_str = "test-workflow-123"

        # The 'self' argument for bound Celery tasks can be None or a mock in direct calls
        result = command(
            pipe_result=None,
            input_files=None,  # Will be overridden by mock_get_input_files
            output_path=output_path_str,
            workflow_id=workflow_id_str,
            task_config=task_config_override,
        )

        # --- Assertions ---
        mock_get_input_files.assert_called_once_with(None, [])
        mock_create_output_file.assert_called_once_with(
            output_path_str,
            display_name=jpeg_with_exif.name,
            extension=expected_extension,
            data_type=expected_data_type,
        )
        full_expected_popen_command = expected_exiftool_args + [str(jpeg_with_exif)]
        mock_popen.assert_called_once()
        # Check the actual command passed to Popen
        assert mock_popen.call_args[0][0] == full_expected_popen_command
        # Check that stdout was a file handle (the 'w' mode file object)
        assert hasattr(mock_popen.call_args[1]["stdout"], "write")

        mock_create_task_result.assert_called_once_with(
            output_files=[mock_output_file_obj.to_dict()],
            workflow_id=workflow_id_str,
            command=" ".join(expected_exiftool_args),
            meta={},
        )
        assert result == expected_final_result

        # Test the case where Popen fails
        # We need to reset mocks that are called once per parametrized run if we call 'command' again
        # within the same test execution for the failure case.
        # A cleaner way for distinct Popen success/failure might be separate tests or more complex parametrization.
        # However, for this structure, let's ensure mocks are ready for the failure call.

        # Reset mocks that would be called again
        mock_get_input_files.reset_mock()
        mock_create_output_file.reset_mock()
        mock_popen.reset_mock()  # Popen itself will be called again
        # mock_create_task_result is not called in the failure path before the exception

        # Re-setup for the failure path (some mocks might need re-return_values if stateful)
        mock_get_input_files.return_value = [mock_input_file_dict]
        mock_create_output_file.return_value = mock_output_file_obj
        # mock_popen is already configured to return mock_process by the decorator

        mock_process.returncode = 1
        mock_process.communicate.return_value = (b"", b"Exiftool error")

        with pytest.raises(
            RuntimeError, match=f"ExifTool failed for {jpeg_with_exif}: Exiftool error"
        ):
            command(
                pipe_result=None,
                input_files=None,
                output_path=output_path_str,
                workflow_id=workflow_id_str,
                task_config=task_config_override,
            )
