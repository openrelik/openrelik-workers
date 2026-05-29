[![codecov](https://codecov.io/github/openrelik/openrelik-worker-containers/graph/badge.svg?token=TMSHQ9KNO5)](https://codecov.io/github/openrelik/openrelik-worker-containers)

# OpenRelik worker for Containers

The OpenRelik Containers Worker analyzes disk images for containerd or Docker containers. It gets
tasks through Celery to examine either entire disk images or specific container IDs found within
them.

The container worker only processes input files that are disk images with one of these extensions:
.raw, .img, .dd, .qcow, .qcow2, or .qcow3. Files without these extensions won't be processed.

## Features

- Lists Containers:
  - Discovers Docker and containerd containers located on disk.
  - Uses default storage paths (`/var/lib/docker` or `/var/lib/containerd`) by default.
  - Allows specifying custom container root directories (e.g., `/data/containers/docker/`).

- Show Container Drift:
  - Detects modifications made to running containers.
  - Identifies changes such as configuration alterations, malware additions, or file deletions.

- Export Container Files:
  - Specific Files/Directories: Exports designated files or folders from a container for use by other OpenRelik workers.

- Container Export Functionality:
  - Exports complete container filesystems as `.tar.gz` archives or `.raw` disk images for OpenRelik processing.
  - Filters container exports based on labels (e.g., `io.kubernetes.pod.namespace=myapp`).
  - Excludes containers within the `kube-system` namespace.
  - Processes multiple input disks.
  - Automatically detects containers across all available namespaces.
  - Records the export time as the filesystem birth timestamp in the archive.
  - Without specific configuration, defaults to exporting all containers as disk images.

  **Note**: File creation timestamp on exported containers will be the time of the export.

## Prerequisites

The following software is required to build local image.

- Docker
- Docker Compose
- Git

## Installation

OpenRelik containers worker can be installed by using the pre-build Docker image or building a
local Docker image.

**Note on Privileges:** This worker requires `privileged` mode and `SYS_ADMIN` capabilities to perform necessary mounting operations (e.g., mounting disk images, container layers via FUSE or loop devices). Be aware of the security implications of granting these privileges.


### Using Pre-built Docker Image

Update the `docker-compose.yml` to include `openrelik-worker-containers` stable release from OpenRelik container registry.

```yaml
openrelik-worker-containers:
  container_name: openrelik-worker-containers
  image: ghcr.io/openrelik/openrelik-worker-containers:${OPENRELIK_WORKER_CONTAINERS_VERSION}
  platform: linux/amd64
  privileged: true
  restart: always
  environment:
    - REDIS_URL=redis://openrelik-redis:6379
  volumes:
    - /dev:/dev
    - ./data:/usr/share/openrelik/data
  command: "celery --app=src.app worker --task-events --concurrency=2 --loglevel=INFO -Q openrelik-worker-containers"
```

Add __one__ of the below environment variables to output structured JSON or Console logging.

```yaml
environment:
    - OPENRELIK_LOG_TYPE=structlog
    - OPENRELIK_LOG_TYPE=structlog_console
```

### Building Local Image

1. Clone `openrelik-worker-containers`.

    ```shell
    git clone https://github.com/openrelik/openrelik-worker-containers
    ```

2. Build a Docker container.

    Container Explorer image used in the container is linux/amd64 binary, and the Docker container for
    `openrelik-worker-containers` needs to be `linux/amd64` as well.

    ```shell
    cd openrelik-worker-containers
    docker build --platform linux/amd64 -t openrelik-worker-containers:latest .
    ```

3. Update the `docker-compose.yml` to include `openrelik-worker-containers`.

    ```yaml
    openrelik-worker-containers:
      container_name: openrelik-worker-containers
      image: openrelik-worker-containers:latest
      platform: linux/amd64
      privileged: true
      restart: always
      environment:
        - REDIS_URL=redis://openrelik-redis:6379
      volumes:
        - /dev:/dev
        - ./data:/usr/share/openrelik/data
      command: "celery --app=src.app worker --task-events --concurrency=2 --loglevel=INFO -Q openrelik-worker-containers"
    ```

4. Run `openrelik-worker-containers`.

    ```shell
    docker compose up -d openrelik-worker-containers
    ```

5. Run the following command to review `openrelik-worker-containers` logs.

    ```shell
    docker logs -f openrelik-worker-containers
    ```

    **Note**: Update `docker-compose.yml` to view `openrelik-worker-containers` debug logs.

    ```yaml
    openrelik-worker-containers:
      container_name: openrelik-worker-containers
      image: openrelik-worker-containers:latest
      platform: linux/amd64
      privileged: true
      restart: always
      environment:
        - REDIS_URL=redis://openrelik-redis:6379
      volumes:
        - /dev:/dev
        - ./data:/usr/share/openrelik/data
      command: "celery --app=src.app worker --task-events --concurrency=2 --loglevel=DEBUG -Q openrelik-worker-containers"
    ```

### Updating Container Explorer Version

The OpenRelik container worker currently uses Container Explorer version 0.4.0. To use a different version with OpenRelik, modify the `CE_VER` variable in the `setup.sh` script.

```bash
Example:
set -e

SCRIPTNAME=$(basename "$0")

CE_VER=0.4.0
CE_PKG=container-explorer.tar.gz
```

**Note**: The minimum required version of Container Explorer for the OpenRelik container worker is 0.4.0.

