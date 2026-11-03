"""Slack space carver for deleted NTFS index entries."""

from __future__ import annotations

import logging
import struct
from collections.abc import Sequence

from .models import IndexEntry, filetime_to_iso

logger = logging.getLogger(__name__)

# NTFS illegal filename characters
ILLEGAL_FILENAME_CHARS: frozenset[str] = frozenset(
    {"\\", "/", ":", "*", "?", '"', "<", ">", "|", "\x00"}
)


def carve_slack_entries(
    buffer: bytes | bytearray,
    slack_start: int,
    active_entries: Sequence[IndexEntry] | None = None,
    base_offset: int = 0,
) -> list[IndexEntry]:
    """Carve deleted index entries from unallocated slack space.

    Scans the buffer starting from slack_start to the end of the block,
    applying validation to prevent false positives.

    Args:
        buffer: The raw or patched block bytes.
        slack_start: Byte offset where slack space begins.
        active_entries: List of active entries already parsed, used for deduplication.
        base_offset: Base byte offset within larger stream/file.

    Returns:
        List of carved IndexEntry objects with is_slack=True.
    """
    carved_entries: list[IndexEntry] = []
    buf_len = len(buffer)
    if slack_start >= buf_len or buf_len < 82:
        logger.debug(
            "Slack start %d out of bounds or buffer too small (%d bytes), skipping carving",
            slack_start,
            buf_len,
        )
        return carved_entries

    # Build active entry sets for deduplication
    active_keys: set[tuple[str, int, int]] = set()
    active_simple_keys: set[tuple[str, int]] = set()
    if active_entries:
        for entry in active_entries:
            active_keys.add((entry.filename, entry.file_mft_ref, entry.parent_mft_ref))
            active_simple_keys.add((entry.filename, entry.file_mft_ref))

    seen_carved: set[tuple[str, int, int, str | None]] = set()

    curr_offset = max(slack_start, 0)
    max_scan_offset = (
        buf_len - 82
    )  # Minimal index entry size is 82 bytes (0-len filename)

    logger.debug(
        "Scanning slack space from offset %d to %d (buffer length: %d)",
        slack_start,
        max_scan_offset,
        buf_len,
    )

    while curr_offset <= max_scan_offset:
        # Read candidate entry length from entry header (offset 0x08)
        entry_len = struct.unpack_from("<H", buffer, curr_offset + 8)[0]
        remaining_in_buf = buf_len - curr_offset

        # Validation
        if entry_len > remaining_in_buf or entry_len < 82:
            curr_offset += 1
            continue

        name_len = buffer[curr_offset + 80]
        if not (1 <= name_len <= 255):
            curr_offset += 1
            continue

        if entry_len < 82 + 2 * name_len:
            curr_offset += 1
            continue

        if curr_offset + 82 + 2 * name_len > buf_len:
            curr_offset += 1
            continue

        namespace = buffer[curr_offset + 81]
        if namespace not in (0, 1, 2, 3):
            curr_offset += 1
            continue

        name_raw = buffer[curr_offset + 82 : curr_offset + 82 + 2 * name_len]
        try:
            filename = name_raw.decode("utf-16le")
        except (UnicodeDecodeError, ValueError):
            curr_offset += 1
            continue

        if any(
            c in ILLEGAL_FILENAME_CHARS or ord(c) < 32 or not c.isprintable()
            for c in filename
        ):
            curr_offset += 1
            continue

        if not filename.strip():
            curr_offset += 1
            continue

        fn_offset = curr_offset + 16
        created_ft, modified_ft, mft_mod_ft, accessed_ft = struct.unpack_from(
            "<QQQQ", buffer, fn_offset + 8
        )
        created_time = filetime_to_iso(created_ft, is_slack=True)
        modified_time = filetime_to_iso(modified_ft, is_slack=True)

        if created_time is None or modified_time is None:
            curr_offset += 1
            continue

        mft_modified_time = filetime_to_iso(mft_mod_ft, is_slack=True)
        accessed_time = filetime_to_iso(accessed_ft, is_slack=True)

        file_mft_ref = int.from_bytes(buffer[curr_offset : curr_offset + 6], "little")
        file_mft_seq = int.from_bytes(
            buffer[curr_offset + 6 : curr_offset + 8], "little"
        )
        parent_mft_ref = int.from_bytes(buffer[fn_offset : fn_offset + 6], "little")
        parent_mft_seq = int.from_bytes(buffer[fn_offset + 6 : fn_offset + 8], "little")

        if (
            file_mft_ref <= 0
            or file_mft_ref >= (1 << 48)
            or parent_mft_ref >= (1 << 48)
        ):
            curr_offset += 1
            continue

        # Deduplication against active entries
        if (filename, file_mft_ref, parent_mft_ref) in active_keys or (
            filename,
            file_mft_ref,
        ) in active_simple_keys:
            curr_offset += 1
            continue

        carve_key = (filename, file_mft_ref, parent_mft_ref, created_time)
        if carve_key in seen_carved:
            curr_offset += 1
            continue

        # Sizes and flags
        allocated_size, real_size = struct.unpack_from("<QQ", buffer, fn_offset + 40)
        file_flags = struct.unpack_from("<I", buffer, fn_offset + 56)[0]
        flags = struct.unpack_from("<H", buffer, curr_offset + 12)[0]

        if real_size > (1 << 48) or allocated_size > (1 << 48):
            curr_offset += 1
            continue

        is_directory = bool(file_flags & 0x10 or file_flags & 0x10000000)

        entry = IndexEntry(
            filename=filename,
            parent_mft_ref=parent_mft_ref,
            parent_mft_seq=parent_mft_seq,
            file_mft_ref=file_mft_ref,
            file_mft_seq=file_mft_seq,
            real_size=real_size,
            allocated_size=allocated_size,
            created_time=created_time,
            modified_time=modified_time,
            mft_modified_time=mft_modified_time,
            accessed_time=accessed_time,
            is_slack=True,
            is_directory=is_directory,
            namespace=namespace,
            flags=flags,
            source_offset=base_offset + curr_offset,
        )
        carved_entries.append(entry)
        seen_carved.add(carve_key)
        logger.debug(
            "Carved slack entry: %r (MFT: %d, parent: %d, offset: %d)",
            filename,
            file_mft_ref,
            parent_mft_ref,
            base_offset + curr_offset,
        )

        advance_step = max(entry_len, 82 + 2 * name_len)
        curr_offset += max(advance_step, 1)

    logger.debug(
        "Carved %d entries from slack space (block offset: %d, slack start: %d)",
        len(carved_entries),
        base_offset,
        slack_start,
    )
    return carved_entries
