# Use the official Docker Hub Ubuntu base image
FROM ubuntu:24.04

# Prevent needing to configure debian packages, stopping the setup of
# the docker container.
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

# Install poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------
# Install Capa
# ----------------------------------------------------------------------
# Define a build argument for the Capa version (with a default)
ARG CAPA_VERSION=9.3.1
ENV CAPA_ZIP="capa-v${CAPA_VERSION}-linux.zip"

# Download the specified Capa release using curl
RUN curl -L -o ${CAPA_ZIP} https://github.com/mandiant/capa/releases/download/v${CAPA_VERSION}/${CAPA_ZIP}

# Unzip and clean up
RUN unzip ${CAPA_ZIP} -d /usr/local/bin && rm ${CAPA_ZIP}

# Make Capa executable
RUN chmod 755 /usr/local/bin/capa

# Set working directory
WORKDIR /openrelik

# Install the latest uv binaries
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy poetry toml and uv.lock
COPY uv.lock pyproject.toml ./

# Install the project's dependencies using the lockfile and settings
RUN uv sync --locked --no-install-project --no-dev

# Copy files needed to build
COPY . ./

# Installing separately from its dependencies allows optimal layer caching
RUN uv sync --locked --no-dev

# Set PATH to use the virtual environment
ENV PATH="/openrelik/.venv/bin:$PATH"

# Default command if not run from docker-compose (and command being overridden)
CMD ["celery", "--app=openrelik_worker_capa.tasks", "worker", "--task-events", "--concurrency=1", "--loglevel=INFO"]
