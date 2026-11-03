# Openrelik worker INDX
## Description
OpenRelik worker for processing NTFS directory index ($I30 / INDX) files.

## Deploy
Add the below configuration to the OpenRelik docker-compose.yml file.

```
openrelik-worker-indx:
    container_name: openrelik-worker-indx
    image: ghcr.io/openrelik/openrelik-worker-indx:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-indx"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
