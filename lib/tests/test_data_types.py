import unittest

from enum import Enum, StrEnum

from openrelik_worker_common import data_types
from openrelik_worker_common import task_utils


class TestDataTypes(unittest.TestCase):
    """Test the OpenRelik data types."""

    def test_datatype_str_comparision(self):
        """Test string comparison of data types."""
        self.assertEqual(data_types.DataType.DISKIMAGE_QCOW, "diskimage:qcow")

    def test_datatype_enum_comparision(self):
        """Test enum comparison of data types."""
        test_enum = data_types.DataType.DISKIMAGE_QCOW
        self.assertIsInstance(test_enum, Enum)
        self.assertIsInstance(test_enum, StrEnum)

    def test_datatype_filtering(self):
        """Test glob comparision of data types."""
        input_files = [
            {"name": "testfile.qcow", "data_type": f"container_explorer:{data_types.DataType.DISKIMAGE_QCOW}"},
            {"name": "testfile.bin", "data_type": f"hayabusa:{data_types.DataType.BINARY}"},
        ]

        filter_dict = {"data_types": ["*"]}
        compatible = task_utils.filter_compatible_files(input_files, filter_dict)
        self.assertEqual(len(compatible), 2)

        filter_dict = {"data_types": ["container_explorer:*"]}
        compatible = task_utils.filter_compatible_files(input_files, filter_dict)
        self.assertEqual(len(compatible), 1)

        filter_dict = {"data_types": ["*:diskimage:*"]}
        compatible = task_utils.filter_compatible_files(input_files, filter_dict)
        self.assertEqual(len(compatible), 1)

        filter_dict = {"data_types": ["*:binary"]}
        compatible = task_utils.filter_compatible_files(input_files, filter_dict)
        self.assertEqual(len(compatible), 1)

        filter_dict = {"data_types": [f"*:{data_types.DataType.DISKIMAGE_QCOW}"]}
        compatible = task_utils.filter_compatible_files(input_files, filter_dict)
        self.assertEqual(len(compatible), 1)


if __name__ == "__main__":
    unittest.main()
