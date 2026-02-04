# Use the official Docker Hub Ubuntu base image
FROM ubuntu:24.04

# Prevent needing to configure debian packages, stopping the setup of
# the docker container.
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

# Install poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-poetry \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Configure poetry
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# Set working directory
WORKDIR /openrelik

# Copy files needed to build
COPY . ./

# Install the worker and set environment to use the correct python interpreter.
RUN poetry install && rm -rf $POETRY_CACHE_DIR
ENV VIRTUAL_ENV=/app/.venv PATH="/openrelik/.venv/bin:$PATH"

# ----------------------------------------------------------------------
# Install Capa
# ----------------------------------------------------------------------
# Define a build argument for the Capa version (with a default)
ARG CAPA_VERSION=9.1.0
ENV CAPA_ZIP="capa-v${CAPA_VERSION}-linux.zip"

# Download the specified Capa release using curl
RUN curl -L -o ${CAPA_ZIP} https://github.com/mandiant/capa/releases/download/v${CAPA_VERSION}/${CAPA_ZIP}

# Unzip and clean up
RUN unzip ${CAPA_ZIP} -d /usr/local/bin && rm ${CAPA_ZIP}

# Make Capa executable
RUN chmod 755 /usr/local/bin/capa

# ----------------------------------------------------------------------

# Default command if not run from docker-compose (and command being overridden)
CMD ["celery", "--app=openrelik_worker_capa.tasks", "worker", "--task-events", "--concurrency=1", "--loglevel=INFO"]
