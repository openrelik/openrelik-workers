# Copyright 2025 Google LLC
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

import unittest
from unittest.mock import patch

from src.analyzers.linux_analyzer import (analyze_accts, analyse_shadow_file,
                                          _extract_linux_credentials)
from src.analyzers.windows_analyzer import _extract_windows_hashes

from openrelik_worker_common.reporting import Report, Priority


class LinuxAcctTest(unittest.TestCase):
    """Test the Linux Account analyzer functions."""

    TEST_SHADOW_FILE = "test_data/shadow"

    EXPECTED_CREDENTIALS = {
        '*':
        'root',
        '$6$NS6w5Q6yjrlZiw7s$5jeyNS.bsw2p4nlbbMRI5H8oZnSbbwKs0Lsw94xCouqn/y/yQpKNA4vdPSr/wdA0isyUmq3BD..ZcirwOVNPF/':
        'testuser'
    }

    def test_extract_linux_credentials(self):
        """Tests the extract_linux_credentials method."""

        shadow_file = None
        with open(self.TEST_SHADOW_FILE, 'r') as data:
            shadow_file = data.read()
        credentials = _extract_linux_credentials(shadow_file.split('\n'))

        self.assertEqual(credentials, self.EXPECTED_CREDENTIALS)


class WindowsAcctTest(unittest.TestCase):
    RAW_CREDS = [
        'testuser:1000:aad3b435b51404eeaad3b435b51404ee:9c7ae0f76b24aad74254914c2b191633:::',
        'testlocaluser:1004:aad3b435b51404eeaad3b435b51404ee:29f98734e7aa3df2454621ff3928d121:::',
        'badpassword:1005:aad3b435b51404eeaad3b435b51404ee:7a21990fcd3d759941e45c490f143d5f:::'
    ]
    EXPECTED_CREDENTIALS = {
        '29f98734e7aa3df2454621ff3928d121': 'testlocaluser',
        '7a21990fcd3d759941e45c490f143d5f': 'badpassword',
        '9c7ae0f76b24aad74254914c2b191633': 'testuser'
    }

    def test_extract_windows_hashes(self):
        creds, credentials = _extract_windows_hashes("test_data/")
        self.assertDictEqual(credentials, self.EXPECTED_CREDENTIALS)
        self.assertCountEqual(creds, self.RAW_CREDS)
