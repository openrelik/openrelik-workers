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
import time
from typing import Callable, Optional

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


class _UploadProgress:
    """boto3 upload_file Callback that throttles progress updates.

    boto3 invokes this every chunk (~8 KiB by default) — far too frequent to
    forward verbatim to Celery. We coalesce into one update per
    ``min_interval_s`` seconds, with a guaranteed final update on completion.
    """

    def __init__(
        self,
        total_bytes: int,
        on_update: Callable[[int, int], None],
        min_interval_s: float = 5.0,
    ):
        self._total = total_bytes
        self._sent = 0
        self._last_emit = 0.0
        self._min_interval = min_interval_s
        self._on_update = on_update

    def __call__(self, chunk_bytes: int) -> None:
        self._sent += chunk_bytes
        now = time.monotonic()
        if self._sent >= self._total or (now - self._last_emit) >= self._min_interval:
            self._last_emit = now
            try:
                self._on_update(self._sent, self._total)
            except Exception:
                logger.exception("on_progress callback raised; ignoring")


def upload_file(
    s3_client,
    local_path: str,
    bucket: str,
    key: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Upload ``local_path`` to ``s3://bucket/key`` and return bytes uploaded.

    boto3's ``upload_file`` already handles multipart streaming for large
    files. If ``on_progress`` is provided, it is called periodically with
    ``(bytes_sent, bytes_total)``.
    """
    size = os.path.getsize(local_path)
    callback = _UploadProgress(size, on_progress) if on_progress else None
    s3_client.upload_file(local_path, bucket, key, Callback=callback)
    return size
