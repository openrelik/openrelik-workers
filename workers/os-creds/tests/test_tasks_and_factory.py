import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import src.app
import src.linux_acct_task
import src.windows_acct_task
from src.factory import task_factory

class TestFactory(unittest.TestCase):
    def test_app_imports(self):
        self.assertIsNotNone(src.app.celery)

    @patch("builtins.open")
    @patch("celery.app.task.Task.send_event")
    @patch("src.factory.get_input_files")
    @patch("src.factory.create_output_file")
    @patch("src.factory.create_task_result")
    @patch("src.factory.serialize_file_report")
    def test_task_factory(self, mock_serialize, mock_create_result, mock_create_out, mock_get_input, mock_send_event, mock_open_built):
        def dummy_analysis(creds_file):
            class DummyReport:
                def to_markdown(self): return "md"
                def to_dict(self): return {}
            return DummyReport()

        mock_out = MagicMock()
        mock_out.path = tempfile.mktemp()
        mock_out.to_dict.return_value = {"path": mock_out.path}
        mock_create_out.return_value = mock_out
        
        mock_get_input.return_value = [{"path": "test.txt", "filename": "test.txt", "display_name": "test"}]

        mock_create_result.return_value = "res"

        task = task_factory(
            "test_task",
            "test",
            {"filenames": ["test.txt"]},
            {"display_name": "Test"},
            True,
            dummy_analysis
        )

        res = task(
            input_files=[{"path": "test.txt", "filename": "test.txt", "display_name": "test"}],
            output_path="/tmp",
            workflow_id="wf1"
        )
        self.assertEqual(res, "res")

        # Now test operate_on_each_file=False
        task2 = task_factory(
            "test_task2",
            "test",
            {"filenames": ["test.txt"]},
            {"display_name": "Test"},
            False,
            dummy_analysis
        )
        res2 = task2(
            input_files=[{"path": "test.txt", "filename": "test.txt", "display_name": "test"}],
            output_path="/tmp",
            workflow_id="wf1"
        )
        self.assertEqual(res2, "res")

if __name__ == "__main__":
    unittest.main()
