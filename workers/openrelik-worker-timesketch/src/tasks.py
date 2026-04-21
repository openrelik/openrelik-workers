# Copyright 2024 Google LLC
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

import os
import time

from openrelik_worker_common.task_utils import create_task_result, get_input_files
from timesketch_api_client import client as timesketch_client
from timesketch_import_client import importer

from .app import celery, redis_client

# Hardcoded list of available Timesketch analyzers
TIMESKETCH_ANALYZERS = [
    "account_finder",
    "browser_search",
    "browser_timeframe",
    "domain",
    "feature_extraction",
    "hashr_lookup",
    "tagger",
    "yetikeywords",
    "yetibloomchecker",
    "yetitriageindicators",
    "yetibadnessindicators",
    "yetilolbasindicators",
    "yetiinvestigations",
]

MAX_INDEXING_RETRIES = 240
POLL_INTERVAL_SECONDS = 5


def get_or_create_sketch(
    timesketch_api_client,
    redis_client,
    sketch_id: int | str | None = None,
    sketch_name: str | None = None,
    workflow_id: str | None = None,
):
    """
    Retrieves or creates a sketch, handling locking if needed.
    This uses Redis distributed lock to avoid race conditions.

    Args:
        client: Timesketch API client.
        redis_client: Redis client.
        sketch_id: ID of the sketch to retrieve.
        sketch_name: Name of the sketch to create.
        workflow_id: ID of the workflow.

    Returns:
        Timesketch sketch object or None if failed
    """
    sketch = None

    if sketch_id:
        try:
            sketch = timesketch_api_client.get_sketch(int(sketch_id))
        except ValueError:
            raise ValueError(f"Sketch ID must be a number. Received: '{sketch_id}'")
    elif sketch_name:
        sketch = timesketch_api_client.create_sketch(sketch_name)
    else:
        sketch_name = f"openrelik-workflow-{workflow_id}"
        # Prevent multiple distributed workers from concurrently creating the same
        # sketch. This Redis-based lock ensures only one worker proceeds at a time, even
        # across different machines. The code will block until the lock is acquired.
        # The lock automatically expires after 60 seconds to prevent deadlocks.
        with redis_client.lock(sketch_name, timeout=60, blocking_timeout=5):
            # Search for an existing sketch while having the lock
            for _sketch in timesketch_api_client.list_sketches():
                if _sketch.name == sketch_name:
                    sketch = _sketch
                    break

            # If not found, create a new one
            if not sketch:
                sketch = timesketch_api_client.create_sketch(sketch_name)

    return sketch


# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-timesketch.tasks.upload"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Upload to Timesketch",
    "description": "Upload resulting file to Timesketch",
    "task_config": [
        {
            "name": "sketch_id",
            "label": "Add to an existing sketch",
            "description": "Provide the numerical sketch ID of the existing sketch",
            "type": "text",
            "required": False,
        },
        {
            "name": "sketch_name",
            "label": "Name of the new sketch to create",
            "description": "Create a new sketch",
            "type": "text",
            "required": False,
        },
        {
            "name": "timeline_name",
            "label": "Name of the timeline to create",
            "description": "Timeline name",
            "type": "text",
            "required": False,
        },
        {
            "name": "analyzers",
            "label": "Select Analyzers",
            "description": "Select Timesketch Analyzers to run on the timeline after upload.",
            "type": "autocomplete",
            "items": TIMESKETCH_ANALYZERS,
            "required": False,
        },
        {
            "name": "shared_users",
            "label": "Share with Timesketch users",
            "description": (
                "Comma-separated list of Timesketch usernames to share the "
                "sketch with (e.g., admin,user1@example.com)."
            ),
            "type": "text",
            "required": False,
        },
        {
            "name": "shared_groups",
            "label": "Share with Timesketch groups",
            "description": (
                "Comma-separated list of Timesketch groups to share the "
                "sketch with (e.g., DF,SOC)."
            ),
            "type": "text",
            "required": False,
        },
        {
            "name": "make_private",
            "label": "Set Sketch as Private",
            "description": (
                "By default, sketches are public so you can view them. "
                "If you check this, ONLY the users specified in the shared "
                "list above will have access."
            ),
            "type": "checkbox",
            "required": False,
        },
    ],
}


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def upload(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Export files to Timesketch.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Base64-encoded dictionary containing task results.
    """
    input_files = get_input_files(pipe_result, input_files or [])
    task_config = task_config or {}

    # Connection details from environment variables.
    timesketch_server_url = os.environ.get("TIMESKETCH_SERVER_URL")
    if not timesketch_server_url:
        raise RuntimeError(
            "TIMESKETCH_SERVER_URL environment variable is not set on the worker."
        )

    timesketch_server_public_url = os.environ.get("TIMESKETCH_SERVER_PUBLIC_URL")
    timesketch_username = os.environ.get("TIMESKETCH_USERNAME")
    timesketch_password = os.environ.get("TIMESKETCH_PASSWORD")

    # User supplied config.
    sketch_id = task_config.get("sketch_id")
    sketch_name = task_config.get("sketch_name")

    # Analyzers config
    selected_analyzers = task_config.get("analyzers", [])

    # Extract Access Control Config safely
    make_private = task_config.get("make_private", False)
    if isinstance(make_private, str):
        make_private = make_private.lower() in ["true", "1", "yes"]
    else:
        make_private = bool(make_private)

    # Public Sketch is the default!
    is_public = not make_private

    shared_users_str = task_config.get("shared_users", "")
    shared_users = []
    if shared_users_str:
        # Split by comma, trim whitespace, and ignore empty strings
        shared_users = [u.strip() for u in shared_users_str.split(",") if u.strip()]

    shared_groups_str = task_config.get("shared_groups", "")
    shared_groups = []
    if shared_groups_str:
        # Split by comma, trim whitespace, and ignore empty strings
        shared_groups = [g.strip() for g in shared_groups_str.split(",") if g.strip()]

    # Create a Timesketch API client.
    timesketch_api_client = timesketch_client.TimesketchApi(
        host_uri=timesketch_server_url,
        username=timesketch_username,
        password=timesketch_password,
    )

    # UI Update: Initializing
    self.send_event(
        "task-progress",
        data={"status": "Connecting to Timesketch API and configuring Sketch..."},
    )

    # Get or create sketch using a distributed lock.
    sketch = get_or_create_sketch(
        timesketch_api_client,
        redis_client,
        sketch_id=sketch_id,
        sketch_name=sketch_name,
        workflow_id=workflow_id,
    )

    if not sketch:
        raise Exception(
            f"Failed to create or retrieve sketch '{sketch_name or sketch_id}'"
        )

    # Apply Access Controls to the sketch
    sketch.add_to_acl(
        make_public=is_public, user_list=shared_users, group_list=shared_groups
    )

    warnings = []
    uploaded_timelines = []
    total_files = len(input_files)

    # Import each input file to its own index.
    for index, input_file in enumerate(input_files, start=1):
        input_file_path = input_file.get("path")
        file_display_name = input_file.get("display_name")

        # Prevent identical timeline names if multiple files are processed
        base_name = task_config.get("timeline_name")
        if base_name and total_files > 1:
            timeline_name = f"{base_name} - {file_display_name}"
        else:
            timeline_name = base_name or file_display_name

        timeline = None

        # UI Update: Uploading
        self.send_event(
            "task-progress",
            data={
                "status": "Uploading file to Timesketch",
                "progress": f"File {index} of {total_files}",
                "current_file": file_display_name,
                "timeline_name": timeline_name,
            },
        )

        with importer.ImportStreamer() as streamer:
            streamer.set_sketch(sketch)
            streamer.set_timeline_name(timeline_name)
            streamer.add_file(input_file_path)

            # Grab the timeline object before context closes so we can query it later
            timeline = streamer.timeline

        # Append to our summary list
        if timeline:
            uploaded_timelines.append({"ID": timeline.id, "Name": timeline.name})

        # If the user selected analyzers, we must wait for indexing to complete
        if selected_analyzers and timeline:
            max_retries = MAX_INDEXING_RETRIES
            retry_count = 0

            while retry_count < max_retries:
                # Always fetch the latest status to display
                current_status = timeline.status

                # UI Update: Indexing
                self.send_event(
                    "task-progress",
                    data={
                        "status": "Waiting for Timesketch internal indexing to finish",
                        "Sketch": f"{timesketch_server_public_url}/sketch/{sketch.id}",
                        "progress": f"File {index} of {total_files}",
                        "current_file": file_display_name,
                        "timesketch_status": current_status,
                        "time_elapsed": f"{retry_count * POLL_INTERVAL_SECONDS}s (Timeout at {max_retries * POLL_INTERVAL_SECONDS}s)",
                    },
                )

                if current_status in ["ready", "fail"]:
                    break

                retry_count += 1
                time.sleep(POLL_INTERVAL_SECONDS)

            # Once ready, trigger the analyzers
            if timeline.status == "ready":
                # UI Update: Triggering analyzers
                self.send_event(
                    "task-progress",
                    data={
                        "status": "Triggering Analyzers in Timesketch",
                        "Sketch": f"{timesketch_server_public_url}/sketch/{sketch.id}",
                        "progress": f"File {index} of {total_files}",
                        "current_file": file_display_name,
                        "analyzers_queued": len(selected_analyzers),
                    },
                )

                for analyzer in selected_analyzers:
                    timeline.run_analyzer(analyzer)
            elif timeline.status == "fail":
                warnings.append(
                    f"Analyzers for timeline '{timeline_name}' skipped because Timesketch failed to index the file."
                )
            else:
                warnings.append(
                    f"Analyzers for timeline '{timeline_name}' skipped because it was not ready within "
                    f"{max_retries * POLL_INTERVAL_SECONDS} seconds!"
                )

    # Create the metadata dictionary
    meta_result = {
        "sketch": f"{timesketch_server_public_url}/sketch/{sketch.id}",
    }

    # Flatten the uploaded timelines into a single, readable string
    timelines_summary = ", ".join(
        f'"{t["Name"]}" (ID: {t["ID"]})' for t in uploaded_timelines
    )
    if timelines_summary:
        meta_result["uploaded_timelines"] = timelines_summary

    # If any warnings occurred, append them so they appear in the UI
    if warnings:
        meta_result["warnings"] = " | ".join(warnings)

    # UI Update: Finished
    self.send_event(
        "task-progress", data={"status": "Done! Finished exporting to Timesketch."}
    )

    return create_task_result(
        output_files=[],
        workflow_id=workflow_id,
        command="Timesketch Importer Client",
        meta=meta_result,
    )
