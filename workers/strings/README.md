# Openrelik worker for running strings on input files

## Installation

Add this to your docker-compose.yml file
```
openrelik-worker-strings:
    container_name: openrelik-worker-strings
    image: ghcr.io/openrelik/openrelik-worker-strings:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
    volumes:
      - /path/to/your/artifacts:/path/to/your/artifacts
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-strings"
```
 ## Test
 ```
uv sync --group test
uv run pytest -s --cov=.
```