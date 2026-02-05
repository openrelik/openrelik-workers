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
import threading


def bruteforce_password_hashes(password_hashes, tmp_dir, timeout=300, extra_args=""):
    """Bruteforce password hashes using Hashcat or john.

    Args:
      password_hashes (list): Password hashes as strings.
      tmp_dir (str): Path to use as a temporary directory
      timeout (int): Number of seconds to run for before terminating the process.
      extra_args (str): Any extra arguments to be passed to Hashcat.

    Returns:
      list: of tuples with hashes and plain text passwords.

    Raises:
      RuntimeError if execution failed.
    """
    print("Starting password hash brutefoce")
    with tempfile.NamedTemporaryFile(delete=False, mode="w+") as fh:
        password_hashes_file_path = fh.name
        fh.write("\n".join(password_hashes))

    pot_file = os.path.join((tmp_dir or tempfile.gettempdir()), "hashcat.pot")
    password_list_file_path = os.path.expanduser("/openrelik/password.lst")
    password_rules_file_path = os.path.expanduser(
        "/openrelik/openrelik-password-cracking.rules"
    )

    # Fallback
    if not os.path.isfile(password_list_file_path):
        password_list_file_path = "/usr/share/john/password.lst"

    # Bail
    if not os.path.isfile(password_list_file_path):
        raise RuntimeError("No password list available")

    # Does rules file exist? If not make a temp one
    if not os.path.isfile(password_rules_file_path):
        with tempfile.NamedTemporaryFile(delete=False, mode="w+") as rf:
            password_rules_file_path = rf.name
            rf.write("\n".join([":", "d"]))

    if "$y$" in "".join(password_hashes):
        cmd = [
            "john",
            "--format=crypt",
            f"--wordlist={password_list_file_path}",
            password_hashes_file_path,
        ]
        pot_file = os.path.expanduser("~/.john/john.pot")
    else:
        # Ignore warnings & plain word list attack (with rules)
        cmd = ["hashcat", "--force", "-a", "0"]
        if extra_args:
            cmd = cmd + extra_args.split(" ")
        cmd = cmd + [f"--potfile-path={pot_file}"]
        cmd = cmd + [password_hashes_file_path, password_list_file_path]
        cmd = cmd + ["-r", password_rules_file_path]

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
