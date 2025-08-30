# app/features/comic/router.py
from __future__ import annotations

import json
import os
import shutil
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import config
from app.logger import get_logger
from app.features.pages.schemas import ComicRequest
from app.lib.paths import ensure_job_dir, make_job_dir_with_id, job_dir
from app.lib.jobs import (
    manifest_path,
    load_manifest,
    prune_job_dir,
    save_manifest,
    pages_done,
    seed_manifest_pending,
    set_cancelled,
    set_task_name,
)
from app.lib.cloud_tasks import create_task, delete_task
from app.lib.imaging import resolve_or_download_cover_ref
from app.lib.gcs_inventory import download_gcs_object_to_file, upload_json_to_gcs, upload_to_gcs
from app.lib.pdf import make_pdf
from app.features.pages.service import render_pages_chained

router = APIRouter(prefix="/api/v1", tags=["comic"])
log = get_logger(__name__)


@router.post("/generate/comic", status_code=202)
async def enqueue_comic_job(req: ComicRequest) -> dict:
    """
    Public endpoint. Fire-and-forget.
    Creates job dir, persists request.json + manifest,
    uploads request.json to GCS, and enqueues a Cloud Task
    to /api/v1/tasks/worker/comic/{job_id}.
    """
    log.info(f"enqueueing comic job for {req.comic_title}")
    # 1) Resolve job_id
    if req.job_id:
        job_id = req.job_id
        workdir = ensure_job_dir(job_id)  # creates if missing
    else:
        job_id, workdir = make_job_dir_with_id()

    # persist locally for debugging / resume
    req_path = os.path.join(workdir, "request.json")
    with open(req_path, "w") as f:
        json.dump(req.model_dump(), f, indent=2)

    # seed manifest with pending pages
    mf_path = manifest_path(workdir)
    mf = load_manifest(mf_path)
    if mf.get("cancelled"):
        log.info(f"[{job_id}] already cancelled; acking")
        return JSONResponse({"job_id": job_id, "ok": True, "cancelled": True})
    seed_manifest_pending(mf_path, total_pages=len(req.pages))

    # upload request.json to GCS (source of truth for worker)
    req_info = upload_json_to_gcs(
        req.model_dump(),
        object_name=f"jobs/{job_id}/request.json",
        subdir="jobs"
    )

    # enqueue Cloud Task (fire and forget)
    task_url = f"{config.public_base_url}/api/v1/tasks/worker/comic/{job_id}"
    resp = create_task(
        queue=config.tasks_queue,
        url=task_url,
        payload={"job_id": job_id, "request_gcs": req_info["gs_uri"]},
        schedule_in_seconds=0,
    )
    log.debug(f"created cloud task for job {job_id}")

    set_task_name(mf_path, resp.name)
    return {
        "job_id": job_id,
        "status_url": f"/api/v1/generate/comic/status/{job_id}",
        "resume_url": f"/api/v1/generate/comic/resume/{job_id}",
        "worker_url": f"/api/v1/tasks/worker/comic/{job_id}",  # local testing
    }

@router.post("/tasks/worker/comic/{job_id}")
async def worker_process(job_id: str, request: Request) -> JSONResponse:
    """
    Cloud Tasks target.
    Idempotent: safe to retry.
    - Downloads request.json if missing
    - Renders sequentially (page N references page N-1)
    - Uploads each page to GCS and updates manifest
    - Builds and uploads final artifact if all pages done
    """
    log.debug(f"worker process called for job id: {job_id}")
    workdir = job_dir(job_id)
    os.makedirs(workdir, exist_ok=True)
    mf_path = manifest_path(workdir)
    mf = load_manifest(mf_path)
    if mf.get("cancelled"):
        log.info(f"[{job_id}] already cancelled; acking")
        return JSONResponse({"job_id": job_id, "ok": True, "cancelled": True}, status_code=200)

    # parse Cloud Task payload
    try:
        body = await request.json()
    except Exception:
        # Malformed body is a permanent caller error
        raise HTTPException(status_code=400, detail="invalid JSON body")

    request_gcs = body.get("request_gcs")

    # ensure request.json exists locally
    req_path = os.path.join(workdir, "request.json")
    if not os.path.exists(req_path):
        if not request_gcs:
            log.error(f"no request.json found for job {job_id} and no request_gcs in payload")
            raise HTTPException(200, f"unknown job_id {job_id}")
        download_gcs_object_to_file(request_gcs, req_path)

    # load request
    with open(req_path, "r") as f:
        req_dict = json.load(f)
    req = ComicRequest(**req_dict)

    # resolve cover image
    cover_ref_path = resolve_or_download_cover_ref(req.image_ref, workdir)
    if not cover_ref_path or not os.path.exists(cover_ref_path):
        raise HTTPException(200, "Invalid or missing cover image reference")

    total_pages = len(req.pages)

    # render sequentially
    render_pages_chained(
        job_id=job_id,
        req=req,
        workdir=workdir,
        cover_image_ref=cover_ref_path,
        manifest_file=mf_path,
        gcs_prefix=f"jobs/{job_id}",
    )

    # collect all local pages
    local_files: List[str] = []
    for i in range(total_pages):
        p = os.path.join(workdir, f"page-{i+1}.png")
        if os.path.exists(p):
            local_files.append(p)

    # finalize if all present
    if len(local_files) == total_pages and mf.get("final") is None:
        if req.return_pdf:
            out_path = os.path.join(workdir, "comic.pdf")
            make_pdf(local_files, pdf_name=out_path)
            mime = "application/pdf"
            objname = f"jobs/{job_id}/comic.pdf"
        else:
            zip_base = os.path.join(workdir, "pages")
            shutil.make_archive(zip_base, "zip", workdir)
            out_path = f"{zip_base}.zip"
            mime = "application/zip"
            objname = f"jobs/{job_id}/pages.zip"

        try:
            info = upload_to_gcs(out_path, object_name=objname)
            mf["final"] = {"mime": mime, "gcs": info}
        except Exception as e:
            mf["final"] = {"mime": mime, "local": out_path, "upload_error": str(e)}

        save_manifest(mf_path, mf)

        # cleanup if configured
        try:
            prune_job_dir(
                workdir,
                remove_pages=config.prune_pages_after_final,
                remove_artifacts=config.prune_artifact_after_upload,
            )
        except Exception as e:
            log.warning(f"failed to prune {workdir}: {e}")

    return JSONResponse({"job_id": job_id, "ok": True})

@router.post("/generate/comic/stop/{job_id}")
async def stop_comic_job(job_id: str) -> dict:
    workdir = job_dir(job_id)
    mf_path = manifest_path(workdir)
    if not os.path.exists(mf_path):
        raise HTTPException(404, f"unknown job_id {job_id}")

    mf = load_manifest(mf_path)

    # 1) mark as cancelled so a running worker can bail out safely
    set_cancelled(mf_path, True)

    # 2) try to delete pending Cloud Task (noop if it's already running/handled)
    deleted = False
    task_name = mf.get("task_name")
    if task_name:
        try:
            deleted = delete_task(
                project=config.gcp_project,
                location=config.gcp_location,
                queue=config.tasks_queue,
                task_name=task_name,
            )
        except Exception:
            # don't fail the endpoint if delete fails; worker will see "cancelled"
            deleted = False
    mf["final"] = {"status": "cancelled"}
    save_manifest(mf_path, mf)

    return {"job_id": job_id, "cancelled": True, "queued_task_deleted": deleted}
