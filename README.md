> [!IMPORTANT]
> **This repository has moved to [openrelik/openrelik](https://github.com/openrelik/openrelik),**
> the OpenRelik monorepo, where it lives in [`workers/`](https://github.com/openrelik/openrelik/tree/main/workers).
> This repository is archived and read-only.
>
> The full history moved with it. Open issues were moved too. Please open new issues and pull requests in
> [openrelik/openrelik](https://github.com/openrelik/openrelik).
>
> Each worker is in `workers/<name>/`, and the openrelik-worker-common library is in [`libs/worker-common/`](https://github.com/openrelik/openrelik/tree/main/libs/worker-common).

# OpenRelik Workers Repository

This repository contains all OpenRelik Core Workers.

## How to Use

### How create a new worker
This repository contains the core workers only! When you want to create your own worker use the openrelik-worker-template repository and follow the instructions [there](https://github.com/openrelik/openrelik-worker-template/).

If you think your worker should be part of the OpenRelik Core Worker open a feature request issue.

### Development
Fork this repository, clone it, develop and finally create a PR against this repository. More information on how to setup your development environment for OpenRelik can be found at [here](https://openrelik.org/docs/developer/developing/) and a guide on worker development is [here](https://openrelik.org/docs/developer/create-a-new-worker/).

Every subfolder contains their own README with more details per worker.

## Worker Test Coverage

<!-- COVERAGE_START -->
| Worker | Coverage |
| --- | --- |
| analyzer-config | 96% |
| analyzer-logs | 78% |
| bulkextractor | 97% |
| capa | 98% |
| chromecreds | 97% |
| cloud-logs | 100% |
| containers | 57% |
| dfindexeddb | 85% |
| duckdb | 0% |
| entropy | 98% |
| exif | 96% |
| extraction | 98% |
| floss | 94% |
| grep | 100% |
| hasher | 99% |
| indx | 95% |
| llm | 0% |
| os-creds | 96% |
| photorec | 99% |
| plaso | 90% |
| strings | 100% |
| timesketch | 76% |
| yara | 95% |
<!-- COVERAGE_END -->
