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
from app.lib.pdf import make_pdf

router = APIRouter(prefix="/api/v1", tags=["comic"])
log = logger.get_logger(__name__)

@router.post("/generate/comic")
async def generate_comic(
    background_tasks: BackgroundTasks,
    payload: str = Form(...),            # JSON string for ComicRequest
    image: UploadFile = File(None),      # optional file upload
):
    workdir = make_job_dir()
    log.info(f"Working directory created: {workdir}")

    # Auto-clean temp directory after response is sent
    if not config.keep_outputs:
        background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)

    # Parse & validate JSON payload
    try:
        req = ComicRequest(**json.loads(payload))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid payload JSON: {e}")

    # Save uploaded image if present
    ref_path = None
    if image:
        if image.content_type not in {"image/png", "image/jpeg"}:
            log.error("Invalid image format")
            raise HTTPException(status_code=400, detail="image must be PNG or JPEG")
        ref_path = os.path.join(workdir, "ref.png")
        with open(ref_path, "wb") as f:
            f.write(await image.read())
        log.info(f"Reference image saved at: {ref_path}")

    # Build page prompts (mirrors your original logic)
    prepared_prompts = build_page_prompts(req, ref_path=ref_path)

    # Generate images
    files = render_pages_from_prompts(prepared_prompts, workdir=workdir)
    if not files:
        raise HTTPException(status_code=500, detail="no pages were generated")

    # Return PDF or ZIP
    if req.return_pdf:
        pdf_name = os.path.join(workdir, f"comic_{uuid.uuid4().hex}.pdf")
        make_pdf(files, pdf_name=pdf_name)
        return FileResponse(pdf_name, media_type="application/pdf", filename="comic.pdf")

    zip_base = os.path.join(workdir, "pages")
    shutil.make_archive(zip_base, "zip", workdir)
    return FileResponse(f"{zip_base}.zip", media_type="application/zip", filename="comic_pages.zip")
