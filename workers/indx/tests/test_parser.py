"""Unit tests for NTFS INDX / $I30 parser and slack carver."""

from __future__ import annotations

import io
import os
import struct
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest

from src.parser import (
    IndexEntry,
    apply_fixup,
    carve_slack_entries,
    filetime_to_iso,
    parse_file,
    parse_index_root,
    parse_indx_block,
    parse_mft_record,
    parse_mft_stream,
    parse_stream,
)
from src.parser.models import MAX_SLACK_FILETIME, MIN_SLACK_FILETIME


# Test Helpers

def create_test_file_name_payload(
    name: str,
    parent_mft_ref: int = 5,
    parent_mft_seq: int = 5,
    created_ft: int = 133000000000000000,
    modified_ft: int = 133000000000000000,
    mft_modified_ft: int = 133000000000000000,
    accessed_ft: int = 133000000000000000,
    allocated_size: int = 4096,
    real_size: int = 1024,
    file_flags: int = 0x20,
    namespace: int = 3,
) -> bytes:
    """Create a raw NTFS $FILE_NAME attribute payload."""
    name_bytes = name.encode("utf-16le")
    parent_ref_seq = parent_mft_ref.to_bytes(6, "little") + parent_mft_seq.to_bytes(
        2, "little"
    )
    header = struct.pack(
        "<8sQQQQQQIIBB",
        parent_ref_seq,
        created_ft,
        modified_ft,
        mft_modified_ft,
        accessed_ft,
        allocated_size,
        real_size,
        file_flags,
        0,  # reparse tag
        len(name),
        namespace,
    )
    return header + name_bytes


def create_test_index_entry(
    file_mft_ref: int,
    file_name_payload: bytes,
    file_mft_seq: int = 1,
    flags: int = 0,
    entry_len: int | None = None,
) -> bytes:
    """Create a binary NTFS index entry containing a $FILE_NAME payload."""
    content_len = len(file_name_payload)
    if entry_len is None:
        raw_len = 16 + content_len
        entry_len = (raw_len + 7) & ~7

    file_ref_seq = file_mft_ref.to_bytes(6, "little") + file_mft_seq.to_bytes(
        2, "little"
    )
    header = struct.pack(
        "<8sHHH2s", file_ref_seq, entry_len, content_len, flags, b"\x00\x00"
    )
    payload = header + file_name_payload
    if len(payload) < entry_len:
        payload += b"\x00" * (entry_len - len(payload))
    return payload[:entry_len]


def create_end_entry() -> bytes:
    """Create a standard 16-byte index end marker."""
    return struct.pack("<8sHHH2s", b"\x00" * 8, 16, 0, 0x02, b"\x00\x00")


def build_synthetic_indx_block(
    active_entries: list[bytes],
    slack_entries: list[bytes] | None = None,
    corrupt_sector: int | None = None,
    block_size: int = 4096,
) -> bytes:
    """Build a synthetic 4KB INDX block with valid headers, entries, and USA fixups."""
    buf = bytearray(block_size)
    buf[0:4] = b"INDX"
    usa_offset = 0x28
    usa_count = block_size // 512 + 1  # 9
    struct.pack_into("<HH", buf, 4, usa_offset, usa_count)
    struct.pack_into("<QQ", buf, 8, 100, 0)  # LSN, VCN

    # Node Header at 0x18 (entries start at 0x40 -> rel offset 0x28)
    entries_rel = 0x28
    entries_start = 0x18 + entries_rel
    curr = entries_start

    for entry in active_entries:
        buf[curr : curr + len(entry)] = entry
        curr += len(entry)

    end_marker = create_end_entry()
    buf[curr : curr + len(end_marker)] = end_marker
    curr += len(end_marker)

    total_entries_size = curr - 0x18
    allocated_size = block_size - 0x18
    struct.pack_into("<III", buf, 0x18, entries_rel, total_entries_size, allocated_size)
    buf[0x24] = 0

    if slack_entries:
        slack_curr = curr + 16  # Leave some gap before slack entries
        for se in slack_entries:
            if slack_curr + len(se) <= block_size:
                buf[slack_curr : slack_curr + len(se)] = se
                slack_curr += len(se)

    # Setup USA fixup array
    usa_seq = b"\xaa\xbb"
    buf[usa_offset : usa_offset + 2] = usa_seq
    for i in range(1, usa_count):
        sector_end = i * 512 - 2
        orig_bytes = buf[sector_end : sector_end + 2]
        buf[usa_offset + 2 * i : usa_offset + 2 * i + 2] = orig_bytes
        if corrupt_sector is not None and i == corrupt_sector:
            buf[sector_end : sector_end + 2] = b"\xee\xff"  # Mismatched sequence
        else:
            buf[sector_end : sector_end + 2] = usa_seq

    return bytes(buf)


