import base64
import hashlib
import json
import os
import shutil
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.features.lookbook_ref_assets.service import _load_lookbook, _save_lookbook
from app.features.lookbook_seed.schemas import ReferenceAsset
from app.lib.gcs_inventory import upload_to_gcs, upload_json_to_gcs  # <-- NEW import
from .schemas import GenerateCoverRequest
from .service import generate_comic_cover
from app.config import config
from app.lib.fs import make_job_dir
from app.logger import get_logger

# NEW: prefer job_id-based dirs (same as your full-script flow)
from app.lib.paths import ensure_job_dir, make_job_dir_with_id  # <-- NEW

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["cover"])

def _slugify(s: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip().lower()).strip("_") or "x"

@router.post("/generate/comic/cover")
async def cover_endpoint(req: GenerateCoverRequest, background_tasks: BackgroundTasks):
    # 1) Resolve job dir
    if req.job_id:
        job_id = req.job_id
        workdir = ensure_job_dir(job_id)
    else:
        job_id, workdir = make_job_dir_with_id()

    cover_png = os.path.join(workdir, "cover.png")            # canonical local path
    hash_path = os.path.join(workdir, "cover.hash")           # stores last fingerprint
    rev_path  = os.path.join(workdir, "cover.rev")            # tracks version integer

    # 2) Fingerprint the inputs for idempotency
    # (include whether an image ref was supplied; not the bytes themselves)
    fp = hashlib.sha256(
        "|".join([
            req.title, req.tagline, req.cover_art_description, req.user_theme,
            "has_ref" if bool(req.image_base64) else "no_ref"
        ]).encode("utf-8")
    ).hexdigest()

    # 3) If inputs didn’t change and we have an existing cover AND overwrite/versioned are off -> no-op
    if (not req.overwrite and not req.versioned
        and os.path.exists(cover_png) and os.path.exists(hash_path)
        and open(hash_path).read().strip() == fp):
        # Just re-sign the existing GCS object
        object_name = f"jobs/{job_id}/cover.png"
        # (Optional) you can avoid re-upload by signing directly via bucket.blob(object_name)
        info = upload_to_gcs(cover_png, object_name=object_name, subdir="jobs")
        return {
            "job_id": job_id,
            "cover": info,
            "cover_image_url": info.get("signed_url"),
            "seed_request": {
                "job_id": job_id,
                "cover_gs_uri": info["gs_uri"],
                "initial_ids": {"characters": [], "locations": [], "props": []},
                "hints": {}
            }
        }

    # 4) Generate (or regenerate) the cover image locally
    out_path = os.path.join(workdir, "cover.tmp.png")
    try:
        generate_comic_cover(req=req, out_path=out_path, workdir=workdir)
    except Exception as e:
        raise HTTPException(500, f"Cover generation failed: {e}")

    # atomically set/replace canonical cover
    os.replace(out_path, cover_png)
    with open(hash_path, "w") as f:
        f.write(fp)

    # 5) Upload canonical cover.png
    canonical_obj = f"jobs/{job_id}/cover.png"
    info_canonical = upload_to_gcs(cover_png, object_name=canonical_obj, subdir="jobs")

    # 6) If versioned, also write a new version object cover_v{n}.png
    if req.versioned:
        rev = 1
        if os.path.exists(rev_path):
            try:
                rev = int(open(rev_path).read().strip()) + 1
            except Exception:
                rev = 1
        with open(rev_path, "w") as f:
            f.write(str(rev))

        versioned_obj = f"jobs/{job_id}/cover_v{rev}.png"
        _ = upload_to_gcs(cover_png, object_name=versioned_obj, subdir="jobs")

    # 7) OPTIONAL: keep lookbook cover refs in sync (if lookbook already exists)
    lb_path = os.path.join(workdir, "lookbook.json")
    if os.path.exists(lb_path):
        try:
            lb = _load_lookbook(lb_path)
            # For every entity, ensure a type="cover" asset exists and has gs_uri set to the canonical object
            updated = False
            def _touch_assets(lst):
                nonlocal updated
                for ent in lst:
                    ras = getattr(ent, "reference_assets", None) or []
                    found = False
                    for ra in ras:
                        if getattr(ra, "type", "") == "cover":
                            if getattr(ra, "gs_uri", None) != info_canonical["gs_uri"]:
                                ra.gs_uri = info_canonical["gs_uri"]
                                updated = True
                            # optional: refresh url to the fresh signed URL
                            ra.url = info_canonical.get("signed_url", ra.url)
                            found = True
                            break
                    if not found:
                        ras.append(ReferenceAsset(type="cover",
                                                  url=info_canonical.get("signed_url"),
                                                  gs_uri=info_canonical["gs_uri"]))
                        setattr(ent, "reference_assets", ras)
                        updated = True

            _touch_assets(getattr(lb, "characters", []))
            _touch_assets(getattr(lb, "locations", []))
            _touch_assets(getattr(lb, "props", []))

            if updated:
                _save_lookbook(lb_path, lb)
                upload_json_to_gcs(
                    data=json.loads(lb.model_dump_json()),
                    object_name=f"jobs/{job_id}/lookbook.json",
                    subdir="jobs",
                    filename_hint="lookbook.json",
                    cache_control="no-cache",
                    make_signed_url=True,
                )
        except Exception as e:
            log.warning(f"Failed to sync lookbook cover refs: {e}")

    # 8) Build seed payload (so the next step can seed/update lookbook using the stable gs://)
    seed_request = {
        "job_id": job_id,
        "cover_gs_uri": info_canonical["gs_uri"],   # stable
        "cover_image_url": info_canonical.get("signed_url"),
        "initial_ids": {
            "characters": [], "locations": [], "props": []
        },
        "hints": {}
    }

    # 9) Return
    return {
        "job_id": job_id,
        "cover": info_canonical,
        "cover_image_url": info_canonical.get("signed_url"),
        "seed_request": seed_request,
        "meta": {
            "user_theme": req.user_theme,
            "cover_art_description": req.cover_art_description,
            "title": req.title,
            "tagline": req.tagline
        }
    }
