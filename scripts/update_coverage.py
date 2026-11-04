#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Update worker test coverage summary table in the root README.md."""

import os
import re
import subprocess
import sys
from pathlib import Path

COVERAGE_START = "<!-- COVERAGE_START -->"
COVERAGE_END = "<!-- COVERAGE_END -->"
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def extract_coverage(stdout: str) -> str | None:
    """Extract total coverage percentage from pytest-cov output."""
    clean_stdout = ANSI_ESCAPE.sub("", stdout)
    match = re.search(r"^TOTAL\s+.*?(\d+%)", clean_stdout, re.MULTILINE)
    if match:
        return match.group(1)
    return None


def run_worker_tests(worker_dir: Path, env: dict[str, str]) -> str:
    """Run pytest with coverage in a worker directory and return coverage status."""
    cmd = ["uv", "run", "pytest", "--cov=src"]
    try:
        result = subprocess.run(
            cmd,
            cwd=worker_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
            check=False,
        )

        # If running pytest directly fails, try with --all-groups in case
        # the worker has default-groups = [] configured in pyproject.toml.
        if result.returncode != 0:
            fallback_cmd = ["uv", "run", "--all-groups", "pytest", "--cov=src"]
            fallback_result = subprocess.run(
                fallback_cmd,
                cwd=worker_dir,
                capture_output=True,
                text=True,
                env=env,
                timeout=180,
                check=False,
            )
            if fallback_result.returncode == 0:
                result = fallback_result

        if result.returncode == 0:
            cov = extract_coverage(result.stdout)
            return cov if cov else "N/A"
        return "Failed"
    except subprocess.TimeoutExpired:
        print(f"[{worker_dir.name}] pytest timed out", file=sys.stderr)
        return "Failed"
    except (subprocess.SubprocessError, OSError) as err:
        print(f"[{worker_dir.name}] Error running pytest: {err}", file=sys.stderr)
        return "Failed"


def generate_markdown_table(results: dict[str, str]) -> str:
    """Generate a markdown table from worker coverage results."""
    lines = [
        "| Worker | Coverage |",
        "| --- | --- |",
    ]
    for worker_name, coverage in results.items():
        lines.append(f"| {worker_name} | {coverage} |")
    return "\n".join(lines)


def update_readme(readme_path: Path, table: str) -> None:
    """Inject markdown table between COVERAGE_START and COVERAGE_END markers."""
    content = readme_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"({re.escape(COVERAGE_START)}).*?({re.escape(COVERAGE_END)})",
        re.DOTALL,
    )

    if not pattern.search(content):
        raise RuntimeError(
            f"Coverage markers {COVERAGE_START} and {COVERAGE_END} not found in {readme_path}"
        )

    updated = pattern.sub(f"\\1\n{table}\n\\2", content)
    readme_path.write_text(updated, encoding="utf-8")


def main() -> None:
    """Main execution function."""
    repo_root = Path(__file__).resolve().parent.parent
    readme_path = repo_root / "README.md"
    workers_dir = repo_root / "workers"

    if not workers_dir.is_dir():
        raise RuntimeError(f"Workers directory not found at {workers_dir}")

    worker_dirs = sorted([d for d in workers_dir.iterdir() if d.is_dir()])
    print(f"Found {len(worker_dirs)} workers in {workers_dir}")

    env = os.environ.copy()
    # Provide a default REDIS_URL to avoid connection-string errors during app import.
    env.setdefault("REDIS_URL", "redis://localhost:6379")

    results: dict[str, str] = {}
    for worker_dir in worker_dirs:
        print(f"Running tests for worker: {worker_dir.name}...")
        coverage = run_worker_tests(worker_dir, env)
        results[worker_dir.name] = coverage
        print(f"  -> {worker_dir.name}: {coverage}")

    table = generate_markdown_table(results)
    update_readme(readme_path, table)
    print(f"Successfully updated {readme_path} with test coverage table.")


if __name__ == "__main__":
    main()
