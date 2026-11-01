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

"""Tests for app module."""

import importlib
import os
from unittest import mock


def test_app_debug_enabled():
    with (
        mock.patch.dict(os.environ, {"OPENRELIK_PYDEBUG": "1", "REDIS_URL": "redis://"}, clear=True),
        mock.patch("openrelik_worker_common.debug_utils.start_debugger") as mock_start_debugger,
    ):
        import src.app

        importlib.reload(src.app)
        mock_start_debugger.assert_called_once()
