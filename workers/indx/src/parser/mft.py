"""NTFS Master File Table ($MFT) Record and Resident $INDEX_ROOT Parser."""

from __future__ import annotations

import logging
import struct
from pathlib import Path

from .fixup import apply_fixup
from .models import IndexEntry
from .root import parse_index_root

logger = logging.getLogger(__name__)

MFT_RECORD_SIZE: int = 1024
MFT_MAGIC: bytes = b"FILE"
MFT_RECORD_IN_USE: int = 0x01
MFT_RECORD_IS_DIRECTORY: int = 0x02

ATTR_INDEX_ROOT: int = 0x90
ATTR_END_MARKER: int = 0xFFFFFFFF


def parse_mft_record(
    record_bytes: bytes | bytearray,
    base_offset: int = 0,
    carve_slack: bool = True,
) -> list[IndexEntry]:
    """Parse resident $INDEX_ROOT attributes from a single 1024-byte MFT record.

    Applies USA fixups, traverses record attributes, and parses resident $INDEX_ROOT
    structures (both active entries and slack space).

    Args:
        record_bytes: Raw MFT record bytes (at least 48 bytes).
        base_offset: Global stream offset where this record begins.
        carve_slack: Whether to carve deleted entries from resident $INDEX_ROOT slack.

    Returns:
        List of IndexEntry objects discovered in this MFT record.
    """
    entries: list[IndexEntry] = []
    rec_len = len(record_bytes)
    if rec_len < 48:
        logger.debug(
            "Buffer at offset %d too small for MFT record (%d bytes)",
            base_offset,
            rec_len,
        )
        return entries

    if not record_bytes.startswith(MFT_MAGIC):
        logger.debug(
            "Record at offset %d does not match FILE magic: %r",
            base_offset,
            record_bytes[:4],
        )
        return entries

    try:
        patched = apply_fixup(record_bytes, expected_magic=MFT_MAGIC)
    except (ValueError, struct.error) as e:
        logger.debug("Fixup failed for MFT record at offset %d: %s", base_offset, e)
        patched = bytearray(record_bytes)

    attrs_offset = struct.unpack_from("<H", patched, 0x14)[0]
    bytes_in_use = struct.unpack_from("<I", patched, 0x18)[0]

    if attrs_offset < 0x2A or attrs_offset >= rec_len:
        logger.debug(
            "Invalid attrs_offset %d in MFT record at offset %d",
            attrs_offset,
            base_offset,
        )
        return entries

    limit = min(bytes_in_use if bytes_in_use > attrs_offset else rec_len, rec_len)
    curr_attr = attrs_offset

    while curr_attr + 8 <= limit:
        attr_type = struct.unpack_from("<I", patched, curr_attr)[0]
        if attr_type == ATTR_END_MARKER or attr_type == 0:
            break

        attr_len = struct.unpack_from("<I", patched, curr_attr + 4)[0]
        if attr_len < 8 or curr_attr + attr_len > rec_len:
            logger.debug(
                "Invalid attribute length %d at offset %d",
                attr_len,
                base_offset + curr_attr,
            )
            break

        if attr_type == ATTR_INDEX_ROOT:
            logger.debug(
                "Found resident $INDEX_ROOT attribute at offset %d in MFT record",
                base_offset + curr_attr,
            )
            attr_slice = bytes(patched[curr_attr : curr_attr + attr_len])
            root_entries = parse_index_root(
                attr_slice,
                base_offset=base_offset + curr_attr,
                carve_slack=carve_slack,
            )
            entries.extend(root_entries)

        curr_attr += attr_len

    return entries


def parse_mft_stream(
    stream_data: bytes | bytearray,
    base_offset: int = 0,
    carve_slack: bool = True,
    record_size: int = MFT_RECORD_SIZE,
) -> list[IndexEntry]:
    """Parse MFT records from raw binary stream data.

    Args:
        stream_data: Binary stream containing MFT records.
        base_offset: Global byte offset where this stream begins.
        carve_slack: Whether to carve deleted entries from resident $INDEX_ROOT slack.
        record_size: MFT record size in bytes (default 1024).

    Returns:
        List of parsed IndexEntry objects from all resident $INDEX_ROOT attributes.
    """
    entries: list[IndexEntry] = []
    data_len = len(stream_data)
    if data_len < record_size:
        logger.debug(
            "Stream too small for MFT record (%d bytes, minimum %d required)",
            data_len,
            record_size,
        )
        return entries

    logger.debug(
        "Parsing MFT stream of %d bytes at offset %d (carve_slack=%s)",
        data_len,
        base_offset,
        carve_slack,
    )

    for rec_start in range(0, data_len - record_size + 1, record_size):
        record = stream_data[rec_start : rec_start + record_size]
        if record.startswith(MFT_MAGIC):
            rec_entries = parse_mft_record(
                record,
                base_offset=base_offset + rec_start,
                carve_slack=carve_slack,
            )
            entries.extend(rec_entries)

    logger.debug(
        "Completed MFT stream parsing at offset %d: %d total entries",
        base_offset,
        len(entries),
    )
    return entries


def parse_mft_file(
    file_path: str | Path,
    carve_slack: bool = True,
    record_size: int = MFT_RECORD_SIZE,
    chunk_size: int = 1024 * 1024,
) -> list[IndexEntry]:
    """Stream and parse an NTFS $MFT file in chunks to minimize memory footprint.

    Args:
        file_path: Path to the target $MFT file.
        carve_slack: Whether to carve deleted entries from resident $INDEX_ROOT slack.
        record_size: MFT record size in bytes (default 1024).
        chunk_size: Chunk buffer read size in bytes (must be multiple of record_size).

    Returns:
        List of parsed IndexEntry objects.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    logger.debug("Streaming MFT file: %s (carve_slack=%s)", path, carve_slack)

    entries: list[IndexEntry] = []
    curr_offset = 0
    aligned_chunk_size = max(record_size, (chunk_size // record_size) * record_size)

    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(aligned_chunk_size)
            if not chunk:
                break
            chunk_entries = parse_mft_stream(
                chunk,
                base_offset=curr_offset,
                carve_slack=carve_slack,
                record_size=record_size,
            )
            entries.extend(chunk_entries)
            curr_offset += len(chunk)

    logger.debug(
        "Completed MFT file parsing for %s: %d total entries from %d bytes",
        path,
        len(entries),
        curr_offset,
    )
    return entries
