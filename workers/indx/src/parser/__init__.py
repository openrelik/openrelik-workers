"""Core NTFS $I30 / INDX Binary Parser, Slack Carver, and Stream Handler."""

from __future__ import annotations

import logging
import tarfile
import zipfile
import zlib
from pathlib import Path

from .carver import carve_slack_entries
from .fixup import apply_fixup
from .indx import parse_active_entries, parse_indx_block
from .mft import parse_mft_file, parse_mft_record, parse_mft_stream
from .models import IndexEntry, filetime_to_iso
from .root import parse_index_root

logger = logging.getLogger(__name__)

__all__ = [
    "IndexEntry",
    "apply_fixup",
    "carve_slack_entries",
    "filetime_to_iso",
    "parse_active_entries",
    "parse_file",
    "parse_index_root",
    "parse_indx_block",
    "parse_mft_file",
    "parse_mft_record",
    "parse_mft_stream",
    "parse_stream",
]


def parse_stream(
    stream_data: bytes, base_offset: int = 0, carve_slack: bool = True
) -> list[IndexEntry]:
    """Parse raw bytes representing an INDX allocation stream or INDEX_ROOT dump.

    Scans 4096-byte blocks for 'INDX' signatures, falling back to signature search
    or $INDEX_ROOT attribute parsing.

    Args:
        stream_data: Binary data to parse.
        base_offset: Global offset within the source.
        carve_slack: Whether to carve slack space for deleted entries.

    Returns:
        List of parsed IndexEntry objects.
    """
    entries: list[IndexEntry] = []
    data_len = len(stream_data)
    if data_len < 24:
        logger.debug(
            "Stream too small for NTFS index structures (%d bytes) at offset %d",
            data_len,
            base_offset,
        )
        return entries

    logger.debug(
        "Parsing stream of %d bytes at base offset %d (carve_slack=%s)",
        data_len,
        base_offset,
        carve_slack,
    )

    # Check if stream is an NTFS $MFT (starts with 'FILE')
    if stream_data.startswith(b"FILE"):
        logger.debug("Stream signature indicates NTFS $MFT at offset %d", base_offset)
        return parse_mft_stream(
            stream_data, base_offset=base_offset, carve_slack=carve_slack
        )

    # Check for resident $INDEX_ROOT first if signature indicates it
    if stream_data.startswith(b"\x90\x00\x00\x00") or (
        data_len < 4096 and stream_data.startswith(b"\x30\x00\x00\x00")
    ):
        logger.debug(
            "Stream signature indicates resident $INDEX_ROOT at offset %d", base_offset
        )
        root_entries = parse_index_root(
            stream_data, base_offset=base_offset, carve_slack=carve_slack
        )
        if root_entries:
            logger.debug(
                "Parsed %d entries from resident $INDEX_ROOT stream at offset %d",
                len(root_entries),
                base_offset,
            )
            return root_entries

    # Check for 4096-byte aligned INDX blocks
    found_aligned = False
    for block_start in range(0, data_len, 4096):
        block = stream_data[block_start : block_start + 4096]
        if block.startswith(b"INDX"):
            found_aligned = True
            block_entries = parse_indx_block(
                block, base_offset=base_offset + block_start, carve_slack=carve_slack
            )
            entries.extend(block_entries)

    if found_aligned:
        logger.debug(
            "Parsed %d entries from aligned INDX blocks in stream at offset %d",
            len(entries),
            base_offset,
        )
        return entries

    # Scan stream for unaligned 'INDX' magic signatures
    logger.debug(
        "No aligned INDX blocks found; scanning for unaligned 'INDX' signatures at offset %d",
        base_offset,
    )
    curr = 0
    while curr < data_len:
        idx = stream_data.find(b"INDX", curr)
        if idx == -1:
            break
        block = stream_data[idx : idx + 4096]
        block_entries = parse_indx_block(
            block, base_offset=base_offset + idx, carve_slack=carve_slack
        )
        entries.extend(block_entries)
        curr = idx + max(len(block), 512)

    if entries:
        logger.debug(
            "Parsed %d entries from unaligned INDX blocks at offset %d",
            len(entries),
            base_offset,
        )
        return entries

    logger.debug(
        "Attempting fallback resident $INDEX_ROOT parsing on stream at offset %d",
        base_offset,
    )
    entries = parse_index_root(
        stream_data, base_offset=base_offset, carve_slack=carve_slack
    )

    logger.debug(
        "Completed parse_stream at offset %d: %d total entries",
        base_offset,
        len(entries),
    )
    return entries


def parse_file(file_path: str | Path, carve_slack: bool = True) -> list[IndexEntry]:
    """Parse a file or archive containing NTFS index streams.

    Supports raw $I30 files, attribute dumps, ZIP bundles, and TAR archives.

    Args:
        file_path: Path to the target file.
        carve_slack: Whether to carve deleted entries from unallocated slack.

    Returns:
        List of parsed IndexEntry objects.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    logger.debug("Parsing file: %s (carve_slack=%s)", path, carve_slack)

    # Check if file is a ZIP archive
    if zipfile.is_zipfile(path):
        logger.debug("File %s identified as ZIP archive", path)
        entries: list[IndexEntry] = []
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                try:
                    data = zf.read(name)
                    member_entries = parse_stream(
                        data, base_offset=0, carve_slack=carve_slack
                    )
                    entries.extend(member_entries)
                    logger.debug(
                        "Parsed %d entries from zip member %s",
                        len(member_entries),
                        name,
                    )
                except (
                    zipfile.BadZipFile,
                    zlib.error,
                    OSError,
                    ValueError,
                ) as e:
                    logger.warning("Failed to parse zip member %s: %s", name, e)
        logger.debug(
            "Extracted %d total entries from ZIP archive %s", len(entries), path
        )
        return entries

    # Check if file is a TAR archive
    if tarfile.is_tarfile(path):
        logger.debug("File %s identified as TAR archive", path)
        entries = []
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                extracted = tf.extractfile(member)
                if extracted is not None:
                    try:
                        data = extracted.read()
                        member_entries = parse_stream(
                            data, base_offset=0, carve_slack=carve_slack
                        )
                        entries.extend(member_entries)
                        logger.debug(
                            "Parsed %d entries from tar member %s",
                            len(member_entries),
                            member.name,
                        )
                    except (tarfile.TarError, OSError, ValueError) as e:
                        logger.warning(
                            "Failed to parse tar member %s: %s", member.name, e
                        )
        logger.debug(
            "Extracted %d total entries from TAR archive %s", len(entries), path
        )
        return entries

    # Check if file is an NTFS $MFT file
    with open(path, "rb") as fh:
        magic = fh.read(4)

    if magic == b"FILE":
        logger.debug("File %s identified as NTFS $MFT", path)
        return parse_mft_file(path, carve_slack=carve_slack)

    # Direct raw binary file
    with open(path, "rb") as fh:
        raw_bytes = fh.read()
    logger.debug("Read %d bytes from raw binary file %s", len(raw_bytes), path)
    entries = parse_stream(raw_bytes, base_offset=0, carve_slack=carve_slack)
    logger.debug("Parsed %d entries from raw binary file %s", len(entries), path)
    return entries
