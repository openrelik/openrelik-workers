ARG BASE_IMAGE=ubuntu:26.04
FROM ${BASE_IMAGE}

# GIFT PPA track to install Plaso from: "stable" (default) or "staging" (used by CI)
ARG PPA_TRACK=stable

# System packages and Plaso

# Don't prompt during package installation
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

# add-apt-repository fetches the PPA's current signing key from Launchpad, so key
# rotations are picked up automatically. It also runs apt-get update.
# p7zip-full provides the 7z binary used for archive extraction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gpg-agent \
    p7zip-full \
    software-properties-common \
    tzdata \
  && add-apt-repository -y ppa:gift/${PPA_TRACK} \
  && apt-get install -y --no-install-recommends \
    plaso-tools \
  && rm -rf /var/lib/apt/lists/*

# Python environment

WORKDIR /openrelik

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

# Always use the system Python plaso is installed into; ignore .python-version
ENV UV_PYTHON=/usr/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

# Worker packages go in a venv on the system Python. --system-site-packages lets the
# worker import the apt-installed plaso, while log2timeline.py and psort.py
# (#!/usr/bin/python3) run with only the apt packages plaso was built against.
ENV VIRTUAL_ENV=/openrelik/.venv
ENV UV_PROJECT_ENVIRONMENT=${VIRTUAL_ENV} \
    PATH="${VIRTUAL_ENV}/bin:${PATH}"
RUN uv venv --system-site-packages ${VIRTUAL_ENV}

# Install dependencies before copying the code, so code changes don't
# invalidate this layer
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-install-project --no-dev

# Worker code

COPY . ./
RUN uv sync --locked --no-dev

# Runtime

ARG OPENRELIK_PYDEBUG
ENV OPENRELIK_PYDEBUG=${OPENRELIK_PYDEBUG:-0}
ARG OPENRELIK_PYDEBUG_PORT
ENV OPENRELIK_PYDEBUG_PORT=${OPENRELIK_PYDEBUG_PORT:-5678}

# Default command; docker-compose overrides it
CMD ["celery", "--app=src.app", "worker", "--task-events", "--concurrency=1", "--loglevel=INFO"]
