"""Data models and timestamp utilities for NTFS INDX parsing."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from dfdatetime import filetime

logger = logging.getLogger(__name__)

# Bounds for slack timestamp validation (approx. 1995 to 2045)
MIN_SLACK_FILETIME: int = 0x01A0000000000000
MAX_SLACK_FILETIME: int = 0x0250000000000000


def filetime_to_iso(ft: int | None, is_slack: bool = False) -> str | None:
    """Convert a 64-bit Windows FILETIME to an ISO-8601 UTC string via dfdatetime.

    Args:
        ft: 64-bit Windows FILETIME integer (100-nanosecond intervals since Jan 1, 1601).
        is_slack: If True, enforce plausible historical bounds for slack carving.

    Returns:
        ISO-8601 formatted string (e.g. '2022-06-16T17:46:40.000000+00:00') or None.
    """
    if not isinstance(ft, int) or ft <= 0:
        return None

    if is_slack and not (MIN_SLACK_FILETIME <= ft <= MAX_SLACK_FILETIME):
        return None

    try:
        dt = filetime.Filetime(timestamp=ft)
        iso_str: str = dt.CopyToDateTimeStringISO8601()
        return iso_str
    except (ValueError, OverflowError) as e:
        logger.debug("Failed to convert FILETIME %d to ISO-8601: %s", ft, e)
        return None


@dataclass(slots=True)
class IndexEntry:
    """Represents a single NTFS directory index entry ($I30 / INDX)."""

    filename: str
    parent_mft_ref: int
    parent_mft_seq: int
    file_mft_ref: int
    file_mft_seq: int
    real_size: int
    allocated_size: int
    created_time: str | None
    modified_time: str | None
    mft_modified_time: str | None
    accessed_time: str | None
    is_slack: bool
    is_directory: bool
    namespace: int
    flags: int
    source_offset: int

    def to_dict(self) -> dict[str, Any]:
        """Convert entry to a dictionary."""
        return asdict(self)
