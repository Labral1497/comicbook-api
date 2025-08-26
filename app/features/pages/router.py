# app/features/comic/router.py
from fastapi import APIRouter, BackgroundTasks, HTTPException
import uuid, os, shutil, json
from typing import List
from app.features.pages.schemas import ComicRequest
from app.lib.gcs_inventory import upload_to_gcs
from app.lib.imaging import maybe_decode_image_to_path
from app.lib.paths import job_dir, make_job_dir_with_id
from app.lib.pdf import make_pdf
from app.lib.jobs import load_manifest, save_manifest, manifest_path, pages_done
from app.features.pages.service import render_pages_chained
from app.logger import get_logger
from app.config import config

router = APIRouter(prefix="/api/v1", tags=["comic"])
log = get_logger(__name__)

def _seed_manifest(manifest_file: str, total_pages: int) -> None:
    """Initialize manifest with all pages pending, so /status is informative immediately."""
    mf = {
        "pages": {str(i + 1): {"status": "pending"} for i in range(total_pages)},
        "final": None,
    }
    save_manifest(manifest_file, mf)

def _mark_page_rendered(manifest_file: str, page_num: int, local_path: str, uploaded: bool, gcs_info=None, upload_error: str | None = None):
    mf = load_manifest(manifest_file)
    entry = mf.setdefault("pages", {}).setdefault(str(page_num), {})
    entry.update({
        "status": "done" if uploaded else "rendered",
        "local": local_path,
        "uploaded": uploaded,
    })
    if uploaded and gcs_info is not None:
        entry["gcs"] = gcs_info
    if upload_error:
        entry["upload_error"] = upload_error
    save_manifest(manifest_file, mf)

def _finalize_job(workdir: str, files: List[str], req: ComicRequest, gcs_prefix: str, manifest_file: str):
    """Build PDF/ZIP and upload; record in manifest.final."""
    if req.return_pdf:
        out_path = os.path.join(workdir, f"comic_{uuid.uuid4().hex}.pdf")
        make_pdf(files, pdf_name=out_path)
        mime = "application/pdf"
        objname = f"{gcs_prefix}/comic.pdf"
    else:
        zip_base = os.path.join(workdir, "pages")
        shutil.make_archive(zip_base, "zip", workdir)
        out_path = f"{zip_base}.zip"
        mime = "application/zip"
        objname = f"{gcs_prefix}/pages.zip"

    try:
        info = upload_to_gcs(out_path, object_name=objname)
        final = {"mime": mime, "gcs": info}
    except Exception as e:
        log.exception(f"Final artifact upload failed: {e}")
        final = {"mime": mime, "local": out_path, "upload_error": str(e)}

    mf = load_manifest(manifest_file)
    mf["final"] = final
    save_manifest(manifest_file, mf)

async def _process_job(job_id: str, req: ComicRequest, workdir: str):
    """
    Long-running background job:
      - decode/resolve cover image reference
      - generate pages SEQUENTIALLY (page N references page N-1)
      - upload each page on completion
      - build and upload final artifact when all pages exist
    """
    gcs_prefix = f"jobs/{job_id}"
    manifest_file = manifest_path(workdir)

    # persist request for resume
    with open(os.path.join(workdir, "request.json"), "w") as f:
        json.dump(req.model_dump(), f, indent=2)

    # decode cover ref (required for page 1 reference)
    cover_ref_path = maybe_decode_image_to_path(req.image_ref, workdir)
    if not cover_ref_path or not os.path.exists(cover_ref_path):
        raise HTTPException(400, "Invalid or missing cover image reference (image_ref)")

    # seed manifest with all pages pending
    total_pages = len(req.pages)
    _seed_manifest(manifest_file, total_pages)

    # compute which pages already done (resume support)
    mf = load_manifest(manifest_file)
    done_set = set(pages_done(mf))    # integers of pages with status 'done'
    # For chained rendering we need previous frames; we will re-render from the first missing
    # contiguous point to preserve continuity if needed.

    # define callback for each finished page
    def on_page_done(idx_zero_based: int, local_path: str):
        page_num = idx_zero_based + 1
        try:
            info = upload_to_gcs(local_path, object_name=f"{gcs_prefix}/pages/page-{page_num}.png")
            _mark_page_rendered(manifest_file, page_num, local_path, uploaded=True, gcs_info=info)
        except Exception as e:
            log.exception(f"GCS upload failed for page {page_num}: {e}")
            _mark_page_rendered(manifest_file, page_num, local_path, uploaded=False, upload_error=str(e))

    # Run chained generation (page 1 uses cover; page N uses page N-1)
    files = render_pages_chained(
        req=req,
        workdir=workdir,
        cover_image_ref=cover_ref_path,
        manifest_file=manifest_file,   # <-- pass it through
        # gcs_prefix=gcs_prefix,         # <-- optional uploads
        on_page_done=on_page_done,     # keep your callback
    )

    # Collect all local files that actually exist (in order)
    existing_files: List[str] = []
    for i in range(total_pages):
        p = os.path.join(workdir, f"page-{i+1}.png")
        if os.path.exists(p):
            existing_files.append(p)

    if len(existing_files) == total_pages:
        _finalize_job(workdir, existing_files, req, gcs_prefix, manifest_file)

@router.post("/generate/comic", status_code=202)
async def generate_comic(background_tasks: BackgroundTasks, req: ComicRequest):
    job_id, workdir = make_job_dir_with_id()

    # optional cleanup after response is sent
    if not config.keep_outputs:
        background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)

    # kick off the long-running job
    background_tasks.add_task(_process_job, job_id, req, workdir)

    # return tracking info
    return {
        "job_id": job_id,
        "status_url": f"/api/v1/generate/comic/status/{job_id}",
        "resume_url": f"/api/v1/generate/comic/resume/{job_id}",
    }

@router.get("/generate/comic/status/{job_id}")
async def status(job_id: str):
    workdir = job_dir(job_id)
    mf = load_manifest(manifest_path(workdir))
    return mf

@router.post("/generate/comic/resume/{job_id}", status_code=202)
async def resume(background_tasks: BackgroundTasks, job_id: str):
    workdir = job_dir(job_id)
    req_path = os.path.join(workdir, "request.json")
    if not os.path.exists(req_path):
        raise HTTPException(404, f"unknown job_id {job_id}")
    with open(req_path, "r") as f:
        req_dict = json.load(f)
    req = ComicRequest(**req_dict)
    background_tasks.add_task(_process_job, job_id, req, workdir)
    return {"job_id": job_id, "resumed": True}
