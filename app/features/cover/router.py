# app/features/cover/router.py
import base64
import os
import shutil
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.lib.gcs_inventory import _decode_image_b64, upload_to_gcs
from .schemas import GenerateCoverRequest
from .service import generate_comic_cover
from app.config import config
from app.lib.fs import make_job_dir
from app.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["cover"])

@router.post("/generate/comic/cover")
async def cover_endpoint(req: GenerateCoverRequest, background_tasks: BackgroundTasks):
    out_path = f"data/cover_{req.title.replace(' ', '_')}.png"
    # log.info("yoyo")
    # Make job dir; auto-clean unless KEEP_OUTPUTS=true
    workdir = make_job_dir()
    if not config.keep_outputs:
        background_tasks.add_task(shutil.rmtree, str(workdir), ignore_errors=True)

    # Generate cover
    out_path = os.path.join(workdir, "cover.png")
    try:
        generate_comic_cover(req=req, out_path=out_path, workdir=workdir)
    except Exception as e:
        # log.exception("Cover generation failed")  # if you have logging set up
        raise HTTPException(500, f"Cover generation failed: {e}")
    # log.debug("koko3")
    mode = req.return_mode
    if mode == "inline":
        return FileResponse(out_path, media_type="image/png", filename="comic_cover.png")
    elif mode == "base64":
        # log.debug("koko3")
        with open(out_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return {"mime": "image/png", "base64": b64}
    elif mode == "signed_url":
        info = upload_to_gcs(out_path)  # requires GCS_BUCKET and service account perms
        return {
            "cover": info,
            "meta": {
                "user_theme": req.user_theme,
                "cover_art_description": req.cover_art_description,
            },
        }
    else:
        raise HTTPException(422, "return_mode must be one of: signed_url, inline, base64")
