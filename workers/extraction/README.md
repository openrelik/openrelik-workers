## Openrelik worker for running image_extract on input files to extract forensic artifacts

### Installation
Add the below configuration to the OpenRelik `docker-compose.yml` file.

```
openrelik-worker-extraction:
    container_name: openrelik-worker-extraction
    image: ghcr.io/openrelik/openrelik-worker-extraction:${OPENRELIK_WORKER_ARTIFACT_EXTRACTION_VERSION:-latest}
    privileged: true
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
      - /dev:/dev
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-extraction"
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```