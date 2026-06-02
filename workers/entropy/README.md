# Openrelik worker entropy
## Description

This worker calculates entropy of every file provided, as well as generate
a summary containing files with a high entropy (> 7 bits of entropy per byte).

## Deploy
Add the below configuration to the OpenRelik docker-compose.yml file.

```
openrelik-worker-entropy:
    container_name: openrelik-worker-entropy
    image: ghcr.io/openrelik/openrelik-worker-entropy:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-entropy"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
