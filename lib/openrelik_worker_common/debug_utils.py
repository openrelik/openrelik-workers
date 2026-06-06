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


def start_debugger(port: int = 5678):
    """Setup the Python Debugger.

    This function initializes the debugpy library, allowing you to attach a debugger to your Python process.
    It checks for the environment variable `OPENRELIK_PYDEBUG` to determine if debugging should be enabled.
    If enabled, it also checks for the `OPENRELIK_PYDEBUG_PORT` environment variable to specify a custom port.

    Args:
        port: The port to listen on. Defaults to 5678.
    """
    import debugpy

    if os.getenv("OPENRELIK_PYDEBUG_PORT"):
        port = os.getenv("OPENRELIK_PYDEBUG_PORT")

    print(f"Starting debugpy on {port}\n")
    debugpy.listen(("0.0.0.0", int(port)))
