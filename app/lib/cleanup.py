import os
import time
import shutil
from pathlib import Path

from app.lib.jobs import load_manifest, manifest_path

ALLOWLIST = {"manifest.json", "request.json"}  # keep for /status & replay

def sweep_finished_jobs(base_dir: str, *, ttl_hours: int) -> int:
    """
    Delete entire job folders that:
      - contain a manifest with 'final' set
      - and are older than ttl_hours
    Returns how many folders were removed.
    """
    now = time.time()
    removed = 0
    base = Path(base_dir)
    if not base.exists():
        return 0

    for sub in base.iterdir():
        if not sub.is_dir():
            continue
        mf = manifest_path(sub.as_posix())
        if not os.path.exists(mf):
            continue
        try:
            mtime = sub.stat().st_mtime
            age_hours = (now - mtime) / 3600.0
            manifest = load_manifest(mf)
            is_final = bool(manifest.get("final"))
            if is_final and age_hours >= ttl_hours:
                shutil.rmtree(sub.as_posix(), ignore_errors=True)
                removed += 1
        except Exception:
            # best-effort
            continue
    return removed