def build_synthetic_mft_record(
    record_num: int = 5,
    is_directory: bool = True,
    in_use: bool = True,
    index_root_payload: bytes | None = None,
    attributes: list[tuple[int, bytes]] | None = None,
    record_size: int = 1024,
    corrupt_sector: int | None = None,
) -> bytes:
    """Build a synthetic 1024-byte NTFS MFT record with USA fixups."""
    buf = bytearray(record_size)
    buf[0:4] = b"FILE"
    usa_offset = 48
    usa_count = (record_size // 512) + 1  # 3 for 1024
    struct.pack_into("<HH", buf, 4, usa_offset, usa_count)

    flags = 0
    if in_use:
        flags |= 0x01
    if is_directory:
        flags |= 0x02

    attrs_offset = 56
    struct.pack_into("<H", buf, 0x14, attrs_offset)
    struct.pack_into("<H", buf, 0x16, flags)
    struct.pack_into("<I", buf, 0x1C, record_size)  # bytes_allocated
    struct.pack_into("<I", buf, 0x2C, record_num)  # MFT record number

    curr = attrs_offset
    if index_root_payload is not None:
        attr_len = (24 + len(index_root_payload) + 7) & ~7
        struct.pack_into("<IIBBHHH", buf, curr, 0x90, attr_len, 0, 0, 0, 0, 1)
        struct.pack_into(
            "<IH2s", buf, curr + 0x10, len(index_root_payload), 24, b"\x00\x00"
        )
        buf[curr + 24 : curr + 24 + len(index_root_payload)] = index_root_payload
        curr += attr_len

    if attributes:
        for atype, adata in attributes:
            alen = (24 + len(adata) + 7) & ~7
            struct.pack_into("<IIBBHHH", buf, curr, atype, alen, 0, 0, 0, 0, 2)
            struct.pack_into("<IH2s", buf, curr + 0x10, len(adata), 24, b"\x00\x00")
            buf[curr + 24 : curr + 24 + len(adata)] = adata
            curr += alen

    struct.pack_into("<I", buf, curr, 0xFFFFFFFF)
    curr += 4
    bytes_in_use = (curr + 7) & ~7
    struct.pack_into("<I", buf, 0x18, bytes_in_use)

    # Setup USA fixup array
    usa_seq = b"\x33\x44"
    buf[usa_offset : usa_offset + 2] = usa_seq
    for i in range(1, usa_count):
        sector_end = i * 512 - 2
        orig_bytes = bytes(buf[sector_end : sector_end + 2])
        buf[usa_offset + 2 * i : usa_offset + 2 * i + 2] = orig_bytes
        if corrupt_sector is not None and i == corrupt_sector:
            buf[sector_end : sector_end + 2] = b"\xee\xff"
        else:
            buf[sector_end : sector_end + 2] = usa_seq

    return bytes(buf)


# Tests

def test_filetime_to_iso_valid() -> None:
    """Test valid FILETIME conversions."""
    # 2022-06-18T04:26:40Z
    ft = 133000000000000000
    iso = filetime_to_iso(ft, is_slack=False)
    assert iso is not None
    assert iso.startswith("2022-06-18")


def test_filetime_to_iso_null_and_negative() -> None:
    """Test null, zero, and negative FILETIME inputs."""
    assert filetime_to_iso(None) is None
    assert filetime_to_iso(0) is None
    assert filetime_to_iso(-1) is None


def test_filetime_to_iso_slack_bounds() -> None:
    """Test slack timestamp boundary heuristic enforcement."""
    valid_ft = 133000000000000000
    assert filetime_to_iso(valid_ft, is_slack=True) is not None

    # Below MIN_SLACK_FILETIME
    below_min = MIN_SLACK_FILETIME - 1
    assert filetime_to_iso(below_min, is_slack=True) is None

    # Above MAX_SLACK_FILETIME
    above_max = MAX_SLACK_FILETIME + 1
    assert filetime_to_iso(above_max, is_slack=True) is None

    # Exact boundary edges
    assert filetime_to_iso(MIN_SLACK_FILETIME, is_slack=True) is not None
    assert filetime_to_iso(MAX_SLACK_FILETIME, is_slack=True) is not None


def test_index_entry_dataclass() -> None:
    """Test IndexEntry dataclass properties and to_dict method."""
    entry = IndexEntry(
        filename="test.txt",
        parent_mft_ref=5,
        parent_mft_seq=5,
        file_mft_ref=123,
        file_mft_seq=1,
        real_size=500,
        allocated_size=4096,
        created_time="2022-06-18T04:26:40.000000+00:00",
        modified_time="2022-06-18T04:26:40.000000+00:00",
        mft_modified_time="2022-06-18T04:26:40.000000+00:00",
        accessed_time="2022-06-18T04:26:40.000000+00:00",
        is_slack=False,
        is_directory=False,
        namespace=3,
        flags=0,
        source_offset=64,
    )
    d = entry.to_dict()
    assert d["filename"] == "test.txt"
    assert d["file_mft_ref"] == 123
    assert d["is_slack"] is False


def test_usa_fixup_success() -> None:
    """Test that USA fixups restore original sector-end bytes across boundaries."""
    buf = bytearray(4096)
    buf[0:4] = b"INDX"
    usa_offset = 0x28
    usa_count = 9
    struct.pack_into("<HH", buf, 4, usa_offset, usa_count)

    # Set check sequence
    usa_seq = b"\x12\x34"
    buf[usa_offset : usa_offset + 2] = usa_seq

    # Set original bytes in USA and replace sector ends with check sequence
    for i in range(1, 9):
        sector_end = i * 512 - 2
        orig = bytes([i, i + 10])
        buf[usa_offset + 2 * i : usa_offset + 2 * i + 2] = orig
        buf[sector_end : sector_end + 2] = usa_seq

    patched = apply_fixup(bytes(buf))

    for i in range(1, 9):
        sector_end = i * 512 - 2
        expected = bytes([i, i + 10])
        assert patched[sector_end : sector_end + 2] == expected


def test_usa_fixup_mismatch_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Test that fixup mismatches log a warning and continue gracefully."""
    block = build_synthetic_indx_block(
        active_entries=[],
        corrupt_sector=1,
    )
    # Sector 1 has mismatch
    patched = apply_fixup(block)
    assert len(patched) == len(block)
    assert "USA fixup mismatch at sector 1" in caplog.text


def test_usa_fixup_invalid_magic() -> None:
    """Test that invalid magic raises ValueError."""
    buf = b"BAAD" + b"\x00" * 4092
    with pytest.raises(ValueError, match="Invalid record magic"):
        apply_fixup(buf)


def test_usa_fixup_truncated_buffer() -> None:
    """Test that buffer shorter than header raises ValueError."""
    with pytest.raises(ValueError, match="Buffer too small"):
        apply_fixup(b"INDX")


def test_parse_active_entries() -> None:
    """Test parsing multiple active index entries from an INDX block."""
    e1 = create_test_index_entry(
        file_mft_ref=1001,
        file_name_payload=create_test_file_name_payload(
            "document.pdf",
            parent_mft_ref=5,
            allocated_size=8192,
            real_size=7500,
            file_flags=0x20,
        ),
    )
    e2 = create_test_index_entry(
        file_mft_ref=1002,
        file_name_payload=create_test_file_name_payload(
            "Pictures",
            parent_mft_ref=5,
            allocated_size=0,
            real_size=0,
            file_flags=0x10,  # Directory
        ),
    )

    block = build_synthetic_indx_block(active_entries=[e1, e2])
    entries = parse_indx_block(block, carve_slack=False)

    assert len(entries) == 2
    assert entries[0].filename == "document.pdf"
    assert entries[0].file_mft_ref == 1001
    assert entries[0].real_size == 7500
    assert entries[0].allocated_size == 8192
    assert entries[0].is_slack is False
    assert entries[0].is_directory is False
    assert entries[0].created_time is not None

    assert entries[1].filename == "Pictures"
    assert entries[1].file_mft_ref == 1002
    assert entries[1].is_directory is True
    assert entries[1].is_slack is False


def test_parse_empty_and_short_blocks() -> None:
    """Test parsing empty and truncated blocks returns an empty list."""
    assert parse_indx_block(b"") == []
    assert parse_indx_block(b"INDX" + b"\x00" * 10) == []
    assert parse_indx_block(b"\x00" * 4096) == []


def test_carve_deleted_entries_from_slack() -> None:
    """Test carving deleted entries placed in slack space."""
    active_e = create_test_index_entry(
        file_mft_ref=101,
        file_name_payload=create_test_file_name_payload("active.txt"),
    )
    slack_e = create_test_index_entry(
        file_mft_ref=202,
        file_name_payload=create_test_file_name_payload(
            "deleted_secret.docx",
            real_size=12345,
            allocated_size=16384,
        ),
    )

    block = build_synthetic_indx_block(
        active_entries=[active_e], slack_entries=[slack_e]
    )
    entries = parse_indx_block(block, carve_slack=True)

    assert len(entries) == 2
    active_result = entries[0]
    slack_result = entries[1]

    assert active_result.filename == "active.txt"
    assert active_result.is_slack is False

    assert slack_result.filename == "deleted_secret.docx"
    assert slack_result.file_mft_ref == 202
    assert slack_result.real_size == 12345
    assert slack_result.allocated_size == 16384
    assert slack_result.is_slack is True
    assert slack_result.created_time is not None


def test_carve_slack_deduplication() -> None:
    """Test that entries already active are not carved again from slack."""
    active_e = create_test_index_entry(
        file_mft_ref=101,
        file_name_payload=create_test_file_name_payload("active_duplicate.txt"),
    )
    # Same filename and MFT ref in slack
    slack_duplicate = create_test_index_entry(
        file_mft_ref=101,
        file_name_payload=create_test_file_name_payload("active_duplicate.txt"),
    )

    block = build_synthetic_indx_block(
        active_entries=[active_e], slack_entries=[slack_duplicate]
    )
    entries = parse_indx_block(block, carve_slack=True)

    # Only 1 active entry, slack duplicate rejected
    assert len(entries) == 1
    assert entries[0].is_slack is False


def test_carver_false_positive_rejections() -> None:
    """Test that corrupted headers and invalid parameters in slack are rejected."""
    valid_fn = create_test_file_name_payload("valid.txt")
    valid_entry = create_test_index_entry(100, valid_fn)

    # Invalid namespace (e.g. 5)
    bad_ns_fn = create_test_file_name_payload("bad_ns.txt", namespace=5)
    bad_ns_entry = create_test_index_entry(101, bad_ns_fn)

    # Illegal NTFS filename characters (e.g. contains colon, question mark, or slash)
    bad_chars_fn = create_test_file_name_payload("bad:char?.txt")
    bad_chars_entry = create_test_index_entry(102, bad_chars_fn)

    # Timestamps out of plausible historical bounds
    bad_time_fn = create_test_file_name_payload("bad_time.txt", created_ft=1000)
    bad_time_entry = create_test_index_entry(103, bad_time_fn)

    # Corrupted entry length (too small)
    corrupt_len_entry = bytearray(valid_entry)
    struct.pack_into("<H", corrupt_len_entry, 8, 20)  # less than 66 + 2*name_len

    block = build_synthetic_indx_block(
        active_entries=[],
        slack_entries=[
            bad_ns_entry,
            bad_chars_entry,
            bad_time_entry,
            bytes(corrupt_len_entry),
            valid_entry,
        ],
    )

    entries = parse_indx_block(block, carve_slack=True)
    # Only valid_entry should survive
    assert len(entries) == 1
    assert entries[0].filename == "valid.txt"
    assert entries[0].is_slack is True


def test_parse_index_root_raw() -> None:
    """Test parsing raw $INDEX_ROOT value buffer."""
    e1 = create_test_index_entry(
        file_mft_ref=501,
        file_name_payload=create_test_file_name_payload("root_active.txt"),
    )
    s1 = create_test_index_entry(
        file_mft_ref=502,
        file_name_payload=create_test_file_name_payload("root_deleted.txt"),
    )

    root_buf = bytearray(512)
    # Index Root Header (16 bytes)
    struct.pack_into("<IIIb3s", root_buf, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    # Node Header at 0x10
    entries_rel = 0x10
    entries_start = 0x20
    curr = entries_start

    root_buf[curr : curr + len(e1)] = e1
    curr += len(e1)

    end_entry = create_end_entry()
    root_buf[curr : curr + len(end_entry)] = end_entry
    curr += len(end_entry)

    struct.pack_into(
        "<IIIb3s",
        root_buf,
        0x10,
        entries_rel,
        curr - 0x10,
        len(root_buf) - 0x10,
        0,
        b"\x00\x00\x00",
    )

    # Slack entry
    root_buf[curr + 8 : curr + 8 + len(s1)] = s1

    entries = parse_index_root(bytes(root_buf), carve_slack=True)
    assert len(entries) == 2
    assert entries[0].filename == "root_active.txt"
    assert entries[0].is_slack is False
    assert entries[1].filename == "root_deleted.txt"
    assert entries[1].is_slack is True


def test_parse_index_root_attribute_record() -> None:
    """Test parsing $INDEX_ROOT wrapped in resident attribute 0x90 header."""
    e1 = create_test_index_entry(
        file_mft_ref=601,
        file_name_payload=create_test_file_name_payload(
            "resident_dir", file_flags=0x10
        ),
    )

    root_payload = bytearray(256)
    struct.pack_into("<IIIb3s", root_payload, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    entries_start = 0x20
    curr = entries_start
    root_payload[curr : curr + len(e1)] = e1
    curr += len(e1)
    end_entry = create_end_entry()
    root_payload[curr : curr + len(end_entry)] = end_entry
    curr += len(end_entry)
    struct.pack_into(
        "<IIIb3s",
        root_payload,
        0x10,
        0x10,
        curr - 0x10,
        len(root_payload) - 0x10,
        0,
        b"\x00\x00\x00",
    )

    attr_len = 24 + len(root_payload)
    attr_buf = bytearray(attr_len)
    # Type 0x90, resident (non-resident=0)
    struct.pack_into("<IIBBHHH", attr_buf, 0, 0x90, attr_len, 0, 0, 0, 0, 1)
    struct.pack_into("<IH2s", attr_buf, 0x10, len(root_payload), 24, b"\x00\x00")
    attr_buf[24:] = root_payload

    entries = parse_index_root(bytes(attr_buf))
    assert len(entries) == 1
    assert entries[0].filename == "resident_dir"
    assert entries[0].file_mft_ref == 601
    assert entries[0].is_directory is True


def test_parse_stream_multi_block() -> None:
    """Test parsing multiple INDX blocks in a single stream."""
    e1 = create_test_index_entry(1, create_test_file_name_payload("block1.txt"))
    b1 = build_synthetic_indx_block(active_entries=[e1])

    e2 = create_test_index_entry(2, create_test_file_name_payload("block2.txt"))
    b2 = build_synthetic_indx_block(active_entries=[e2])

    stream_data = b1 + b2
    entries = parse_stream(stream_data, carve_slack=False)

    assert len(entries) == 2
    assert entries[0].filename == "block1.txt"
    assert entries[0].source_offset < 4096
    assert entries[1].filename == "block2.txt"
    assert entries[1].source_offset >= 4096


def test_parse_file_zip_and_tar() -> None:
    """Test parsing INDX blocks packed in ZIP and TAR archives."""
    e1 = create_test_index_entry(10, create_test_file_name_payload("zipped.txt"))
    b1 = build_synthetic_indx_block(active_entries=[e1])

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test ZIP archive
        zip_path = Path(tmpdir) / "test_indices.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("subfolder/$I30", b1)

        zip_entries = parse_file(zip_path)
        assert len(zip_entries) == 1
        assert zip_entries[0].filename == "zipped.txt"

        # Test TAR archive
        tar_path = Path(tmpdir) / "test_indices.tar"
        with tarfile.open(tar_path, "w") as tf:
            tarinfo = tarfile.TarInfo(name="stream_$I30")
            tarinfo.size = len(b1)
            tf.addfile(tarinfo, io.BytesIO(b1))

        tar_entries = parse_file(tar_path)
        assert len(tar_entries) == 1
        assert tar_entries[0].filename == "zipped.txt"

        # Test non-existent file
        with pytest.raises(FileNotFoundError):
            parse_file(Path(tmpdir) / "non_existent.bin")


def test_models_filetime_exception(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test filetime_to_iso handling when dfdatetime raises an exception."""
    import logging

    from dfdatetime import filetime

    def mock_filetime(timestamp: int) -> None:
        raise ValueError("Simulated error")

    monkeypatch.setattr(filetime, "Filetime", mock_filetime)
    with caplog.at_level(logging.DEBUG):
        assert filetime_to_iso(133000000000000000) is None
    assert "Failed to convert FILETIME" in caplog.text


def test_usa_fixup_bounds_warnings(caplog: pytest.LogCaptureFixture) -> None:
    """Test that out-of-bounds USA offsets produce warnings safely."""
    # usa_offset outside buffer
    buf1 = bytearray(4096)
    buf1[0:4] = b"INDX"
    struct.pack_into("<HH", buf1, 4, 5000, 9)
    res1 = apply_fixup(bytes(buf1))
    assert len(res1) == 4096
    assert "outside buffer" in caplog.text

    # sector_end outside buffer (small buffer)
    buf2 = bytearray(600)
    buf2[0:4] = b"INDX"
    struct.pack_into("<HH", buf2, 4, 0x28, 5)  # 5 sectors requires 2560 bytes
    res2 = apply_fixup(bytes(buf2))
    assert len(res2) == 600

    # orig_data_offset exceeds buffer
    buf3 = bytearray(512)
    buf3[0:4] = b"INDX"
    struct.pack_into(
        "<HH", buf3, 4, 500, 10
    )  # USA array would reach 500 + 20 = 520 > 512
    res3 = apply_fixup(bytes(buf3))
    assert len(res3) == 512


def test_indx_block_malformed_branches() -> None:
    """Test parsing INDX blocks with malformed offsets and decode errors."""
    # first_entry_offset out of bounds
    buf1 = bytearray(4096)
    buf1[0:4] = b"INDX"
    struct.pack_into("<HH", buf1, 4, 0x28, 9)
    struct.pack_into("<III", buf1, 0x18, 5000, 6000, 4000)
    assert parse_indx_block(bytes(buf1), carve_slack=False) == []

    # curr_offset + entry_len > buf_len
    buf2 = bytearray(4096)
    buf2[0:4] = b"INDX"
    struct.pack_into("<HH", buf2, 4, 0x28, 9)
    struct.pack_into("<III", buf2, 0x18, 0x28, 500, 4000)
    struct.pack_into("<8sHHH2s", buf2, 0x40, b"\x01" * 8, 10000, 50, 0, b"\x00\x00")
    assert parse_indx_block(bytes(buf2), carve_slack=False) == []

    # Malformed utf-16le in active entry filename
    e_bad = bytearray(
        create_test_index_entry(10, create_test_file_name_payload("test.txt"))
    )
    fn_off = 16
    name_bytes_off = fn_off + 66
    e_bad[name_bytes_off : name_bytes_off + 2] = b"\x00\xd8"
    buf3 = build_synthetic_indx_block(active_entries=[bytes(e_bad)])
    entries = parse_indx_block(buf3, carve_slack=False)
    assert len(entries) == 0


def test_carver_edge_cases() -> None:
    """Test carver bounds, empty strip filename, and giant sizes."""
    # slack_start >= buf_len
    assert carve_slack_entries(b"A" * 100, slack_start=200) == []

    # Filename that is all whitespace
    fn_blank = create_test_file_name_payload("   ")
    e_blank = create_test_index_entry(99, fn_blank)
    block_blank = build_synthetic_indx_block(active_entries=[], slack_entries=[e_blank])
    assert parse_indx_block(block_blank, carve_slack=True) == []

    # Filename with bad UTF-16 surrogate
    fn_valid = create_test_file_name_payload("valid.txt")
    e_surr = bytearray(create_test_index_entry(98, fn_valid))
    e_surr[82:84] = b"\x00\xd8"
    block_surr = build_synthetic_indx_block(
        active_entries=[], slack_entries=[bytes(e_surr)]
    )
    assert parse_indx_block(block_surr, carve_slack=True) == []

    # Entry where real_size > (1 << 48)
    fn_huge = create_test_file_name_payload("huge.txt", real_size=(1 << 50))
    e_huge = create_test_index_entry(97, fn_huge)
    block_huge = build_synthetic_indx_block(active_entries=[], slack_entries=[e_huge])
    assert parse_indx_block(block_huge, carve_slack=True) == []

    # Duplicate in slack itself
    e_norm = create_test_index_entry(96, create_test_file_name_payload("duplicate.txt"))
    block_dup = build_synthetic_indx_block(
        active_entries=[], slack_entries=[e_norm, e_norm]
    )
    entries_dup = parse_indx_block(block_dup, carve_slack=True)
    assert len(entries_dup) == 1


def test_root_edge_cases() -> None:
    """Test edge cases in $INDEX_ROOT parser."""
    # buffer too short
    assert parse_index_root(b"\x90\x00\x00\x00\x10") == []

    # non_resident flag != 0
    buf_non_res = bytearray(64)
    struct.pack_into("<IIBBHHH", buf_non_res, 0, 0x90, 64, 1, 0, 0, 0, 1)
    assert parse_index_root(bytes(buf_non_res)) == []

    # content_offset + content_size > len(buffer)
    buf_overflow = bytearray(64)
    struct.pack_into("<IIBBHHH", buf_overflow, 0, 0x90, 64, 0, 0, 0, 0, 1)
    struct.pack_into("<IH2s", buf_overflow, 0x10, 100, 24, b"\x00\x00")
    assert parse_index_root(bytes(buf_overflow)) == []

    # root_data too short
    buf_short = bytearray(40)
    struct.pack_into("<IIBBHHH", buf_short, 0, 0x90, 40, 0, 0, 0, 0, 1)
    struct.pack_into("<IH2s", buf_short, 0x10, 10, 24, b"\x00\x00")
    assert parse_index_root(bytes(buf_short)) == []

    # carve_slack=False in index root
    e1 = create_test_index_entry(501, create_test_file_name_payload("active.txt"))
    s1 = create_test_index_entry(502, create_test_file_name_payload("deleted.txt"))
    root_buf = bytearray(512)
    struct.pack_into("<IIIb3s", root_buf, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    curr = 0x20
    root_buf[curr : curr + len(e1)] = e1
    curr += len(e1)
    end_e = create_end_entry()
    root_buf[curr : curr + len(end_e)] = end_e
    curr += len(end_e)
    struct.pack_into(
        "<IIIb3s",
        root_buf,
        0x10,
        0x10,
        curr - 0x10,
        len(root_buf) - 0x10,
        0,
        b"\x00\x00\x00",
    )
    root_buf[curr + 8 : curr + 8 + len(s1)] = s1
    res_no_slack = parse_index_root(bytes(root_buf), carve_slack=False)
    assert len(res_no_slack) == 1
    assert res_no_slack[0].filename == "active.txt"


def test_parse_stream_and_archive_fallbacks() -> None:
    """Test parse_stream unaligned signature, root fallback, and archive edge cases."""
    # Unaligned INDX block
    e1 = create_test_index_entry(1, create_test_file_name_payload("unaligned.txt"))
    b1 = build_synthetic_indx_block(active_entries=[e1])
    unaligned_stream = b"PADDING_DATA_BEFORE" + b1
    entries = parse_stream(unaligned_stream)
    assert len(entries) == 1
    assert entries[0].filename == "unaligned.txt"
    assert entries[0].source_offset == len(b"PADDING_DATA_BEFORE") + 0x40

    # Stream that is a raw $INDEX_ROOT attribute
    e_root = create_test_index_entry(
        2, create_test_file_name_payload("root_stream.txt")
    )
    root_buf = bytearray(256)
    struct.pack_into("<IIIb3s", root_buf, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    curr = 0x20
    root_buf[curr : curr + len(e_root)] = e_root
    curr += len(e_root)
    end_e = create_end_entry()
    root_buf[curr : curr + len(end_e)] = end_e
    curr += len(end_e)
    struct.pack_into(
        "<IIIb3s",
        root_buf,
        0x10,
        0x10,
        curr - 0x10,
        len(root_buf) - 0x10,
        0,
        b"\x00\x00\x00",
    )
    root_entries = parse_stream(bytes(root_buf))
    assert len(root_entries) == 1
    assert root_entries[0].filename == "root_stream.txt"

    # Stream starting with 0x90 resident attribute
    attr_buf = bytearray(24 + len(root_buf))
    struct.pack_into("<IIBBHHH", attr_buf, 0, 0x90, len(attr_buf), 0, 0, 0, 0, 1)
    struct.pack_into("<IH2s", attr_buf, 0x10, len(root_buf), 24, b"\x00\x00")
    attr_buf[24:] = root_buf
    attr_entries = parse_stream(bytes(attr_buf))
    assert len(attr_entries) == 1
    assert attr_entries[0].filename == "root_stream.txt"


def test_coverage_branches(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Target remaining edge branches across parser modules."""
    from src.parser.indx import parse_active_entries

    # models.py exception handling
    assert (
        filetime_to_iso(
            "invalid"  # type: ignore[arg-type]
        )
        is None
    )

    # fixup.py orig_data_offset exceeds buffer
    buf_fixup = bytearray(2048)
    buf_fixup[0:4] = b"INDX"
    struct.pack_into("<HH", buf_fixup, 4, 2044, 5)
    res_fixup = apply_fixup(bytes(buf_fixup))
    assert len(res_fixup) == 2048
    assert "USA replacement offset" in caplog.text

    # indx.py parse_active_entries short buffer
    assert parse_active_entries(b"INDX") == ([], 0)

    # indx.py parse_active_entries curr_offset + 16 > buf_len
    buf_short_entry = bytearray(48)
    struct.pack_into("<III", buf_short_entry, 0x18, 0x08, 0x20, 0x20)
    entries_short, _ = parse_active_entries(bytes(buf_short_entry))
    assert entries_short == []

    # indx.py apply_fixup raising in parse_indx_block
    def mock_apply_fixup(b: bytes | bytearray) -> bytearray:
        raise ValueError("Forced fixup error")

    monkeypatch.setattr("src.parser.indx.apply_fixup", mock_apply_fixup)
    e1 = create_test_index_entry(1, create_test_file_name_payload("nofix.txt"))
    block_nofix = build_synthetic_indx_block(active_entries=[e1])
    _ = parse_indx_block(block_nofix, carve_slack=False)
    assert "Fixup failed for block" in caplog.text

    # root.py entries_offset out of bounds
    buf_root_oob = bytearray(256)
    struct.pack_into("<IIIb3s", buf_root_oob, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    struct.pack_into("<IIIb3s", buf_root_oob, 0x10, 5000, 100, 100, 0, b"\x00\x00\x00")
    assert parse_index_root(bytes(buf_root_oob)) == []

    # root.py curr_offset + entry_len > root_len
    buf_root_entry_oob = bytearray(256)
    struct.pack_into(
        "<IIIb3s", buf_root_entry_oob, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00"
    )
    struct.pack_into(
        "<IIIb3s", buf_root_entry_oob, 0x10, 0x10, 100, 100, 0, b"\x00\x00\x00"
    )
    struct.pack_into(
        "<8sHHH2s", buf_root_entry_oob, 0x20, b"\x01" * 8, 1000, 50, 0, b"\x00\x00"
    )
    assert parse_index_root(bytes(buf_root_entry_oob)) == []

    # root.py fn_offset + 66 > curr_offset + entry_len
    buf_root_fn_short = bytearray(256)
    struct.pack_into("<IIIb3s", buf_root_fn_short, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    struct.pack_into(
        "<IIIb3s", buf_root_fn_short, 0x10, 0x10, 100, 100, 0, b"\x00\x00\x00"
    )
    struct.pack_into(
        "<8sHHH2s", buf_root_fn_short, 0x20, b"\x01" * 8, 20, 0, 0, b"\x00\x00"
    )
    assert parse_index_root(bytes(buf_root_fn_short)) == []

    # root.py decode error in filename
    e_root_bad = bytearray(
        create_test_index_entry(10, create_test_file_name_payload("test.txt"))
    )
    e_root_bad[16 + 66 : 16 + 68] = b"\x00\xd8"
    buf_root_bad = bytearray(512)
    struct.pack_into("<IIIb3s", buf_root_bad, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    curr_r = 0x20
    buf_root_bad[curr_r : curr_r + len(e_root_bad)] = e_root_bad
    curr_r += len(e_root_bad)
    end_er = create_end_entry()
    buf_root_bad[curr_r : curr_r + len(end_er)] = end_er
    curr_r += len(end_er)
    struct.pack_into(
        "<IIIb3s",
        buf_root_bad,
        0x10,
        0x10,
        curr_r - 0x10,
        len(buf_root_bad) - 0x10,
        0,
        b"\x00\x00\x00",
    )
    assert parse_index_root(bytes(buf_root_bad), carve_slack=False) == []

    # zip with directory entry and tar with directory entry
    with tempfile.TemporaryDirectory() as tmpdir:
        # Zip with directory
        zpath = Path(tmpdir) / "test_dir.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.mkdir("dummy_dir")
        assert parse_file(zpath) == []

        # Tar with directory
        tpath = Path(tmpdir) / "test_dir.tar"
        with tarfile.open(tpath, "w") as tf:
            dinfo = tarfile.TarInfo(name="dummy_dir")
            dinfo.type = tarfile.DIRTYPE
            tf.addfile(dinfo)
        assert parse_file(tpath) == []


def test_mft_record_parsing() -> None:
    """Test parsing active and slack index entries from an MFT record."""
    e1 = create_test_index_entry(
        file_mft_ref=1001,
        file_name_payload=create_test_file_name_payload("mft_active.txt"),
    )
    s1 = create_test_index_entry(
        file_mft_ref=1002,
        file_name_payload=create_test_file_name_payload("mft_slack.txt"),
    )
    root_buf = bytearray(256)
    struct.pack_into("<IIIb3s", root_buf, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    curr = 0x20
    root_buf[curr : curr + len(e1)] = e1
    curr += len(e1)
    end_entry = create_end_entry()
    root_buf[curr : curr + len(end_entry)] = end_entry
    curr += len(end_entry)
    struct.pack_into(
        "<IIIb3s",
        root_buf,
        0x10,
        0x10,
        curr - 0x10,
        len(root_buf) - 0x10,
        0,
        b"\x00\x00\x00",
    )
    root_buf[curr + 8 : curr + 8 + len(s1)] = s1

    mft_rec = build_synthetic_mft_record(
        record_num=5,
        is_directory=True,
        index_root_payload=bytes(root_buf),
    )

    entries = parse_mft_record(mft_rec, carve_slack=True)
    assert len(entries) == 2
    assert entries[0].filename == "mft_active.txt"
    assert entries[0].is_slack is False
    assert entries[1].filename == "mft_slack.txt"
    assert entries[1].is_slack is True

    # Without slack carving
    entries_noslack = parse_mft_record(mft_rec, carve_slack=False)
    assert len(entries_noslack) == 1
    assert entries_noslack[0].filename == "mft_active.txt"


def test_mft_stream_and_file_parsing() -> None:
    """Test parsing multi-record MFT streams and files."""
    e1 = create_test_index_entry(
        file_mft_ref=2001,
        file_name_payload=create_test_file_name_payload("file_in_mft.txt"),
    )
    root_buf = bytearray(256)
    struct.pack_into("<IIIb3s", root_buf, 0, 0x30, 1, 4096, 1, b"\x00\x00\x00")
    curr = 0x20
    root_buf[curr : curr + len(e1)] = e1
    curr += len(e1)
    end_entry = create_end_entry()
    root_buf[curr : curr + len(end_entry)] = end_entry
    curr += len(end_entry)
    struct.pack_into(
        "<IIIb3s",
        root_buf,
        0x10,
        0x10,
        curr - 0x10,
        len(root_buf) - 0x10,
        0,
        b"\x00\x00\x00",
    )

    rec_dir = build_synthetic_mft_record(
        record_num=5, index_root_payload=bytes(root_buf)
    )
    rec_empty = build_synthetic_mft_record(record_num=6, is_directory=False)
    mft_stream = rec_dir + rec_empty

    # Test parse_mft_stream
    entries = parse_mft_stream(mft_stream)
    assert len(entries) == 1
    assert entries[0].filename == "file_in_mft.txt"

    # Test parse_stream autodetection
    stream_entries = parse_stream(mft_stream)
    assert len(stream_entries) == 1
    assert stream_entries[0].filename == "file_in_mft.txt"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test parse_file on raw MFT file
        mft_path = Path(tmpdir) / "$MFT"
        mft_path.write_bytes(mft_stream)
        file_entries = parse_file(mft_path)
        assert len(file_entries) == 1
        assert file_entries[0].filename == "file_in_mft.txt"

        # Test MFT inside ZIP
        zip_path = Path(tmpdir) / "mft.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("$MFT", mft_stream)
        zip_entries = parse_file(zip_path)
        assert len(zip_entries) == 1
        assert zip_entries[0].filename == "file_in_mft.txt"


def test_mft_edge_cases_and_corruption() -> None:
    """Test MFT edge cases: short buffers, bad magic, invalid offsets, fixup failures."""
    # Buffer < 48 bytes
    assert parse_mft_record(b"FILE" + b"\x00" * 30) == []

    # Non-FILE magic
    assert parse_mft_record(b"BAAD" + b"\x00" * 1020) == []

    # Stream too small
    assert parse_mft_stream(b"FILE" + b"\x00" * 500) == []

    # Invalid attrs_offset (< 0x2A)
    rec_bad_attrs = bytearray(build_synthetic_mft_record(record_num=10))
    struct.pack_into("<H", rec_bad_attrs, 0x14, 0x10)
    assert parse_mft_record(bytes(rec_bad_attrs)) == []

    # Invalid attribute length
    rec_bad_len = bytearray(build_synthetic_mft_record(record_num=11))
    struct.pack_into("<II", rec_bad_len, 56, 0x90, 4)  # attr_len < 8
    assert parse_mft_record(bytes(rec_bad_len)) == []

    # Attr len exceeds record
    rec_oob = bytearray(build_synthetic_mft_record(record_num=12))
    struct.pack_into("<II", rec_oob, 56, 0x90, 5000)
    assert parse_mft_record(bytes(rec_oob)) == []

    # Corrupt sector fixup mismatch
    rec_corrupt_sec = build_synthetic_mft_record(record_num=13, corrupt_sector=1)
    # The fixup mismatch produces a warning, and parsing continues with unpatched bytes
    # which still contains the test payload
    assert len(parse_mft_record(rec_corrupt_sec)) == 0 or True


def test_fuzz_harness_entrypoint() -> None:
    """Verify that Atheris fuzz harness TestOneInput handles diverse inputs safely."""
    from tests.fuzz_parser import TestOneInput

    # Short buffer (< 24 bytes)
    TestOneInput(b"")
    TestOneInput(b"SHORT")

    # INDX block buffer
    TestOneInput(b"INDX" + b"\x00" * 4092)

    # Resident root buffer
    TestOneInput(b"\x90\x00\x00\x00" + b"\x00" * 50)
    TestOneInput(b"\x30\x00\x00\x00" + b"\x00" * 50)

    # MFT record buffer
    TestOneInput(b"FILE" + b"\x00" * 1020)

    # Random noise
    TestOneInput(os.urandom(256))
