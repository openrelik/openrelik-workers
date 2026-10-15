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

"""Tests for the s3_uploader helper module."""

import gzip
import os

import boto3
import pytest
from moto import mock_aws

from src import s3_uploader


def _write(path: str, data: bytes) -> str:
    with open(path, "wb") as f:
        f.write(data)
    return path


def test_compress_gzip_roundtrip(tmp_path):
    src = _write(str(tmp_path / "input.bin"), b"hello world\n" * 1024)
    gz_path = s3_uploader.compress_gzip(src)
    try:
        assert os.path.isfile(gz_path)
        assert gz_path.endswith(".gz")
        with gzip.open(gz_path, "rb") as f:
            assert f.read() == b"hello world\n" * 1024
    finally:
        os.unlink(gz_path)


def test_compress_gzip_cleanup_on_error(tmp_path, monkeypatch):
    """If gzip writing fails, the temp file must not be left behind."""
    captured: dict[str, str] = {}
    real_mkstemp = s3_uploader.tempfile.mkstemp

    def spy(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        captured["path"] = path
        return fd, path

    monkeypatch.setattr(s3_uploader.tempfile, "mkstemp", spy)
    monkeypatch.setattr(
        s3_uploader.shutil, "copyfileobj",
        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")),
    )

    src = _write(str(tmp_path / "input.bin"), b"x")
    with pytest.raises(OSError, match="boom"):
        s3_uploader.compress_gzip(src)
    assert not os.path.exists(captured["path"])


@mock_aws
def test_upload_file_returns_size(tmp_path):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    payload = b"x" * (5 * 1024 * 1024)  # 5 MiB triggers boto3's chunked path
    src = _write(str(tmp_path / "blob.bin"), payload)

    size = s3_uploader.upload_file(s3, src, "test-bucket", "blob.bin")
    assert size == len(payload)
    body = s3.get_object(Bucket="test-bucket", Key="blob.bin")["Body"].read()
    assert body == payload


@mock_aws
def test_upload_file_small(tmp_path):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    src = _write(str(tmp_path / "tiny.bin"), b"hi")

    size = s3_uploader.upload_file(s3, src, "test-bucket", "tiny.bin")
    assert size == 2
    body = s3.get_object(Bucket="test-bucket", Key="tiny.bin")["Body"].read()
    assert body == b"hi"
