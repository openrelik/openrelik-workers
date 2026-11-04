import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import src.app
import src.jenkins_task
import src.jupyter_task
import src.llm_task
import src.redis_task
import src.sshd_task
import src.tomcat_task
from src.factory import task_factory, on_task_prerun

class TestFactory(unittest.TestCase):
    def test_app_imports(self):
        self.assertIsNotNone(src.app.celery)

    def test_on_task_prerun(self):
        task = MagicMock()
        task.name = "test"
        on_task_prerun(None, "task-1", task, [], {})

    @patch("celery.app.task.Task.send_event")
    @patch("src.factory.get_input_files")
    @patch("src.factory.create_output_file")
    @patch("src.factory.create_task_result")
    @patch("src.factory.serialize_file_report")
    def test_task_factory(self, mock_serialize, mock_create_result, mock_create_out, mock_get_input, mock_send_event):
        def dummy_analysis(input_file, task_config):
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
            dummy_analysis
        )

        # Call with mocked self
        res = task(
            input_files=[{"path": "test.txt", "filename": "test.txt", "display_name": "test"}],
            output_path="/tmp",
            workflow_id="wf1"
        )
        self.assertEqual(res, "res")

if __name__ == "__main__":
    unittest.main()
