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

import shutil
import tempfile
import unittest
from openrelik_worker_common import password_utils


class PasswordUtils(unittest.TestCase):
    @unittest.skipIf(not shutil.which("hashcat"), "hashcat not installed")
    def test_Hashcat(self):
        password = ('$6$NS6w5Q6yjrlZiw7s$5jeyNS.bsw2p4nlbbMRI5H8oZnSbbwKs0Lsw94xCouqn/y/yQpKNA4vdPSr/wdA0isyUmq3BD..ZcirwOVNPF/', 'test')
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(b'test')
            fp.seek(0)
            ret = password_utils.bruteforce_password_hashes([password[0]], '/tmp/', fp.name, "")
            self.assertEqual(ret, [password])

    @unittest.skipIf(not shutil.which("john"), "john (JTR) not installed")
    def test_John(self):
        password = ('$y$j9T$Ju9QNI0mUsapuQPOXH4Ie0$o7RT.ZY25GXZkBd2EguKLGXNeSVmIN6KWrZkWl5PoL9', 'password')
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(b'password')
            fp.seek(0)
            ret = password_utils.bruteforce_password_hashes([password[0]], '/tmp/', fp.name, "")
            self.assertEqual(ret, [password])

if __name__ == "__main__":
    unittest.main()