import unittest
from unittest.mock import patch, MagicMock
from openrelik_worker_common.debug_utils import start_debugger
import os


class TestDebugUtils(unittest.TestCase):
    @patch("debugpy.listen")
    def test_start_debugger_default_port(self, mock_listen):
        start_debugger()
        mock_listen.assert_called_once_with(("0.0.0.0", 5678))

    @patch("debugpy.listen")
    def test_start_debugger_custom_port(self, mock_listen):
        start_debugger(port=1234)
        mock_listen.assert_called_once_with(("0.0.0.0", 1234))

    @patch("debugpy.listen")
    @patch.dict("os.environ", {"OPENRELIK_PYDEBUG_PORT": "1234"})
    def test_start_debugger_env_var_port(self, mock_listen):
        start_debugger()
        mock_listen.assert_called_once_with(("0.0.0.0", 1234))

    @patch.dict("os.environ", {"OPENRELIK_PYDEBUG_PORT": "abc"})
    def test_start_debugger_env_var_port_invalid(self):
        with self.assertRaises(ValueError):
            start_debugger()


if __name__ == "__main__":
    unittest.main()
