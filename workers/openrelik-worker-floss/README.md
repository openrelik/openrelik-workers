[![codecov](https://codecov.io/github/openrelik/openrelik-worker-floss/graph/badge.svg?token=riFvCijyWc)](https://codecov.io/github/openrelik/openrelik-worker-floss)

# Openrelik worker FLOSS
## Description
Run FLARE's FLOSS string finder on supported file types.

## Deploy
Add the below configuration to the OpenRelik docker-compose.yml file.

```
openrelik-worker-floss:
    container_name: openrelik-worker-floss
    image: ghcr.io/openrelik/openrelik-worker-floss:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-floss"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Test
```
pip install poetry
poetry install --with test --no-root
poetry run pytest --cov=. -v
```
