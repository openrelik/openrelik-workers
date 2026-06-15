# OpenRelik worker for analysing files with an LLM

This worker supports the LLM providers defined in openrelik-ai-common. This worker will take any files it can read as UTF-8 and run a prompt on it. You prompt can reference the file contents explicitly by mentioning `$file`.

You can also specify the optional `LLM_MAX_INPUT_TOKENS` to truncate the prompt.

You can emable this worker by adding this to your docker-compose.yml:

```
  openrelik-worker-llm:
    container_name: openrelik-worker-llm
    build:
      context: ./openrelik-worker-llm
      dockerfile: Dockerfile
    restart: always
    environment:
      - OPENRELIK_PYDEBUG=1
      - OPENRELIK_PYDEBUG_PORT=5678
      - REDIS_URL=redis://openrelik-redis:6379
      - OLLAMA_SERVER_URL=http://openrelik-ollama:11434
      - OLLAMA_DEFAULT_MODEL=llama3
      - LLM_MAX_INPUT_TOKENS=1000000
    ports:
      - 5678:5678
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-llm"
```

If you're using Ollama then you can tack on a container exposing TCP/11434 ie.

```
  openrelik-ollama:
    container_name: ollama
    image: ollama/ollama:latest
    ports:
      - 11434:11434
```

You will also need to load the llama3 model in the Ollama server instance ie.

```
docker compose exec openrelik-ollama /bin/bash
root@04456c12e6e8:/# ollama run llama3
pulling manifest
...
verifying sha256 digest
writing manifest
success
```

## Test
```
uv sync --group test
uv run pytest -s --cov=.
```
