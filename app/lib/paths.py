# app/lib/paths.py
import os, uuid

DATA_ROOT = os.getenv("DATA_ROOT", os.path.join(os.getcwd(), "data"))
JOBS_ROOT = os.path.join(DATA_ROOT, "jobs")

def job_dir(job_id: str) -> str:
    path = os.path.join(JOBS_ROOT, job_id)
    os.makedirs(path, exist_ok=True)
    return path

def make_job_dir_with_id() -> tuple[str, str]:
    jid = uuid.uuid4().hex
    return jid, job_dir(jid)
