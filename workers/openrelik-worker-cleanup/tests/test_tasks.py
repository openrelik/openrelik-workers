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

"""End-to-end tests for the cleanup worker task."""

import base64
import json
import os

from src import tasks


def _decode(result: str) -> dict:
    return json.loads(base64.b64decode(result.encode("utf-8")).decode("utf-8"))


def _write(path, body=b"x"):
    """Create a file (and any missing parent dirs) with the given content."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(body)
    return path


def _run(output_path, task_config=None):
    return _decode(
        tasks.cleanup(
            pipe_result=None,
            input_files=[],
            output_path=str(output_path) if output_path is not None else None,
            workflow_id="wf-test",
            task_config=task_config or {},
        )
    )


def test_deletes_non_log_files(tmp_path):
    """Every file is deleted except *.log (the default keep pattern)."""
    data = _write(str(tmp_path / "abc123.plaso"))
    extracted = _write(str(tmp_path / "def456.evtx"))
    log = _write(str(tmp_path / "extract_archives_archive.zip.log"))

    meta = _run(tmp_path)["meta"]

    assert meta["scanned_count"] == 3
    assert meta["deleted_count"] == 2
    assert meta["kept_count"] == 1
    assert not os.path.exists(data)
    assert not os.path.exists(extracted)
    assert os.path.exists(log)  # *.log preserved


def test_freed_bytes_sums_deleted_only(tmp_path):
    """freed_bytes counts deleted files, not kept ones."""
    _write(str(tmp_path / "a.bin"), body=b"12345")  # 5 bytes, deleted
    _write(str(tmp_path / "keep.log"), body=b"9" * 100)  # kept

    meta = _run(tmp_path)["meta"]

    assert meta["deleted_count"] == 1
    assert meta["freed_bytes"] == 5


def test_recurses_into_subdirectories(tmp_path):
    """Files in nested subdirectories are deleted too."""
    nested = _write(str(tmp_path / "sub" / "deep" / "scratch.tmp"))
    top = _write(str(tmp_path / "top.bin"))

    meta = _run(tmp_path)["meta"]

    assert meta["deleted_count"] == 2
    assert not os.path.exists(nested)
    assert not os.path.exists(top)


def test_custom_keep_patterns(tmp_path):
    """keep_patterns overrides the default and accepts multiple globs."""
    log = _write(str(tmp_path / "task.log"))
    report = _write(str(tmp_path / "report.json"))
    data = _write(str(tmp_path / "data.plaso"))

    meta = _run(tmp_path, task_config={"keep_patterns": "*.json, *.plaso"})["meta"]

    # With a custom pattern, *.log is no longer kept.
    assert not os.path.exists(log)
    assert os.path.exists(report)
    assert os.path.exists(data)
    assert meta["deleted_count"] == 1
    assert meta["kept_count"] == 2


def test_empty_keep_patterns_falls_back_to_default(tmp_path):
    """A blank keep_patterns string falls back to the *.log default."""
    log = _write(str(tmp_path / "task.log"))
    data = _write(str(tmp_path / "data.bin"))

    meta = _run(tmp_path, task_config={"keep_patterns": "  ,  "})["meta"]

    assert meta["keep_patterns"] == ["*.log"]
    assert os.path.exists(log)
    assert not os.path.exists(data)


def test_dry_run_deletes_nothing(tmp_path):
    """dry_run reports what would be deleted but leaves files on disk."""
    data = _write(str(tmp_path / "data.bin"))

    meta = _run(tmp_path, task_config={"dry_run": True})["meta"]

    assert meta["dry_run"] is True
    assert meta["deleted_count"] == 1
    assert meta["freed_bytes"] == 1
    assert os.path.exists(data)


def test_remove_empty_dirs(tmp_path):
    """Opt-in pruning removes subdirs emptied by deletion, not output_path."""
    nested = _write(str(tmp_path / "sub" / "scratch.tmp"))

    meta = _run(tmp_path, task_config={"remove_empty_dirs": True})["meta"]

    assert meta["deleted_count"] == 1
    assert meta["removed_empty_dirs"] == 1
    assert not os.path.exists(nested)
    assert not (tmp_path / "sub").exists()
    assert tmp_path.exists()  # the workflow folder itself is preserved


def test_remove_empty_dirs_keeps_nonempty(tmp_path):
    """A subdir still holding a kept file is not removed."""
    _write(str(tmp_path / "sub" / "keep.log"))
    _write(str(tmp_path / "sub" / "scratch.tmp"))

    meta = _run(tmp_path, task_config={"remove_empty_dirs": True})["meta"]

    assert meta["deleted_count"] == 1
    assert meta["removed_empty_dirs"] == 0
    assert (tmp_path / "sub").exists()
    assert (tmp_path / "sub" / "keep.log").exists()


def test_missing_output_path_refuses(tmp_path):
    """A non-existent output_path is a safe no-op with an error in meta."""
    missing = tmp_path / "does-not-exist"

    meta = _run(missing)["meta"]

    assert meta["deleted_count"] == 0
    assert "error" in meta


def test_none_output_path_refuses(tmp_path):
    """output_path=None deletes nothing and reports an error."""
    meta = _run(None)["meta"]

    assert meta["deleted_count"] == 0
    assert "error" in meta


def test_empty_folder_is_clean_noop(tmp_path):
    """An empty output folder scans nothing and deletes nothing."""
    meta = _run(tmp_path)["meta"]

    assert meta["scanned_count"] == 0
    assert meta["deleted_count"] == 0
    assert meta["kept_count"] == 0


def test_symlink_target_outside_is_not_followed(tmp_path):
    """Deleting a symlink removes the link, never the out-of-tree target."""
    outside_dir = tmp_path.parent / "outside"
    outside_dir.mkdir()
    target = outside_dir / "target.txt"
    target.write_bytes(b"keep me")

    link = tmp_path / "link.bin"
    os.symlink(str(target), str(link))

    meta = _run(tmp_path)["meta"]

    assert meta["deleted_count"] == 1
    assert not os.path.lexists(link)  # the link is gone
    assert target.exists()  # the real file outside the folder survives
