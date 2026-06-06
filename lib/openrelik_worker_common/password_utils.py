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
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from typing import List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def bruteforce_password_hashes(
    password_hashes: List[str],
    tmp_dir: str,
    password_list_file_path: str,
    password_rules_file_path: str,
    timeout: int = 300,
    extra_args: str = "",
) -> List[tuple[str, str]]:
  """Bruteforce password hashes using Hashcat or john.

  Args:
    password_hashes (list): Password hashes as strings.
    tmp_dir (str): Path to use as a temporary directory.
    password_list_file_path (str): Path to the password list file.
    password_rules_file_path (str): Path to the password rules file.
    timeout (int): Number of seconds to run for before terminating the process.
    extra_args (str): Any extra arguments to be passed to Hashcat.

  Returns:
    list: of tuples with hashes and plain text passwords.

  Raises:
    RuntimeError: if execution failed.
  """
  logger.info("Starting password hash bruteforce")
  password_hash_temp_file = tempfile.NamedTemporaryFile(
      delete=False, mode="w+", dir=tmp_dir
  )
  password_hashes_file_path = password_hash_temp_file.name
  password_hash_temp_file.write("\n".join(password_hashes))

  pot_file = os.path.join((tmp_dir or tempfile.gettempdir()), "hashcat.pot")

  # Fallback
  if not os.path.isfile(password_list_file_path):
    password_list_file_path = "/usr/share/john/password.lst"

  # Bail
  if not os.path.isfile(password_list_file_path):
    password_hash_temp_file.close()
    raise RuntimeError("No password list available")

  password_rules_temp_file = tempfile.NamedTemporaryFile(
      delete=False, mode="w+", dir=tmp_dir
  )
  # Does rules file exist? If not make a temp one
  if not os.path.isfile(password_rules_file_path):
    password_rules_file_path = password_rules_temp_file.name
    password_rules_temp_file.write("\n".join([":", "d"]))

  if "$y$" in "".join(password_hashes):
    if not shutil.which("john"):
      password_hash_temp_file.close()
      password_rules_temp_file.close()
      raise RuntimeError("Trying to execute jtr but it's not installed")
    cmd = [
        "john",
        "--format=crypt",
        f"--wordlist={password_list_file_path}",
        password_hashes_file_path,
    ]
    pot_file = os.path.expanduser("~/.john/john.pot")
  else:
    if not shutil.which("hashcat"):
      password_hash_temp_file.close()
      password_rules_temp_file.close()
      raise RuntimeError("Trying to execute hashcat but it's not installed")
    # Ignore warnings & plain word list attack (with rules)
    cmd = ["hashcat", "--force", "-a", "0"]
    if extra_args:
      cmd = cmd + extra_args.split(" ")
    cmd = cmd + [f"--potfile-path={pot_file}"]
    cmd = cmd + [password_hashes_file_path, password_list_file_path]
    cmd = cmd + ["-r", password_rules_file_path]

  logger.info(f"Using command: {cmd}")

  password_hash_temp_file.close()
  password_rules_temp_file.close()

  with open(os.devnull, "w", encoding="utf-8") as devnull:
    try:
      child = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
      timer = threading.Timer(timeout, child.terminate)
      timer.start()
      child.communicate()
      # Cancel the timer if the process is done before the timer.
      if timer.is_alive():
        timer.cancel()
    except OSError as exception:
      raise RuntimeError(f'{" ".join(cmd)} failed: {exception}') from exception

  result = []

  if os.path.isfile(pot_file):
    with open(pot_file, "r", encoding="utf-8") as fh:
      for line in fh:
        password_hash, plaintext = line.rsplit(":", 1)
        plaintext = plaintext.rstrip()
        if plaintext:
          result.append((password_hash, plaintext))
    os.remove(pot_file)

  return result
