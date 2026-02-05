[![codecov](https://codecov.io/gh/openrelik/openrelik-worker-analyzer-config/graph/badge.svg?token=IAZK4I612L)](https://codecov.io/gh/openrelik/openrelik-worker-analyzer-config)

# Openrelik worker for analyzing configuration files.

## Supported Configuration Analyzers
* SSH Daemon - artifact:SshConfigFile
* Jupyter Notebook - artifact:JupyterConfigFile
* Jenkins - filename:config.xml
* Redis - artifact:RedisConfigFile
* Tomcat - artifact:TomcatConfigFile

## Installation
Add the below configuration to the OpenRelik `docker-compose.yml` file.

```
openrelik-worker-analyzer-config:
    container_name: openrelik-worker-analyzer-config
    image: ghcr.io/openrelik/openrelik-worker-analyzer-config:${OPENRELIK_WORKER_ANALYZER_CONFIG_VERSION:-latest}
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-analyzer-config"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```