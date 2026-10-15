# Openrelik worker: Export to Splunk

Uploads JSONL events from OpenRelik workflows to Splunk Cloud via the HTTP Event
Collector (HEC). Supports both the `/services/collector/event` and
`/services/collector/raw` endpoints.

## Configuration

Secrets are supplied as environment variables on the worker container:

- `SPLUNK_HEC_URL` — base URL of the HEC endpoint, e.g.
  `https://http-inputs-example.splunkcloud.com`
- `SPLUNK_HEC_TOKEN` — HEC token
- `SPLUNK_HEC_VERIFY_TLS` — `true` (default) or `false`

Per-run options are set via `task_config`:

- `index` (required) — target Splunk index
- `sourcetype` — Splunk sourcetype (default `_json`)
- `host` — host override; falls back to the input filename stem
- `source` — source override; falls back to the input `display_name`
- `hec_endpoint` — `raw` (default) or `event`

## Input

Accepts `*.jsonl` files produced by upstream OpenRelik tasks. Each line is sent
as one event.
