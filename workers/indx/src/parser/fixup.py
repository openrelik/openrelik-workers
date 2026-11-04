"""NTFS Update Sequence Array (USA) Sector Fixup Engine."""

from __future__ import annotations

import logging
import struct

logger = logging.getLogger(__name__)


def apply_fixup(
    buffer: bytes | bytearray,
    expected_magic: bytes | tuple[bytes, ...] = (b"INDX", b"FILE"),
) -> bytearray:
    """Apply NTFS Update Sequence Array (USA) fixups to an INDX block or MFT record.

    Validates record magic and replaces sector-end sequence check words with
    the original data saved in the Update Sequence Array.

    Args:
        buffer: Raw INDX block or MFT record bytes.
        expected_magic: Expected magic signature bytes or tuple of valid signatures.

    Returns:
        Patched bytearray with fixups applied.

    Raises:
        ValueError: If buffer is too small or magic does not match expected_magic.
    """
    if len(buffer) < 24:
        raise ValueError(
            "Buffer too small for NTFS record header (minimum 24 bytes required)"
        )

    magic = bytes(buffer[:4])
    magics = (expected_magic,) if isinstance(expected_magic, bytes) else expected_magic
    if magic not in magics:
        raise ValueError(f"Invalid record magic: {magic!r}, expected one of {magics!r}")

    # Standard NTFS Record Header: usa_offset at 0x04, usa_count at 0x06
    usa_offset, usa_count = struct.unpack_from("<HH", buffer, 4)

    patched = bytearray(buffer)

    if usa_offset + 2 > len(buffer):
        logger.warning(
            "USA offset %d is outside buffer of length %d", usa_offset, len(buffer)
        )
        return patched

    usa_seq = bytes(buffer[usa_offset : usa_offset + 2])

    for i in range(1, usa_count):
        sector_end = i * 512 - 2
        orig_data_offset = usa_offset + 2 * i

        if sector_end + 2 > len(patched):
            logger.warning(
                "Sector end offset %d exceeds buffer length %d",
                sector_end,
                len(patched),
            )
            break

        if orig_data_offset + 2 > len(patched):
            logger.warning(
                "USA replacement offset %d exceeds buffer length %d",
                orig_data_offset,
                len(patched),
            )
            break

        current_bytes = bytes(patched[sector_end : sector_end + 2])
        if current_bytes != usa_seq:
            logger.warning(
                "USA fixup mismatch at sector %d: expected sequence %s, found %s",
                i,
                usa_seq.hex(),
                current_bytes.hex(),
            )
            continue

        orig_bytes = patched[orig_data_offset : orig_data_offset + 2]
        patched[sector_end : sector_end + 2] = orig_bytes

    return patched
