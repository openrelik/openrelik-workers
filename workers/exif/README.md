[![codecov](https://codecov.io/github/openrelik/openrelik-worker-exif/graph/badge.svg?token=cv9CSSeEC3)](https://codecov.io/github/openrelik/openrelik-worker-exif)

# Openrelik worker exif
## Description
The OpenRelik Exif Worker is a Celery-based task processor designed to extract EXIF (Exchangeable Image File Format) metadata from image files. It utilizes the powerful `exiftool` command-line utility to read and parse metadata, making it available for further processing within the OpenRelik ecosystem.

## Deploy


Add the below configuration to the OpenRelik docker-compose.yml file.

```
openrelik-worker-exif:
    container_name: openrelik-worker-exif
    image: ghcr.io/openrelik/openrelik-worker-exif:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-exif"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Configuration

The worker offers task-specific configurations that can be set through the OpenRelik UI when dispatching a task.

*   **Output in JSON format**:
    *   **UI Label**: `Output in JSON format`
    *   **Description**: If checked, ExifTool will output metadata in JSON format. Output files will have a `.json` extension and an `application/json` MIME type. Otherwise, the output will be plain text (`.txt` extension, `text/plain` MIME type).
    *   **Default**: Unchecked (plain text output).


## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
