# app/features/comic/router.py
import base64
import json
import os
import shutil
import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from app.config import config
from app import logger
from app.features.pages.schemas import ComicRequest
from app.features.pages.service import build_page_prompts, render_pages_from_prompts
from app.lib.fs import make_job_dir
from app.lib.gcs_inventory import upload_to_gcs
from app.lib.imaging import maybe_decode_image_to_path
from app.lib.pdf import make_pdf

router = APIRouter(prefix="/api/v1", tags=["comic"])
log = logger.get_logger(__name__)

@router.post("/generate/comic")
async def generate_comic(
    background_tasks: BackgroundTasks,
    req: ComicRequest,
):
    workdir = make_job_dir()
    log.info(f"Working directory created: {workdir}")

    # Auto-clean temp directory after response is sent
    if not config.keep_outputs:
        background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)

    # Build page prompts (mirrors your original logic)
    image_ref_path = maybe_decode_image_to_path(req.image_ref, workdir)

    prepared_prompts = build_page_prompts(req)

    # Generate images
    files = render_pages_from_prompts(prepared_prompts, workdir=workdir, image_ref=image_ref_path)
    if not files:
        raise HTTPException(status_code=500, detail="no pages were generated")

    # Decide which artifact to build
    if req.return_pdf:
        out_path = os.path.join(workdir, f"comic_{uuid.uuid4().hex}.pdf")
        make_pdf(files, pdf_name=out_path)
        mime = "application/pdf"
        download_name = "comic.pdf"
    else:
        zip_base = os.path.join(workdir, "pages")
        shutil.make_archive(zip_base, "zip", workdir)
        out_path = f"{zip_base}.zip"
        mime = "application/zip"
        download_name = "comic_pages.zip"

    # Now return by mode
    mode = req.return_mode
    if mode == "inline":
        return FileResponse(out_path, media_type=mime, filename=download_name)

    elif mode == "base64":
        with open(out_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return {
            "mime": mime,
            "base64": b64,
            "meta": {
                "comic_title": req.comic_title,
                "style": req.style,
                "pages": len(req.pages),
                "artifact": "pdf" if req.return_pdf else "zip",
            },
        }

    elif mode == "signed_url":
        info = upload_to_gcs(out_path)  # requires GCS_BUCKET + service account
        return {
            "asset": info,  # whatever your upload_to_gcs returns (url, bucket, key, etc.)
            "meta": {
                "comic_title": req.comic_title,
                "style": req.style,
                "pages": len(req.pages),
                "artifact": "pdf" if req.return_pdf else "zip",
            },
        }

    else:
        raise HTTPException(status_code=400, detail=f"unknown return_mode: {mode}")
