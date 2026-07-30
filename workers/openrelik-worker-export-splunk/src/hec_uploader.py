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

"""Async uploader that streams a JSONL file to the Splunk HEC endpoint."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode

import aiofiles
import aiohttp

logger = logging.getLogger(__name__)

# Tunables chosen to match the reference SplunkManager implementation.
CONCURRENCY_LIMIT = 5
EVENTS_PER_BATCH = 500
MAX_BATCH_SIZE_BYTES = 1048576  # 1 MiB
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 5

# HTTP statuses that are always permanent: bad token, forbidden token, wrong
# endpoint path. Token-level Splunk codes (1/2/3/4) surface as 401/403 so we
# don't need to enumerate them separately.
PERMANENT_AUTH_STATUS_CODES = frozenset({401, 403, 404})

# On HTTP 400, Splunk codes 5 ("no data") and 6 ("invalid data format") are
# per-event problems: the whole file shouldn't abort because of one malformed
# event. Any other 400 (code 7 "incorrect index", 10/11 channel errors, or an
# unparseable body) is treated as permanent.
# See https://docs.splunk.com/Documentation/Splunk/latest/Data/TroubleshootHTTPEventCollector
RETRYABLE_400_CODES = frozenset({5, 6})


ProgressCallback = Callable[["UploadProgress"], Awaitable[None]]


@dataclass
class UploadProgress:
    """Snapshot of upload progress, passed to the progress callback."""

    success_count: int
    failed_count: int
    batches_completed: int


@dataclass
class UploadResult:
    """Final result of an upload run."""

    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error_dict: dict[str, int] = field(default_factory=dict)
    permanent_error: Optional[str] = None


class HECUploader:
    """Streams a local JSONL file to the Splunk HTTP Event Collector.

    Operates in one of two modes:
      * ``event`` — POST newline-delimited JSON envelopes to
        ``/services/collector/event`` with ``index``, ``sourcetype``, ``host``
        and ``source`` embedded in each envelope.
      * ``raw``   — POST raw newline-delimited bytes to
        ``/services/collector/raw`` with metadata passed as URL query params.
    """

    def __init__(
        self,
        file_path: str,
        hec_url: str,
        token: str,
        index: str,
        sourcetype: str = "_json",
        host: Optional[str] = None,
        source: Optional[str] = None,
        endpoint: str = "event",
        verify_tls: bool = True,
        progress_cb: Optional[ProgressCallback] = None,
    ):
        if endpoint not in ("event", "raw"):
            raise ValueError(
                f"Invalid endpoint {endpoint!r}, expected 'event' or 'raw'"
            )

        self.file_path = file_path
        self.hec_url = hec_url.rstrip("/")
        self.token = token
        self.index = index
        self.sourcetype = sourcetype
        self.host = host
        self.source = source
        self.endpoint = endpoint
        self.verify_tls = verify_tls
        self.progress_cb = progress_cb

        self.channel = str(uuid.uuid4())
        self.headers = {
            "User-Agent": "openrelik-worker-export-splunk",
            "Authorization": f"Splunk {self.token}",
            "X-Splunk-Request-Channel": self.channel,
        }

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=CONCURRENCY_LIMIT * 2)
        self.result = UploadResult()
        self._batches_completed = 0
        self._post_url = self._build_url()
        self._cancel = asyncio.Event()

    def _build_url(self) -> str:
        """Construct the appropriate HEC endpoint URL based on the configured mode and metadata."""
        if self.endpoint == "event":
            return f"{self.hec_url}/services/collector/event"

        params = {"index": self.index, "sourcetype": self.sourcetype}
        if self.host:
            params["host"] = self.host
        if self.source:
            params["source"] = self.source
        return f"{self.hec_url}/services/collector/raw?{urlencode(params)}"

    def _wrap_event(self, line: str) -> bytes:
        """Wrap a JSONL line as a Splunk HEC event envelope."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = line  # fall back to sending the raw string as the event
        envelope: dict = {
            "event": event,
            "index": self.index,
            "sourcetype": self.sourcetype,
        }
        if self.host:
            envelope["host"] = self.host
        if self.source:
            envelope["source"] = self.source
        return (json.dumps(envelope) + "\n").encode("utf-8")

    def _encode_line(self, line: str) -> bytes:
        """Encode a JSONL line for POSTing, depending on the endpoint mode."""
        if self.endpoint == "event":
            return self._wrap_event(line)
        return (line + "\n").encode("utf-8")

    async def _enqueue_lines(self) -> None:
        """Producer — read the JSONL file and enqueue batched payloads."""
        batch: list[bytes] = []
        batch_size = 0

        async with aiofiles.open(self.file_path, mode="r", encoding="utf-8") as f:
            async for raw in f:
                if self._cancel.is_set():
                    return
                line = raw.rstrip("\n").rstrip("\r")
                if not line:
                    continue

                encoded = self._encode_line(line)
                encoded_size = len(encoded)

                if encoded_size > MAX_BATCH_SIZE_BYTES:
                    # A single event bigger than HEC's per-request limit is
                    # unsendable; skip rather than producing an oversized
                    # one-event batch that would fail the whole Splunk POST.
                    logger.warning(
                        "Skipping event of %d bytes (exceeds %d-byte HEC limit)",
                        encoded_size,
                        MAX_BATCH_SIZE_BYTES,
                    )
                    self.result.skipped_count += 1
                    continue

                if batch and (
                    batch_size + encoded_size > MAX_BATCH_SIZE_BYTES
                    or len(batch) >= EVENTS_PER_BATCH
                ):
                    await self.queue.put((b"".join(batch), len(batch)))
                    batch = []
                    batch_size = 0

                batch.append(encoded)
                batch_size += encoded_size

        if batch:
            await self.queue.put((b"".join(batch), len(batch)))

    def _record_error(self, key: str) -> None:
        """Record an error occurrence in the result's error_dict."""
        self.result.error_dict[key] = self.result.error_dict.get(key, 0) + 1

    @staticmethod
    def _parse_hec_body(text: str) -> Optional[dict]:
        """Return the Splunk HEC JSON response body if it parses, else None."""
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    @staticmethod
    def _format_permanent_error(status: int, text: str, body: Optional[dict]) -> str:
        """Format a human-readable message for a permanent HEC failure."""
        if body is not None and "code" in body and "text" in body:
            return f"HTTP {status} (Splunk code {body['code']}): {body['text']}"
        return f"HTTP {status}: {text.strip()[:200]}"

    def _classify_failure(self, status: int, text: str) -> Optional[str]:
        """Return a permanent-failure message, or None if the batch should be retried.

        Config-level failures (bad token, bad index, wrong endpoint path) are
        permanent: retrying won't help. Per-event HTTP 400s (codes 5, 6) are
        treated as transient-for-this-batch so the rest of the file can still
        upload.
        """
        if status in PERMANENT_AUTH_STATUS_CODES:
            return self._format_permanent_error(
                status, text, self._parse_hec_body(text)
            )
        if status == 400:
            body = self._parse_hec_body(text)
            code = body.get("code") if body is not None else None
            if code in RETRYABLE_400_CODES:
                return None
            return self._format_permanent_error(status, text, body)
        return None

    async def _worker(self, session: aiohttp.ClientSession) -> None:
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return

            payload, batch_count = item
            retry_count = 0
            success = False

            while (
                retry_count < MAX_RETRIES and not success and not self._cancel.is_set()
            ):
                try:
                    async with session.post(
                        self._post_url,
                        data=payload,
                        headers=self.headers,
                    ) as resp:
                        status = resp.status
                        text = await resp.text()

                        if status == 200:
                            success = True
                        else:
                            error_key = f"{status}_{text.strip()[:120]}"
                            permanent_message = self._classify_failure(status, text)
                            if permanent_message is not None:
                                logger.error(
                                    "Splunk HEC POST permanent failure: %s",
                                    permanent_message,
                                )
                                if self.result.permanent_error is None:
                                    self.result.permanent_error = permanent_message
                                self._record_error(error_key)
                                self._cancel.set()
                                break
                            logger.warning(
                                "Splunk HEC POST failed (attempt %d/%d): %d %s",
                                retry_count + 1,
                                MAX_RETRIES,
                                status,
                                text[:200],
                            )
                            self._record_error(error_key)
                            retry_count += 1
                            await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                except aiohttp.ClientError as e:
                    logger.warning(
                        "Splunk HEC POST raised %s (attempt %d/%d)",
                        e,
                        retry_count + 1,
                        MAX_RETRIES,
                    )
                    self._record_error(f"client_error_{type(e).__name__}")
                    retry_count += 1
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)

            if success:
                self.result.success_count += batch_count
            else:
                self.result.failed_count += batch_count

            self._batches_completed += 1
            if self.progress_cb is not None:
                await self.progress_cb(
                    UploadProgress(
                        success_count=self.result.success_count,
                        failed_count=self.result.failed_count,
                        batches_completed=self._batches_completed,
                    )
                )

            self.queue.task_done()

    async def run(self) -> UploadResult:
        connector = aiohttp.TCPConnector(
            limit=CONCURRENCY_LIMIT,
            ssl=None if self.verify_tls else False,
        )
        producer_error: Optional[Exception] = None
        async with aiohttp.ClientSession(connector=connector) as session:
            workers = [
                asyncio.create_task(self._worker(session))
                for _ in range(CONCURRENCY_LIMIT)
            ]
            producer = asyncio.create_task(self._enqueue_lines())

            try:
                await producer
            except Exception as e:
                producer_error = e
                # Stop workers from POSTing already-queued batches.
                self._cancel.set()

            # Always drain and shut workers down, even on producer failure —
            # otherwise queue.join() blocks forever on un-ack'd batches.
            try:
                await self.queue.join()
            finally:
                for _ in range(CONCURRENCY_LIMIT):
                    await self.queue.put(None)
                await asyncio.gather(*workers, return_exceptions=True)

        if producer_error is not None:
            raise producer_error
        return self.result
