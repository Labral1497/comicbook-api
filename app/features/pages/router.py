# app/features/comic/router.py
from __future__ import annotations

import json
import os
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import config
from app.logger import get_logger
from app.features.pages.schemas import ComicRequest
from app.lib.paths import make_job_dir_with_id, job_dir
from app.lib.jobs import (
    manifest_path,
    load_manifest,
    prune_job_dir,
    save_manifest,
    pages_done,
    seed_manifest_pending,
)
from app.lib.cloud_tasks import create_task
from app.lib.imaging import resolve_or_download_cover_ref
from app.lib.gcs_inventory import upload_to_gcs
from app.lib.pdf import make_pdf
from app.features.pages.service import render_pages_chained

router = APIRouter(prefix="/api/v1", tags=["comic"])
log = get_logger(__name__)


@router.post("/generate/comic", status_code=202)
async def enqueue_comic_job(req: ComicRequest) -> dict:
    """
    Public endpoint. Fire-and-forget.
    Creates job dir, persists request.json and empty manifest,
    enqueues a Cloud Task to /api/v1/tasks/worker/comic/{job_id}.
    """
    log.info(f"genrating comic {req.comic_title}")
    job_id, workdir = make_job_dir_with_id()

    # persist request
    with open(os.path.join(workdir, "request.json"), "w") as f:
        json.dump(req.model_dump(), f, indent=2)

    # seed manifest (all pages pending, no final)
    seed_manifest_pending(manifest_path(workdir), total_pages=len(req.pages))

    # enqueue Cloud Task to run the heavy job
    task_url = f"{config.public_base_url}/api/v1/tasks/worker/comic/{job_id}"
    create_task(
        queue=config.tasks_queue,
        url=task_url,
        payload={"job_id": job_id},
        schedule_in_seconds=0,
    )
    log.debug(f"created cloud task with job id: {job_id}")

    return {
        "job_id": job_id,
        "status_url": f"/api/v1/generate/comic/status/{job_id}",
        "resume_url": f"/api/v1/generate/comic/resume/{job_id}",
        "worker_url": f"/api/v1/tasks/worker/comic/{job_id}",  # for local testing
    }


@router.get("/generate/comic/status/{job_id}")
async def status(job_id: str) -> dict:
    """Return manifest content (pages + final)."""
    log.debug(f"Checked status on job id: {job_id}")
    workdir = job_dir(job_id)
    mf = load_manifest(manifest_path(workdir))
    return mf


@router.post("/generate/comic/resume/{job_id}", status_code=202)
async def resume(job_id: str) -> dict:
    """
    Re-enqueue the job (idempotent). The worker will skip already-finished pages.
    Useful if the job was interrupted, or GCS upload failed earlier.
    """
    log.debug(f"resumed cloud task with job id: {job_id}")
    workdir = job_dir(job_id)
    req_path = os.path.join(workdir, "request.json")
    if not os.path.exists(req_path):
        raise HTTPException(404, f"unknown job_id {job_id}")

    task_url = f"{config.public_base_url}/api/v1/tasks/worker/comic/{job_id}"
    create_task(
        queue=config.tasks_queue,
        url=task_url,
        payload={"job_id": job_id},
        schedule_in_seconds=0,
    )
    return {"job_id": job_id, "resumed": True}


@router.post("/tasks/worker/comic/{job_id}")
async def worker_process(job_id: str, request: Request) -> JSONResponse:
    """
    Private worker endpoint (Cloud Tasks target).
    - Recomputes which pages are missing (manifest-driven).
    - Renders sequentially (page N references N-1) for continuity.
    - Uploads each page on completion, updates manifest continuously.
    - Builds and uploads final artifact when all pages exist.
    This handler should be idempotent: safe to retry.
    """
    # optional: validate Cloud Tasks signature/token here
    log.debug(f"woekre process called for job id: {job_id}")
    workdir = job_dir(job_id)
    req_path = os.path.join(workdir, "request.json")
    if not os.path.exists(req_path):
        raise HTTPException(404, f"unknown job_id {job_id}")

    # load request
    with open(req_path, "r") as f:
        req_dict = json.load(f)
    req = ComicRequest(**req_dict)

    mf_path = manifest_path(workdir)
    mf = load_manifest(mf_path)

    # resolve cover reference (file path)
    cover_ref_path = resolve_or_download_cover_ref(req.image_ref, workdir)
    if not cover_ref_path or not os.path.exists(cover_ref_path):
        raise HTTPException(400, "Invalid or missing cover image reference (image_ref)")

    # determine which pages already exist so we don't re-do them
    already_done = set(pages_done(mf))  # pages with status == 'done'
    total_pages = len(req.pages)

    # run chained generation (page 1 uses cover; page N uses page N-1)
    files = render_pages_chained(
        req=req,
        workdir=workdir,
        cover_image_ref=cover_ref_path,
        manifest_file=mf_path,  # progress and status written as we go
        gcs_prefix=f"jobs/{job_id}",
    )

    # collect locally existing pages in order
    local_files: List[str] = []
    for i in range(total_pages):
        p = os.path.join(workdir, f"page-{i+1}.png")
        if os.path.exists(p):
            local_files.append(p)

    # if all exist, build+upload final
    if len(local_files) == total_pages and mf.get("final") is None:
        # build PDF or ZIP
        if req.return_pdf:
            out_path = os.path.join(workdir, "comic.pdf")
            make_pdf(local_files, pdf_name=out_path)
            mime = "application/pdf"
            objname = f"jobs/{job_id}/comic.pdf"
        else:
            import shutil
            zip_base = os.path.join(workdir, "pages")
            shutil.make_archive(zip_base, "zip", workdir)
            out_path = f"{zip_base}.zip"
            mime = "application/zip"
            objname = f"jobs/{job_id}/pages.zip"

        # try upload, record in manifest
        try:
            info = upload_to_gcs(out_path, object_name=objname)
            mf["final"] = {"mime": mime, "gcs": info}
        except Exception as e:
            mf["final"] = {"mime": mime, "local": out_path, "upload_error": str(e)}

        save_manifest(mf_path, mf)
        try:
            prune_job_dir(
                workdir,
                remove_pages=config.prune_pages_after_final,
                remove_artifacts=config.prune_artifact_after_upload,
            )
        except Exception:
            pass

    return JSONResponse({"job_id": job_id, "ok": True})
