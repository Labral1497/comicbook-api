# app/lib/paths.py
from __future__ import annotations
import os
import uuid
from pathlib import Path
from app.config import config

def data_dir() -> str:
    """
    Root folder for all job artifacts: <base_output_dir>/data
    Ensures it exists and returns it as a string.
    """
    root = Path(config.base_output_dir) / "data"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)

def job_dir(job_id: str) -> str:
    """
    Folder for a specific job: <data_dir>/jobs/<job_id>
    """
    jd = Path(data_dir()) / "jobs" / job_id
    jd.mkdir(parents=True, exist_ok=True)
    return str(jd)

def make_job_dir_with_id() -> tuple[str, str]:
    """
    Creates a new job id + folder and returns (job_id, job_dir_path).
    """
    jid = uuid.uuid4().hex
    return jid, job_dir(jid)

def manifest_path(workdir: str) -> str:
    """
    Path to the manifest.json inside a job directory.
    """
    return str(Path(workdir) / "manifest.json")

def ensure_job_dir(job_id: str) -> str:
    workdir = os.path.join(data_dir(), "jobs", job_id)
    os.makedirs(workdir, exist_ok=True)
    return workdir
