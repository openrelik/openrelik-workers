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

"""End-to-end tests for the export-s3 worker task."""

import base64
import gzip
import json
import os

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src import s3_uploader, tasks


def _decode(result: str) -> dict:
    return json.loads(base64.b64decode(result.encode("utf-8")).decode("utf-8"))


def _make_input(
    tmp_path,
    name: str,
    body: bytes,
    display_name: str = None,
    original_path: str = None,
) -> dict:
    path = str(tmp_path / name)
    with open(path, "wb") as f:
        f.write(body)
    return {
        "path": path,
        "display_name": display_name or name,
        "original_path": original_path,
    }


def _create_bucket(name: str = "test-bucket") -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=name)


@pytest.fixture(autouse=True)
def _aws_region(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_S3_ENDPOINT_URL", raising=False)


@mock_aws
def test_upload_none_happy_path(tmp_path):
    _create_bucket()
    inputs = [_make_input(tmp_path, "evidence.txt", b"clean data")]

    raw = tasks.upload(
        pipe_result=None,
        input_files=inputs,
        output_path=str(tmp_path),
        workflow_id="wf-1",
        task_config={"s3_bucket": "test-bucket", "s3_prefix": "case-1"},
    )

    result = _decode(raw)
    assert result["meta"]["uploaded_count"] == 1
    assert result["meta"]["failed_count"] == 0
    assert result["meta"]["uploaded_objects"][0]["key"] == "case-1/evidence.txt"

    s3 = boto3.client("s3", region_name="us-east-1")
    body = s3.get_object(Bucket="test-bucket", Key="case-1/evidence.txt")["Body"].read()
    assert body == b"clean data"


@mock_aws
def test_upload_gzip_appends_gz_suffix(tmp_path):
    _create_bucket()
    inputs = [_make_input(tmp_path, "log.json", b'{"a": 1}\n')]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-2",
        task_config={"s3_bucket": "test-bucket", "compression": "gzip"},
    )
    result = _decode(raw)
    assert result["meta"]["uploaded_objects"][0]["key"] == "log.json.gz"

    s3 = boto3.client("s3", region_name="us-east-1")
    body = s3.get_object(Bucket="test-bucket", Key="log.json.gz")["Body"].read()
    assert gzip.decompress(body) == b'{"a": 1}\n'


@mock_aws
def test_upload_gzip_uses_original_path_basename(tmp_path):
    """When original_path is set, the S3 key should be its basename + .gz —
    not the (possibly mangled) intermediate display_name."""
    _create_bucket()
    inputs = [
        _make_input(
            tmp_path,
            "abc123.plaso",
            b"derived",
            display_name="abc123.plaso",
            original_path="/uploads/2026/evidence.E01",
        )
    ]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-orig",
        task_config={"s3_bucket": "test-bucket", "compression": "gzip"},
    )
    result = _decode(raw)
    assert result["meta"]["uploaded_objects"][0]["key"] == "evidence.E01.gz"

    s3 = boto3.client("s3", region_name="us-east-1")
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket").get("Contents", [])]
    assert keys == ["evidence.E01.gz"]


@mock_aws
def test_object_name_pattern_basename_with_extension(tmp_path):
    """An object_name pattern + export_basename names the key after the source
    artifact, keeping the uploaded file's own extension."""
    _create_bucket()
    inputs = [
        _make_input(
            tmp_path,
            "deadbeef.plaso.csv",
            b"timeline",
            display_name="deadbeef.plaso.csv",
            original_path="/derived/deadbeef.plaso.csv",
        )
    ]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-name",
        task_config={
            "s3_bucket": "test-bucket",
            "s3_prefix": "case-1",
            "object_name": "{basename}",
            "export_basename": "evidence",
        },
    )
    result = _decode(raw)
    assert result["meta"]["uploaded_objects"][0]["key"] == "case-1/evidence.csv"

    s3 = boto3.client("s3", region_name="us-east-1")
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket").get("Contents", [])]
    assert keys == ["case-1/evidence.csv"]


@mock_aws
def test_object_name_pattern_with_slice_distinguisher(tmp_path):
    """A pattern that wraps {basename} keeps multiple export tasks from
    colliding — the distinguisher lives in the template, not the importer."""
    _create_bucket()
    inputs = [_make_input(tmp_path, "uuid.csv", b"slice", display_name="uuid.csv")]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-slice",
        task_config={
            "s3_bucket": "test-bucket",
            "object_name": "{basename}_2024-01",
            "export_basename": "evidence",
        },
    )
    result = _decode(raw)
    assert result["meta"]["uploaded_objects"][0]["key"] == "evidence_2024-01.csv"


@mock_aws
def test_object_name_pattern_without_basename_value_falls_back(tmp_path):
    """A pattern referencing {basename} with no export_basename provided falls
    back to the upstream name rather than emitting a literal '{basename}'."""
    _create_bucket()
    inputs = [
        _make_input(
            tmp_path,
            "uuid.csv",
            b"x",
            display_name="uuid.csv",
            original_path="/derived/uuid.csv",
        )
    ]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-noval",
        task_config={"s3_bucket": "test-bucket", "object_name": "{basename}"},
    )
    result = _decode(raw)
    assert result["meta"]["uploaded_objects"][0]["key"] == "uuid.csv"


