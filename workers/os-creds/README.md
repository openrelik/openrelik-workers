# Openrelik worker OS Creds Analyzer
## Description
Extracts and brute forces Linux and Windows credentials to identify a likely method of compromise.

## Deploy
Add the below configuration to the OpenRelik docker-compose.yml file.

```
openrelik-worker-os-creds:
    container_name: openrelik-worker-os-creds
    image: ghcr.io/openrelik/openrelik-worker-os-creds:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-os-creds"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```