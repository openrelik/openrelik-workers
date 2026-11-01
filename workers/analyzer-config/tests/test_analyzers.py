import unittest
from unittest.mock import patch, mock_open, MagicMock

from src.analyzers import (
    jenkins_analyzer,
    jupyter_analyzer,
    llm_analyzer,
    redis_analyzer,
    sshd_analyzer,
    tomcat_analyzer
)

class TestAnalyzers(unittest.TestCase):
    @patch("src.analyzers.jenkins_analyzer.bruteforce_password_hashes")
    def test_jenkins(self, mock_brute):
        mock_brute.return_value = []
        input_file = {"path": "/fake.xml", "filename": "config.xml"}
        with patch("builtins.open", mock_open(read_data="<xml></xml>")):
            res = jenkins_analyzer.analyze_config(input_file, {})

    def test_jupyter(self):
        input_file = {"path": "/fake.py", "filename": "jupyter_notebook_config.py"}
        jupyter_conf = '''
c.NotebookApp.allow_origin = '*'
c.NotebookApp.allow_root = True
c.NotebookApp.password = required False
c.NotebookApp.password = ''
c.NotebookApp.allow_remote_access = True
'''
        with patch("builtins.open", mock_open(read_data=jupyter_conf)):
            res = jupyter_analyzer.analyze_config(input_file, {})

    def test_redis(self):
        input_file = {"path": "/fake.conf", "filename": "redis.conf"}
        with patch("builtins.open", mock_open(read_data="requirepass foobar")):
            res = redis_analyzer.analyze_config(input_file, {})

    def test_sshd(self):
        input_file = {"path": "/fake.conf", "filename": "sshd_config"}
        with patch("builtins.open", mock_open(read_data="PermitRootLogin yes")):
            res = sshd_analyzer.analyze_config(input_file, {})

    def test_tomcat(self):
        input_file = {"path": "/fake.xml", "filename": "server.xml"}
        with patch("builtins.open", mock_open(read_data="<Server></Server>")):
            res = tomcat_analyzer.analyze_config(input_file, {})
            
    @patch("src.analyzers.llm_analyzer.manager.LLMManager")
    def test_llm(self, mock_llm_manager):
        input_file = {"path": "/fake.txt", "filename": "test.txt", "data_type": "worker:openrelik:foo"}
        
        for p in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "OTHER"]:
            mock_provider_cls = MagicMock()
            mock_provider_inst = MagicMock()
            mock_provider_inst.generate_file_analysis.return_value = "AI result"
            mock_provider_inst.chat.side_effect = ["AI summary", p]
            mock_provider_cls.return_value = mock_provider_inst
            
            mock_mgr_inst = MagicMock()
            mock_mgr_inst.get_provider.return_value = mock_provider_cls
            mock_llm_manager.return_value = mock_mgr_inst
            
            with patch("builtins.open", mock_open(read_data="some log content")):
                res = llm_analyzer.analyze_text_content(input_file, {})

if __name__ == "__main__":
    unittest.main()
