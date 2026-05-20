# Openrelik worker: Export to S3

Exports input files from OpenRelik workflows to Amazon S3 (or any S3-compatible
endpoint such as MinIO, Cloudflare R2, or DigitalOcean Spaces). Optionally
gzips each file or bundles all inputs into a single tar.gz archive before
upload.

## Configuration

The destination region is supplied as an environment variable on the worker
container:

- `AWS_REGION` (required) — AWS region (e.g. `us-east-1`)
- `AWS_S3_ENDPOINT_URL` (optional) — S3-compatible endpoint URL (e.g.
  `http://minio:9000`). Leave unset for real AWS.

AWS credentials are resolved by boto3's default credential chain. Any one of
the following works:

- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` env vars (static keys)
- IAM role on the EC2 / EKS / ECS task running the worker
- AWS SSO or a shared credentials file (`AWS_PROFILE`)

If none are available the first S3 call fails with a `NoCredentialsError`,
which the task surfaces as a `RuntimeError`.

Per-run options are set via `task_config`:

- `s3_bucket` (required) — destination bucket name (without `s3://`)
- `s3_prefix` — optional key prefix (folder); leading/trailing slashes are
  stripped, and `..` / `.` path components are dropped
- `compression` — one of:
  - `none` (default) — upload each file as-is
  - `gzip` — gzip each file individually, uploaded as `<display_name>.gz`
  - `tar.gz` — bundle all inputs into a single
    `<workflow_id>.tar.gz` archive and upload that

Note: `s3_prefix` and per-file display names are sanitized — leading/trailing
slashes, `..`, `.`, and NUL bytes are stripped to prevent S3 key injection
and prefix escape.

## Input

Accepts any input files. Per-file uploads use the file's `display_name` as
the S3 object name. The `tar.gz` mode preserves each entry's `display_name`
inside the archive.

## Output

This worker emits no OpenRelik output files. The S3 object(s) are the
artifact. The task result `meta` includes:

- `bucket`, `prefix`, `compression`, `endpoint_url`
- `uploaded_count`, `uploaded_bytes`
- `uploaded_objects` — list of `{display_name, key, size, [bundled_files]}`
- `failed_count`, `failed_objects` — populated on partial failure

On partial failure (some files uploaded, others did not) the task continues
through the full input list, then logs the full `meta` (including
`failed_objects`) and raises `RuntimeError`. Operators can recover the
list of successful and failed keys from the worker logs.
