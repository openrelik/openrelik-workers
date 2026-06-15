# OpenRelik Worker for Grep

This repository contains the OpenRelik worker designed to run grep on files to search for patterns.

### Installation

To deploy this worker, add the following service definition to your `docker-compose.yml` file:

```yaml
  openrelik-worker-grep:
    container_name: openrelik-worker-grep
    image: ghcr.io/openrelik/openrelik-worker-grep
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=1 --loglevel=INFO -Q openrelik-worker-grep"
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
