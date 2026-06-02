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
import subprocess
import tempfile
from pathlib import Path, PurePath
from typing import Optional
from uuid import uuid4


class OutputFile:
    """Represents an output file.

    Attributes:
        uuid: Unique identifier for the file.
        display_name: Display name for the file.
        extension: Extension of the file.
        data_type: Data type of the file.
        path: The full path to the file.
        original_path: The full original path to the file.
        source_file_id: The OutputFile this file belongs to.
    """

    def __init__(
        self,
        uuid: str,
        output_path: str,
        display_name: str,
        extension: Optional[str] = None,
        data_type: Optional[str] = None,
        original_path: Optional[str] = None,
        source_file_id: Optional[int] = None,
    ):
        """Initialize an OutputFile object.

        Args:
            uuid: Unique identifier (uuid4) for the file.
            output_path: The path to the output directory.
            display_name: The name of the output file.
            extension: File extension (optional).
            data_type: The data type of the output file (optional).
            orignal_path: The orignal path of the file (optional).
            source_file_id: The OutputFile this file belongs to (optional).
        """
        self.uuid = uuid
        self.display_name = display_name
        self.extension = extension
        self.data_type = data_type
        self.path = output_path
        self.original_path = original_path
        self.source_file_id = source_file_id

    def to_dict(self) -> dict:
        """
        Return a dictionary representation of the OutputFile object.
        This is what the mediator server gets and uses to create a File in the database.

        Returns:
            A dictionary containing the attributes of the OutputFile object.
        """
        return {
            "uuid": self.uuid,
            "display_name": self.display_name,
            "extension": self.extension,
            "data_type": self.data_type,
            "path": self.path,
            "original_path": self.original_path,
            "source_file_id": self.source_file_id,
        }


def create_output_file(
    output_base_path: str,
    display_name: Optional[str] = None,
    extension: Optional[str] = None,
    data_type: Optional[str] = None,
    original_path: Optional[str] = None,
    source_file_id: Optional[OutputFile] = None,
) -> OutputFile:
    """Creates and returns an OutputFile object.

    Args:
        output_base_path: The path to the output directory.
        display_name: The name of the output file (optional).
        extension: File extension (optional).
        data_type: The data type of the output file (optional).
        original_path: The orignal path of the file (optional).
        source_file_id: The OutputFile this file belongs to (optional).

    Returns:
        An OutputFile object.
    """
    # Create a new UUID for the file to use as filename on disk.
    uuid = uuid4().hex

    # If display_name is missing, set the file's UUID as display_name.
    display_name = display_name if display_name else uuid

    # Allow for an explicit extension to be set.
    if extension:
        extension = extension.lstrip(".")
        display_name = f"{display_name}.{extension}"

    # Extract extension from filename if present
    _, extracted_extension = os.path.splitext(display_name)

    # Construct the full output path.
    output_filename = f"{uuid}{extracted_extension}"
    output_path = os.path.join(output_base_path, output_filename)

    return OutputFile(
        uuid=uuid,
        output_path=output_path,
        display_name=display_name,
        extension=extracted_extension,
        data_type=data_type,
        original_path=original_path,
        source_file_id=source_file_id,
    )


def count_file_lines(file_path: str) -> int:
    """Count the number of lines in a file.

    Args:
        file_path: The path to the file.

    Returns:
        The number of lines in the file.
    """
    wc = subprocess.check_output(["wc", "-l", file_path])
    return int(wc.decode("utf-8").split()[0])


def get_relative_path(path: str) -> str:
    """Converts a full path to relative path without the root.

    Args:
        path: A full path.

    Returns:
        A relative path without the root.
    """
    path = PurePath(path)
    return str(path.relative_to(path.anchor))


def build_file_tree(
    output_path: str, files: list[OutputFile]
) -> tempfile.TemporaryDirectory | None:
    """Creates the original file tree structure from a list of OutputFiles.

    Args:
        output_path: Path to the OpenRelik output directory.
        files: A list of OutPutFile instances.

    Returns:
        The root path of the file tree as a TemporaryDirectory or None.
    """
    if not files or not all(isinstance(file, OutputFile) for file in files):
        return None

    tree_root = tempfile.TemporaryDirectory(dir=output_path)

    for file in files:
        normalized_path = os.path.normpath(file.original_path)
        original_filename = Path(normalized_path).name
        original_folder = Path(normalized_path).parent
        relative_original_folder = get_relative_path(original_folder)
        # Create complete folder structure.
        try:
            tmp_full_path = os.path.join(tree_root.name, relative_original_folder)

            # Ensure that the constructed path is within the system's temporary
            # directory, preventing attempts to write files outside of it.
            if tree_root.name not in tmp_full_path:
                raise PermissionError(
                    f"Folder {tmp_full_path} not in OpenRelik output_path: {output_path}"
                )

            os.makedirs(tmp_full_path)
        except FileExistsError:
            pass
        # Create hardlink to file.
        os.link(
            file.path,
            os.path.join(tree_root.name, relative_original_folder, original_filename),
        )

    return tree_root


def delete_file_tree(root_path: tempfile.TemporaryDirectory) -> None:
    """Delete a temporary file tree folder structure.

    Args:
        root_path: TemporaryDirectory root object of file tree structure.

    Returns: None
    Raises: TypeError
    """
    if not isinstance(root_path, tempfile.TemporaryDirectory):
        raise TypeError("Root path is not a TemporaryDirectory object!")

    root_path.cleanup()


def is_disk_image(inputfile: dict) -> bool:
    """Check if inputfile is a disk image.

    Args:
        inputfile: InputFile structure.

    Returns: bool
    Raises: RuntimeError
    """
    disk_image_extensions = [".img", ".raw", ".dd", ".qcow3", ".qcow2", ".qcow"]

    if "display_name" not in inputfile:
        raise RuntimeError("inputfile parameter malformed, no display_name found")

    input_filename = str(inputfile.get("display_name"))

    _, file_extension = os.path.splitext(input_filename)

    if file_extension.lower() in disk_image_extensions:
        return True

    return False
