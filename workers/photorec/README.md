Notice (March 2026): This worker is WIP!!


# OpenRelik PhotoRec Worker

This OpenRelik worker utilizes [PhotoRec](https://www.cgsecurity.org/wiki/PhotoRec) to perform file carving and data recovery from various input sources, typically disk images. It aims to recover deleted files or files from corrupted file systems.

### Installation

To deploy this worker, add the following service definition to your `docker-compose.yml` file:

```yaml
  openrelik-worker-photorec:
    container_name: openrelik-worker-photorec
    image: ghcr.io/openrelik/openrelik-worker-photorec
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.tasks worker --task-events --concurrency=1 --loglevel=INFO -Q openrelik-worker-photorec"
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
