# OpenRelik Worker - Hasher

## Description

The **OpenRelik Hasher Worker** is a Celery-based task processor designed to calculate various types of hashes for files. These hashes are used to identify, deduplicate, or find similar files during digital forensic investigations.

## Features

### SSDeep Hash Calculation
Calculates SSDeep (Context-Triggered Piecewise Hashes) for files. SSDeep is a fuzzy hashing algorithm used to identify similar files, even if they have minor modifications.

**Key Functionalities:**
*   Accepts one or more input files.
*   For each input file, it executes the `ssdeep` command-line tool.
*   Generates an output file (e.g., `original_filename.ssdeep`) for each input, containing the calculated SSDeep hash. If a file is too small for SSDeep or an error occurs, the output file will contain a relevant notice or error message.

## Deploy
Add the below configuration to the OpenRelik docker-compose.yml file.

```yaml
openrelik-worker-hasher:
    container_name: openrelik-worker-hasher
    image: ghcr.io/openrelik/openrelik-worker-hasher:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-hasher"
    # ports:
      # - 5678:5678 # For debugging purposes.
```

## Local Development
If you want to run the worker from source for development, use the following configuration in your docker-compose.yml:

```yaml
openrelik-worker-hasher:
    container_name: openrelik-worker-hasher
    image: openrelik-worker-hasher
    build: ../openrelik-worker-hasher
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-hasher"
```

## Example results

ssdeep_results.md
```
# SSDeep Hash Results

| Filename | SSDeep Hash |
| --- | --- |
| sample-1.eml | ssdeep,1.1--blocksize:hash:hash,filename
192:4v96wuGv7ugYcXerGF3T5r9kfnWPOrzuynp3gag9ip9dFswHCy/9pRgmsZi5TgqP:4v9HjkiqGFrsWGnDQp9O5lpRm4pZabi |
```

ssdeep_results.json:
```
[
    {
        "filename": "sample-1.eml",
        "ssdeep": "ssdeep,1.1--blocksize:hash:hash,filename\n192:4v96wuGv7ugYcXerGF3T5r9kfnWPOrzuynp3gag9ip9dFswHCy/9pRgmsZi5TgqP:4v9HjkiqGFrsWGnDQp9O5lpRm4pZabi"
    }
]
```

## Test
```bash
uv sync
uv run pytest --cov=. -v
```

