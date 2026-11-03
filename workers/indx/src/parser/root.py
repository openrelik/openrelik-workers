"""Resident $INDEX_ROOT Parser."""

from __future__ import annotations

import logging
import struct

from .carver import carve_slack_entries
from .indx import FILE_ATTR_DIRECTORY, FILE_ATTR_DIRECTORY_ALT, INDEX_ENTRY_END
from .models import IndexEntry, filetime_to_iso

logger = logging.getLogger(__name__)


def parse_index_root(
    buffer: bytes | bytearray, base_offset: int = 0, carve_slack: bool = True
) -> list[IndexEntry]:
    """Parse resident $INDEX_ROOT attribute buffers (attribute type 0x90).

    Supports both full resident attribute records (beginning with 0x90 header)
    and raw Index Root values (beginning with Index Root Header).

    Args:
        buffer: Raw resident attribute record or raw Index Root buffer.
        base_offset: Global stream offset where this buffer begins.
        carve_slack: Whether to carve deleted entries from unallocated slack space.

    Returns:
        List of parsed IndexEntry objects.
    """
    buf_len = len(buffer)
    if buf_len < 32:
        logger.debug(
            "Buffer too small for $INDEX_ROOT (%d bytes) at offset %d",
            buf_len,
            base_offset,
        )
        return []

    root_data = buffer
    root_base = base_offset

    # Check if this is a full resident attribute record (starts with attr type 0x90)
    attr_type = struct.unpack_from("<I", buffer, 0)[0]
    if attr_type == 0x90 and buf_len >= 24:
        non_resident = buffer[8]
        if non_resident != 0:
            logger.warning(
                "Attribute 0x90 marked as non-resident at offset %d", base_offset
            )
            return []

        content_size = struct.unpack_from("<I", buffer, 0x10)[0]
        content_offset = struct.unpack_from("<H", buffer, 0x14)[0]

        if content_offset + content_size > buf_len or content_size < 32:
            logger.debug(
                "Invalid resident content offset %d or size %d at offset %d",
                content_offset,
                content_size,
                base_offset,
            )
            return []

        root_data = buffer[content_offset : content_offset + content_size]
        root_base = base_offset + content_offset

    root_len = len(root_data)
    if root_len < 32:
        return []

    # Index Root Header is 16 bytes (offset 0x00 to 0x10)
    # Node Header is 16 bytes (offset 0x10 to 0x20):
    # - Offset 0x10 (4B): entries_offset (relative to 0x10)
    # - Offset 0x14 (4B): total_entries_size (relative to 0x10)
    # - Offset 0x18 (4B): allocated_size (relative to 0x10)
    # - Offset 0x1C (1B): flags
    entries_offset = struct.unpack_from("<I", root_data, 0x10)[0]
    total_entries_size = struct.unpack_from("<I", root_data, 0x14)[0]

    first_entry_offset = 0x10 + entries_offset
    entries_end_offset = min(0x10 + total_entries_size, root_len)

    active_entries: list[IndexEntry] = []

    if not (0x10 <= first_entry_offset < root_len):
        logger.debug(
            "Invalid first entry offset %d in $INDEX_ROOT at offset %d",
            first_entry_offset,
            root_base,
        )
    else:
        curr_offset = first_entry_offset

        while curr_offset < entries_end_offset:
            if curr_offset + 16 > root_len:
                break

            file_mft_ref = int.from_bytes(
                root_data[curr_offset : curr_offset + 6], "little"
            )
            file_mft_seq = int.from_bytes(
                root_data[curr_offset + 6 : curr_offset + 8], "little"
            )
            entry_len = struct.unpack_from("<H", root_data, curr_offset + 8)[0]
            _ = struct.unpack_from("<H", root_data, curr_offset + 10)[0]
            entry_flags = struct.unpack_from("<H", root_data, curr_offset + 12)[0]

            if (entry_flags & INDEX_ENTRY_END) or entry_len == 0:
                break

            if curr_offset + entry_len > root_len:
                break

            fn_offset = curr_offset + 16
            if fn_offset + 66 <= curr_offset + entry_len and fn_offset + 66 <= root_len:
                parent_mft_ref = int.from_bytes(
                    root_data[fn_offset : fn_offset + 6], "little"
                )
                parent_mft_seq = int.from_bytes(
                    root_data[fn_offset + 6 : fn_offset + 8], "little"
                )

                created_ft, modified_ft, mft_mod_ft, accessed_ft = struct.unpack_from(
                    "<QQQQ", root_data, fn_offset + 8
                )
                allocated_size, real_size = struct.unpack_from(
                    "<QQ", root_data, fn_offset + 40
                )
                file_flags = struct.unpack_from("<I", root_data, fn_offset + 56)[0]

                name_len = root_data[fn_offset + 64]
                namespace = root_data[fn_offset + 65]

                name_bytes_offset = fn_offset + 66
                name_bytes_end = name_bytes_offset + 2 * name_len

                if (
                    name_bytes_end <= curr_offset + entry_len
                    and name_bytes_end <= root_len
                ):
                    name_bytes = root_data[name_bytes_offset:name_bytes_end]
                    try:
                        filename = name_bytes.decode("utf-16le")
                    except (UnicodeDecodeError, ValueError) as exc:
                        logger.debug(
                            "Failed to decode $INDEX_ROOT filename at offset %d: %s",
                            root_base + curr_offset,
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
                            source_offset=root_base + curr_offset,
                        )
                        active_entries.append(entry)

            curr_offset += entry_len

    if not carve_slack:
        logger.debug(
            "Parsed $INDEX_ROOT at offset %d: %d active entries (carve_slack=False)",
            root_base,
            len(active_entries),
        )
        return active_entries

    slack_start = 0x10 + total_entries_size
    slack_entries = carve_slack_entries(
        root_data,
        slack_start=slack_start,
        active_entries=active_entries,
        base_offset=root_base,
    )

    logger.debug(
        "Parsed $INDEX_ROOT at offset %d: %d active, %d slack entries",
        root_base,
        len(active_entries),
        len(slack_entries),
    )

    return active_entries + slack_entries
