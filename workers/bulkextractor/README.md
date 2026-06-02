# OpenRelik Worker for BulkExtractor

This repository contains the OpenRelik worker designed to interact with [BulkExtractor](https://github.com/simsong/bulk_extractor). It processes files using BulkExtractor to identify and extract various types of information.

## Features

*   Integrates BulkExtractor into the OpenRelik processing pipeline.
*   Consumes tasks from a Redis queue.
*   Stores processed results.

## Prerequisites

*   Docker
*   Docker Compose
*   An accessible Redis instance.

### Installation

To deploy this worker, add the following service definition to your `docker-compose.yml` file:

```yaml
  openrelik-worker-bulkextractor:
    container_name: openrelik-worker-bulkextractor
    image: ghcr.io/openrelik/openrelik-worker-bulkextractor
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=1 --loglevel=INFO -Q openrelik-worker-bulkextractor"
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
