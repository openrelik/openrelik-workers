# Copyright 2026 Google LLC
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

import gzip
import logging
import os
import shutil
import tempfile

logger = logging.getLogger(__name__)

_COPY_CHUNK = 1024 * 1024

# Forensic payloads are often already-compressed (images, video, encrypted
# volumes) where higher levels burn CPU for negligible ratio gains. Level 1
# keeps export throughput high.
_GZIP_LEVEL = 1


def compress_gzip(src_path: str) -> str:
    """Gzip ``src_path`` to a new temp file and return the temp path.

    The caller owns the returned path and must delete it.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".gz", prefix="openrelik-s3-")
    os.close(fd)
    try:
        with open(src_path, "rb") as src, gzip.open(
            tmp_path, "wb", compresslevel=_GZIP_LEVEL
        ) as dst:
            shutil.copyfileobj(src, dst, length=_COPY_CHUNK)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            logger.exception("Failed to remove temp file %s after gzip error", tmp_path)
        raise
    return tmp_path


def upload_file(s3_client, local_path: str, bucket: str, key: str) -> int:
    """Upload ``local_path`` to ``s3://bucket/key`` and return bytes uploaded.

    boto3's ``upload_file`` handles multipart streaming for large files
    transparently.
    """
    size = os.path.getsize(local_path)
    s3_client.upload_file(local_path, bucket, key)
    return size
