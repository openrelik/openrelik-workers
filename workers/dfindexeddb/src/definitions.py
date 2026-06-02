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

STDERR_FILE_DATA_TYPE = "plain/txt"

LEVELDB_RECORD_TYPES = {
    "log": [
        "blocks",
        "physical_records",
        "write_batches",
        "parsed_internal_key"
    ],
    "ldb": [
        "blocks",
        "records"
    ],
    "descriptor": [
        "blocks",
        "physical_records",
        "versionedit"
    ]
}

LEVELDB_FILE_REGEX = {
    "descriptor": r"^MANIFEST-[0-9]{6}$",
    "ldb": r"[0-9]{6}\.ldb$",
    "log": r"[0-9]{6}\.log$",
}

CHROMIUM_FILE_REGEX = {
    "ldb": r"[0-9]{6}\.ldb$",
    "log": r"[0-9]{6}\.log$",
}

SAFARI_FILE_REGEX = r"^IndexedDB.sqlite3$"
FIREFOX_FILE_REGEX = r"\.sqlite$"

OUTPUT_TYPES_EXTENSIONS = {
    "json": {
        "extension": ".json",
        "mime": "application/json"
    },
    "jsonl": {
        "extension": ".jsonl",
        "mime": "application/jsonl"
    },
    "repr": {
        "extension": ".txt",
        "mime": "text/plain"
    }
}
