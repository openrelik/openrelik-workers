# Use the official Docker Hub Ubuntu base image
FROM --platform=linux/amd64 ubuntu:24.04 AS ubuntu_2404_amd64

ARG PPA_TRACK=stable

# Prevent needing to configure debian packages, stopping the setup of
# the docker container.
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    python3-pip \
    python3-poetry \
    wget \
    sudo \
    fdisk \
    qemu-utils \
    ntfs-3g \
  && rm -rf /var/lib/apt/lists/*

# Install latest release of container explorer
COPY ./setup.sh ./setup.sh
RUN chmod +x ./setup.sh
RUN ./setup.sh install

# Configure debugging
ARG OPENRELIK_PYDEBUG
ENV OPENRELIK_PYDEBUG=${OPENRELIK_PYDEBUG:-0}
ARG OPENRELIK_PYDEBUG_PORT
ENV OPENRELIK_PYDEBUG_PORT=${OPENRELIK_PYDEBUG_PORT:-5678}

# Set working directory
WORKDIR /openrelik

# Install the latest uv binaries
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy poetry toml and uv.lock
COPY uv.lock pyproject.toml ./

# Install the project's dependencies using the lockfile and settings
RUN uv sync --locked --no-install-project --no-dev

# Copy all worker files
COPY . ./

# Installing separately from its dependencies allows optimal layer caching
RUN uv sync --locked --no-dev

# Set PATH to use the virtual environment
ENV PATH="/openrelik/.venv/bin:$PATH"

# Default command if not run from docker-compose (and command being overidden)
CMD ["celery", "--app=src.tasks", "worker", "--task-events", "--concurrency=1", "--loglevel=INFO"]