@mock_aws
def test_object_name_pattern_applies_before_gzip_suffix(tmp_path):
    """With gzip, the resolved object name still gets the .gz suffix."""
    _create_bucket()
    inputs = [_make_input(tmp_path, "uuid.csv", b"x", display_name="uuid.csv")]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-gznm",
        task_config={
            "s3_bucket": "test-bucket",
            "compression": "gzip",
            "object_name": "{basename}",
            "export_basename": "evidence",
        },
    )
    result = _decode(raw)
    assert result["meta"]["uploaded_objects"][0]["key"] == "evidence.csv.gz"


@mock_aws
def test_upload_no_inputs_returns_warning(tmp_path):
    _create_bucket()
    raw = tasks.upload(
        input_files=[], workflow_id="wf-empty", task_config={"s3_bucket": "test-bucket"}
    )
    result = _decode(raw)
    assert "warnings" in result["meta"]


def test_upload_missing_bucket_raises(tmp_path):
    inputs = [_make_input(tmp_path, "x.bin", b"x")]
    with pytest.raises(ValueError, match="s3_bucket"):
        tasks.upload(input_files=inputs, workflow_id="wf-x", task_config={})


def test_upload_invalid_compression_raises(tmp_path):
    inputs = [_make_input(tmp_path, "x.bin", b"x")]
    with pytest.raises(ValueError, match="compression"):
        tasks.upload(
            input_files=inputs,
            workflow_id="wf-x",
            task_config={"s3_bucket": "b", "compression": "zip"},
        )


def test_upload_no_aws_region_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    inputs = [_make_input(tmp_path, "x.bin", b"x")]
    with pytest.raises(RuntimeError, match="AWS_REGION"):
        tasks.upload(
            input_files=inputs,
            workflow_id="wf-x",
            task_config={"s3_bucket": "b"},
        )


@mock_aws
def test_upload_sanitizes_path_traversal_in_display_name(tmp_path):
    _create_bucket()
    inputs = [_make_input(tmp_path, "ondisk.bin", b"payload",
                          display_name="../escape.txt")]

    raw = tasks.upload(
        input_files=inputs,
        workflow_id="wf-trav",
        task_config={"s3_bucket": "test-bucket", "s3_prefix": "case-1/"},
    )
    result = _decode(raw)
    # `..` segment dropped → ends up directly under the prefix.
    assert result["meta"]["uploaded_objects"][0]["key"] == "case-1/escape.txt"
    assert result["meta"]["prefix"] == "case-1"

    s3 = boto3.client("s3", region_name="us-east-1")
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket").get("Contents", [])]
    assert keys == ["case-1/escape.txt"]


@mock_aws
def test_upload_drops_useless_display_name(tmp_path):
    """A display_name of `..` reduces to empty after sanitization → skipped."""
    _create_bucket()
    inputs = [_make_input(tmp_path, "ondisk.bin", b"payload", display_name="..")]

    with pytest.raises(RuntimeError, match="failure"):
        tasks.upload(
            input_files=inputs,
            workflow_id="wf-drop",
            task_config={"s3_bucket": "test-bucket"},
        )


@mock_aws
def test_upload_partial_failure_continues_and_raises(tmp_path, monkeypatch):
    _create_bucket()
    inputs = [
        _make_input(tmp_path, "good1.bin", b"one"),
        _make_input(tmp_path, "bad.bin", b"two"),
        _make_input(tmp_path, "good2.bin", b"three"),
    ]

    real_upload = s3_uploader.upload_file

    def flaky(client, local_path, bucket, key):
        if "bad.bin" in key:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "PutObject"
            )
        return real_upload(client, local_path, bucket, key)

    monkeypatch.setattr("src.tasks.upload_file", flaky)

    with pytest.raises(RuntimeError, match="1 failure"):
        tasks.upload(
            input_files=inputs,
            workflow_id="wf-partial",
            task_config={"s3_bucket": "test-bucket"},
        )

    # Files 1 and 3 still landed in S3.
    s3 = boto3.client("s3", region_name="us-east-1")
    keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket").get("Contents", []))
    assert keys == ["good1.bin", "good2.bin"]


@mock_aws
def test_upload_emits_per_file_and_done_events(tmp_path, monkeypatch):
    """Per-file 'Uploading' event and a final 'Done' event are emitted from
    the main task thread (no boto3-thread callbacks)."""
    _create_bucket()
    inputs = [_make_input(tmp_path, "blob.bin", b"x" * 1024)]

    events: list[dict] = []
    monkeypatch.setattr(
        tasks.upload, "send_event", lambda *a, **kw: events.append(kw.get("data", {})),
        raising=False,
    )

    tasks.upload(
        input_files=inputs,
        workflow_id="wf-prog",
        task_config={"s3_bucket": "test-bucket"},
    )

    statuses = [e.get("status") for e in events]
    assert "Uploading to S3" in statuses
    assert statuses[-1] == "Done"
