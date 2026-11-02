import unittest
from unittest.mock import patch, mock_open, MagicMock

from src.analyzers import linux_analyzer, windows_analyzer

class TestAnalyzers(unittest.TestCase):
    @patch("src.analyzers.linux_analyzer.analyse_shadow_file")
    def test_linux(self, mock_analyse):
        mock_analyse.return_value = {}
        res = linux_analyzer.analyze_accts("root:x:0:0:root:/root:/bin/bash\nroot:$1$hash:1:1:1:1:1:1", "shadow")
        
    @patch("src.analyzers.linux_analyzer.bruteforce_password_hashes")
    def test_analyse_shadow_file(self, mock_brute):
        mock_brute.return_value = [("hash1", "password")]
        res = linux_analyzer.analyse_shadow_file(["hash1"], "shadow", {"hash1": "root"})
        self.assertEqual(res.summary, "Shadow file analysis of shadow found 1 weak password(s)")
            
    @patch("src.analyzers.windows_analyzer.bruteforce_password_hashes")
    def test_analyse_windows_creds(self, mock_brute):
        mock_brute.return_value = [("hash1", "password")]
        res = windows_analyzer.analyse_windows_creds(["hash1"], {"hash1": "admin"})
        self.assertEqual(res.summary, "Registry analysis found 1 weak password(s)")

    @patch("src.analyzers.windows_analyzer.subprocess.run")
    def test_execution_helper(self, mock_run):
        mock_run.return_value.returncode = 0
        res = windows_analyzer.execution_helper(["echo"])
        self.assertEqual(res, 0)

    @patch("src.analyzers.windows_analyzer.os.path.isfile")
    @patch("src.analyzers.windows_analyzer.os.remove")
    @patch("src.analyzers.windows_analyzer.subprocess.run")
    def test_extract_windows_hashes(self, mock_run, mock_remove, mock_isfile):
        mock_run.return_value.returncode = 0
        mock_isfile.return_value = True
        with patch("builtins.open", mock_open(read_data="admin:1000:aad3:hash1:::\nuser2:1001:aad3:hash1:::\nignore:1002:aad3:31d6cfe0d16ae931b73c59d7e0c089c0:::\n")):
            res = windows_analyzer._extract_windows_hashes("/tmp")
        self.assertEqual(len(res[0]), 2)
        
        # Test error path
        mock_isfile.return_value = False
        with self.assertRaises(RuntimeError):
            windows_analyzer._extract_windows_hashes("/tmp")

    @patch("src.analyzers.windows_analyzer.os.path.isfile")
    @patch("src.analyzers.windows_analyzer.os.remove")
    @patch("src.analyzers.windows_analyzer.subprocess.run")
    def test_extract_ad_hashes(self, mock_run, mock_remove, mock_isfile):
        mock_run.return_value.returncode = 0
        mock_isfile.return_value = True
        with patch("builtins.open", mock_open(read_data="admin:1000:aad3:hash1:::\nuser2:1001:aad3:hash1:::\nignore:1002:aad3:31d6cfe0d16ae931b73c59d7e0c089c0:::\n")):
            res = windows_analyzer._extract_ad_hashes("/tmp", "SYSTEM", "NTDS.dit")
        self.assertEqual(len(res[0]), 2)
        
        # Test error path
        mock_isfile.return_value = False
        with self.assertRaises(RuntimeError):
            windows_analyzer._extract_ad_hashes("/tmp", "SYSTEM", "NTDS.dit")

    @patch("src.analyzers.windows_analyzer._extract_windows_hashes")
    @patch("src.analyzers.windows_analyzer.analyse_windows_creds")
    def test_windows(self, mock_analyse, mock_extract):
        input_data = [
            {"path": "SAM", "filename": "SAM", "display_name": "SAM"},
            {"path": "SYSTEM", "filename": "SYSTEM", "display_name": "SYSTEM"},
            {"path": "SOFTWARE", "filename": "SOFTWARE", "display_name": "SOFTWARE"},
            {"path": "NTDS", "filename": "ntds.dit", "display_name": "ntds.dit"}
        ]
        mock_extract.return_value = ["hash1"], {"hash1": "admin"}
        mock_analyse.return_value = {}
        with patch("src.analyzers.windows_analyzer._extract_ad_hashes") as mock_extract_ad:
            mock_extract_ad.return_value = ["hash1"], {"hash1": "admin"}
            res = windows_analyzer.analyze_accts(input_data)

if __name__ == "__main__":
    unittest.main()
