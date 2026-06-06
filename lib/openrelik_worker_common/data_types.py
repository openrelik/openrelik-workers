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
"""OpenRelik data types

This file defines the OpenRelik data types that can be used for input and
output files. The data types are defined as StrEnums which takes care of
the interoperability between code and database through string comparison 
instead of forcing Enum object comparison. This also makes sure we can
use both Enum based comparison and string based glob filtering.
"""

from enum import StrEnum


class DataType(StrEnum):
    DISKIMAGE_QCOW = "diskimage:qcow"
    DISKIMAGE_RAW = "diskimage:raw"
    BINARY = "binary"
