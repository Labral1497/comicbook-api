# app/lib/fs.py
import uuid
from pathlib import Path

def make_job_dir(base: str = "data/jobs") -> str:
    path = Path(base) / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
