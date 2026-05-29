[![codecov](https://codecov.io/github/openrelik/openrelik-worker-capa/graph/badge.svg?token=mcoWTDgnQz)](https://codecov.io/github/openrelik/openrelik-worker-capa)

# OpenRelik Worker: capa

## Description

This OpenRelik worker utilizes **capa** to identify capabilities in executable files.

**What is capa?**

Capa is an open-source tool developed by Mandiant (formerly FireEye) that detects capabilities in executable files. You run it against a PE file, ELF, shellcode, or .NET module, and it tells you what it thinks the program can do. For example, it might suggest that the file is a backdoor, can install services, or relies on HTTP to communicate. For more details, visit the [official capa repository](https://github.com/mandiant/capa).

## Deploy

To deploy this worker, add the following service configuration to your OpenRelik `docker-compose.yml` file:

```yaml
openrelik-worker-capa:
    container_name: openrelik-worker-capa
    image: ghcr.io/openrelik/openrelik-worker-capa:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0 # Set to 1 for debugpy remote debugging
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-capa"
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
