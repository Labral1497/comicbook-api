# app/lib/cloud_tasks.py
from __future__ import annotations

import json
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import datetime
from google.api_core.exceptions import NotFound


from app.config import config


def create_task(*, queue: str, url: str, payload: dict, schedule_in_seconds: int = 0):
    """
    Create an HTTP task targeting FastAPI worker endpoint.
    Assumes OIDC auth is not used; protect via network/IAP/firewall as needed.
    """
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(config.gcp_project, config.gcp_location, queue)

    body = json.dumps(payload).encode("utf-8")
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "body": body,
        },
        "dispatch_deadline": {"seconds": 1800},
    }

    if schedule_in_seconds > 0:
        d = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=schedule_in_seconds)
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(d)
        task["schedule_time"] = ts

    return client.create_task(parent=parent, task=task)

def delete_task(*, project: str, location: str, queue: str, task_name: str) -> bool:
    """
    Delete a task by full task name:
      projects/<proj>/locations/<loc>/queues/<queue>/tasks/<id>
    Returns True if deleted, False if it didn't exist.
    """
    client = tasks_v2.CloudTasksClient()
    try:
        client.delete_task(name=task_name)
        return True
    except NotFound:
        return False
