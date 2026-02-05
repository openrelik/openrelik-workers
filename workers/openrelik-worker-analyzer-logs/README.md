[![codecov](https://codecov.io/github/openrelik/openrelik-worker-analyzer-logs/graph/badge.svg?token=U1OAOQSX7K)](https://codecov.io/github/openrelik/openrelik-worker-analyzer-logs)

# Openrelik worker for analyzing logs
OpenRelik Logs Analyzer worker is responsible for log analysis. Tasks that read (multiple) logs can be added to this worker.

## Features
- Bruteforce SSH authentication event detection (taskname: ssh_analyzer)
   - Analyze auth logs and detect bruteforce login attempts.

## Installation
Add the below configuration to the OpenRelik `docker-compose.yml` file.

```
  openrelik-worker-analyzer-logs:
      container_name: openrelik-worker-analyzer-logs
      image: ghcr.io/openrelik/openrelik-worker-analyzer-logs:$OPENRELIK_WORKER_ANALYZER_LOGS_VERSION
      restart: always
      environment:
        - REDIS_URL=redis://openrelik-redis:6379
      volumes:
        - ./data:/usr/share/openrelik/data
      command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-analyzer-logs"
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
