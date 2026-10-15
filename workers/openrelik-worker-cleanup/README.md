# Openrelik worker: Cleanup intermediate files

Reclaims disk space at the end of a workflow by deleting the intermediate files
its tasks left behind. It is designed to run **last**, as the `callback` of a
Celery chord, so it only fires after every other task in the chord has
succeeded.

The task walks the workflow's output folder (`output_path`) and deletes every
file except those matching a set of keep patterns (default: `*.log`). It does
**not** consult the database or the API — deletion is a pure filesystem walk, so
the worker needs no credentials.

## Why a folder walk (and not the piped file list)

A Celery chain only forwards each task's *own* output files to the next task, so
by the time the final callback runs, the file lists from earlier tasks
(extraction, Plaso, …) are long gone from the pipe — the callback only sees the
immediately-preceding tasks' (often empty) output. Walking `output_path`
directly is what lets cleanup see everything the workflow produced.

This is safe because cleanup is the **terminal node**: every other task has
already run and consumed the files it needed before the callback fires (a chord
callback runs only after all header tasks succeed). There is nothing left
downstream to read the files.

## ⚠️ Important assumption

This worker deletes by **location and name**, not by database state. Registered
files (`register_in_db=True`) physically live in the *same* `output_path` folder
as intermediate files and are indistinguishable on disk. **If your workflow
produces registered outputs, they will be deleted too** (unless they match a
keep pattern), leaving orphaned database rows.

Use this worker only when the workflow's retained results are either:

- exported elsewhere (e.g. to S3 or Splunk) so the local copies are disposable, or
- matched by `keep_patterns` so they are preserved.

The intended setup is a workflow whose data-producing tasks all set
`register_in_db=false` and whose results are shipped out by export tasks before
cleanup runs.

## Configuration

This worker takes no environment variables beyond `REDIS_URL`. It reads files
from the shared OpenRelik data volume.

Per-run options are set via `task_config`:

- `keep_patterns` — comma-separated glob patterns matched against each file's
  name. Matching files are preserved; everything else under `output_path` is
  deleted. Defaults to `*.log`. Example: `*.log, *.json`.
- `dry_run` (default `false`) — log and report the files that *would* be deleted
  without removing anything. Useful for verifying selection first.
- `remove_empty_dirs` (default `false`) — after deleting files, remove any empty
  subdirectories left under `output_path`. The output folder itself is never
  removed.

## Output

This worker emits no OpenRelik output files. The task result `meta` includes:

- `dry_run`, `keep_patterns`, `output_path`
- `scanned_count` — files seen during the walk
- `kept_count` — files preserved by a keep pattern
- `deleted_count`, `freed_bytes`
- `failed_paths` — files that could not be removed (logged, not raised)
- `removed_empty_dirs`

Per-file deletion failures are logged and reported in `meta` but never raised:
as a chord callback, raising would fail the entire workflow over a best-effort
cleanup.

## Wiring as a chord callback

In the workflow spec, set the chord's `callback` to this task:

```json
"callback": {
  "type": "task",
  "task_name": "openrelik-worker-cleanup.tasks.cleanup",
  "queue_name": "openrelik-worker-cleanup",
  "tasks": [],
  "task_config": [ { "name": "dry_run", "value": false } ]
}
```

`task_name` must equal the worker's `TASK_NAME`, and `queue_name` must match the
`-Q openrelik-worker-cleanup` queue the worker consumes.

## Known limitations

- If a header task fails, the chord callback does not fire by default, so a
  failed run's intermediate files are not cleaned up.
- Cleanup must be the **terminal** task. Placing it mid-workflow would delete
  files that later tasks still need.
