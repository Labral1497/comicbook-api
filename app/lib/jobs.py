# app/lib/jobs.py
from __future__ import annotations

import json
import os, glob
from typing import Dict, Any, Iterable


def manifest_path(workdir: str) -> str:
    return os.path.join(workdir, "manifest.json")


def load_manifest(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"pages": {}, "final": None}
    with open(path, "r") as f:
        return json.load(f)


def save_manifest(path: str, manifest: Dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)


def seed_manifest_pending(path: str, total_pages: int) -> None:
    mf = {"pages": {str(i + 1): {"status": "pending"} for i in range(total_pages)}, "final": None}
    save_manifest(path, mf)


def pages_done(manifest: Dict[str, Any]) -> Iterable[int]:
    for k, v in manifest.get("pages", {}).items():
        if v.get("status") == "done":
            try:
                yield int(k)
            except ValueError:
                continue


def mark_page_status(path: str, page_number: int, status: str, meta: Dict[str, Any] | None = None) -> None:
    mf = load_manifest(path)
    entry = mf.setdefault("pages", {}).setdefault(str(page_number), {})
    entry["status"] = status
    if meta:
        entry.update(meta)
    save_manifest(path, mf)

def prune_job_dir(
    workdir: str,
    *,
    keep_names: tuple[str, ...] = ("manifest.json", "request.json"),
    remove_pages: bool = False,
    remove_artifacts: bool = False,
) -> None:
    """
    Remove generated files in workdir. Keeps `keep_names`.
    - remove_pages: deletes page-*.png
    - remove_artifacts: deletes comic_*.pdf and pages.zip
    """
    try:
        if remove_pages:
            for p in glob.glob(os.path.join(workdir, "page-*.png")):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if remove_artifacts:
            for p in glob.glob(os.path.join(workdir, "comic_*.pdf")):
                try:
                    os.remove(p)
                except Exception:
                    pass
            zip_path = os.path.join(workdir, "pages.zip")
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
        # Don’t delete manifest.json/request.json here; caller may remove the folder later.
    except Exception:
        # best-effort; don't crash the job on cleanup
        pass


def set_cancelled(manifest_file: str, cancelled: bool = True) -> None:
    mf = load_manifest(manifest_file)
    mf["cancelled"] = bool(cancelled)
    save_manifest(manifest_file, mf)

def set_task_name(manifest_file: str, task_name: str) -> None:
    mf = load_manifest(manifest_file)
    mf["task_name"] = task_name
    save_manifest(manifest_file, mf)
