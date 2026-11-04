"""NTFS 4KB INDX Block Parser and Active Entry Traversal Engine."""

from __future__ import annotations

import logging
import struct

from .carver import carve_slack_entries
from .fixup import apply_fixup
from .models import IndexEntry, filetime_to_iso

logger = logging.getLogger(__name__)

INDEX_ENTRY_NODE: int = 0x01
INDEX_ENTRY_END: int = 0x02

FILE_ATTR_DIRECTORY: int = 0x00000010
FILE_ATTR_DIRECTORY_ALT: int = 0x10000000


def parse_active_entries(
    buffer: bytes | bytearray, base_offset: int = 0
) -> tuple[list[IndexEntry], int]:
    """Parse active index entries from an unpacked/fixup-applied INDX block.

    Args:
        buffer: Patched INDX block bytes (at least 40 bytes).
        base_offset: Global stream offset where this block begins.

    Returns:
        Tuple of (list of active IndexEntry instances, total_entries_size from node header).
    """
    active_entries: list[IndexEntry] = []
    buf_len = len(buffer)
    if buf_len < 40:
        logger.debug(
            "Buffer at offset %d too small for INDX header (%d bytes)",
            base_offset,
            buf_len,
        )
        return active_entries, 0

    # Node Header starts at offset 0x18 (24 bytes into the INDX block)
    # Offset 0x18 (4B): entries_offset (relative to 0x18)
    # Offset 0x1C (4B): total_entries_size (relative to 0x18)
    # Offset 0x20 (4B): allocated_size (relative to 0x18)
    # Offset 0x24 (1B): node flags
    entries_offset = struct.unpack_from("<I", buffer, 0x18)[0]
    total_entries_size = struct.unpack_from("<I", buffer, 0x1C)[0]

    first_entry_offset = 0x18 + entries_offset
    entries_end_offset = min(0x18 + total_entries_size, buf_len)

    if first_entry_offset >= buf_len or first_entry_offset < 0x18:
        logger.debug(
            "Invalid first entry offset %d in INDX block at offset %d",
            first_entry_offset,
            base_offset,
        )
        return active_entries, total_entries_size

    curr_offset = first_entry_offset

    while curr_offset < entries_end_offset:
        if curr_offset + 16 > buf_len:
            break

        file_mft_ref = int.from_bytes(buffer[curr_offset : curr_offset + 6], "little")
        file_mft_seq = int.from_bytes(
            buffer[curr_offset + 6 : curr_offset + 8], "little"
        )
        entry_len = struct.unpack_from("<H", buffer, curr_offset + 8)[0]
        _ = struct.unpack_from("<H", buffer, curr_offset + 10)[0]
        entry_flags = struct.unpack_from("<H", buffer, curr_offset + 12)[0]

        if (entry_flags & INDEX_ENTRY_END) or entry_len == 0:
            break

        if curr_offset + entry_len > buf_len:
            break

        # Check if entry contains a $FILE_NAME attribute payload
        fn_offset = curr_offset + 16
        if fn_offset + 66 <= curr_offset + entry_len and fn_offset + 66 <= buf_len:
            parent_mft_ref = int.from_bytes(buffer[fn_offset : fn_offset + 6], "little")
            parent_mft_seq = int.from_bytes(
                buffer[fn_offset + 6 : fn_offset + 8], "little"
            )

            created_ft, modified_ft, mft_mod_ft, accessed_ft = struct.unpack_from(
                "<QQQQ", buffer, fn_offset + 8
            )
            allocated_size, real_size = struct.unpack_from(
                "<QQ", buffer, fn_offset + 40
            )
            file_flags = struct.unpack_from("<I", buffer, fn_offset + 56)[0]

            name_len = buffer[fn_offset + 64]
            namespace = buffer[fn_offset + 65]

            name_bytes_offset = fn_offset + 66
            name_bytes_end = name_bytes_offset + 2 * name_len

            if name_bytes_end <= curr_offset + entry_len and name_bytes_end <= buf_len:
                name_bytes = buffer[name_bytes_offset:name_bytes_end]
                try:
                    filename = name_bytes.decode("utf-16le")
                except (UnicodeDecodeError, ValueError) as exc:
                    logger.debug(
                        "Failed to decode filename for entry at offset %d: %s",
                        base_offset + curr_offset,
                        exc,
                    )
                    filename = ""

                if filename:
                    created_time = filetime_to_iso(created_ft, is_slack=False)
                    modified_time = filetime_to_iso(modified_ft, is_slack=False)
                    mft_modified_time = filetime_to_iso(mft_mod_ft, is_slack=False)
                    accessed_time = filetime_to_iso(accessed_ft, is_slack=False)

                    is_directory = bool(
                        file_flags & FILE_ATTR_DIRECTORY
                        or file_flags & FILE_ATTR_DIRECTORY_ALT
                    )

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
                        is_slack=False,
                        is_directory=is_directory,
                        namespace=namespace,
                        flags=entry_flags,
                        source_offset=base_offset + curr_offset,
                    )
                    active_entries.append(entry)

        curr_offset += entry_len

    return active_entries, total_entries_size


def parse_indx_block(
    buffer: bytes | bytearray, base_offset: int = 0, carve_slack: bool = True
) -> list[IndexEntry]:
    """Parse a single INDX block (usually 4096 bytes).

    Applies sector fixups, parses active index entries, and carves slack space.

    Args:
        buffer: Raw INDX block bytes.
        base_offset: Global stream offset where this block begins.
        carve_slack: Whether to carve deleted entries from unallocated slack space.

    Returns:
        List of IndexEntry objects (active followed by carved slack entries).
    """
    if len(buffer) < 40 or buffer[:4] != b"INDX":
        return []

    try:
        patched = apply_fixup(buffer)
    except (ValueError, struct.error) as e:
        logger.warning("Fixup failed for block at offset %d: %s", base_offset, e)
        patched = bytearray(buffer)

    active_entries, total_entries_size = parse_active_entries(
        patched, base_offset=base_offset
    )

    if not carve_slack:
        return active_entries

    slack_start = 0x18 + total_entries_size
    slack_entries = carve_slack_entries(
        patched,
        slack_start=slack_start,
        active_entries=active_entries,
        base_offset=base_offset,
    )

    logger.debug(
        "Parsed INDX block at offset %d: %d active, %d slack entries",
        base_offset,
        len(active_entries),
        len(slack_entries),
    )

    return active_entries + slack_entries
