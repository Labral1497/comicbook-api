from fastapi import APIRouter
import json, os
from typing import Any, Dict
from app.logger import get_logger
from app.lib.paths import ensure_job_dir, make_job_dir_with_id
from app.lib.gcs_inventory import upload_json_to_gcs

from .schemas import FullScriptRequest, FullScriptPagesResponse
from .service import generate_full_script

# reuse lookbook helpers & models
from app.features.lookbook_ref_assets.service import _load_lookbook as _lb_load, _save_lookbook as _lb_save
from app.features.lookbook_seed.schemas import LookbookDoc, LookbookCharacter, LookbookLocation, LookbookProp

router = APIRouter(prefix="/api/v1", tags=["full-script"])
log = get_logger(__name__)

def _apply_delta_to_lookbook(lb: LookbookDoc, script_delta) -> LookbookDoc:
    def present(lst, _id): return any(getattr(x, "id", None) == _id for x in lst)

    for c in script_delta.characters_to_add or []:
        if not present(lb.characters, c.id):
            lb.characters.append(
                LookbookCharacter(
                    id=c.id,
                    display_name=c.display_name,
                    role=c.role or None,
                    visual_canon={"notes": (c.visual_stub or "").strip() or "Added by script"},
                    reference_assets=[],
                    created_from="script_v1",
                )
            )

    for l in script_delta.locations_to_add or []:
        if not present(lb.locations, l.id):
            lb.locations.append(
                LookbookLocation(
                    id=l.id,
                    name=l.name,
                    visual_canon={"notes": (l.visual_stub or "").strip() or "Added by script"},
                    reference_assets=[],
                    created_from="script_v1",
                )
            )

    for p in script_delta.props_to_add or []:
        if not present(lb.props, p.id):
            lb.props.append(
                LookbookProp(
                    id=p.id,
                    name=p.name,
                    visual_canon={"notes": (p.visual_stub or "").strip() or "Added by script"},
                    reference_assets=[],
                    created_from="script_v1",
                )
            )
    return lb

@router.post("/generate/comic/full-script", status_code=201)
async def full_script_create_job(req: FullScriptRequest) -> Dict[str, Any]:
    """
    Generate the full script using the existing lookbook (if job_id given).
    Save script.json (pages only) to GCS.
    Apply lookbook_delta (derived from recurring usage) to lookbook.json and upload it.
    Return job_id, script GCS, lookbook_delta, and lookbook GCS pointers.
    """
    if req.job_id:
        job_id = req.job_id
        workdir = ensure_job_dir(job_id)
    else:
        job_id, workdir = make_job_dir_with_id()
        req.job_id = job_id

    script: FullScriptPagesResponse = await generate_full_script(req)

    # Save script.json (pages only)
    script_only = {"pages": [p.model_dump() for p in script.pages]}
    with open(os.path.join(workdir, "script.json"), "w") as f:
        json.dump(script_only, f, ensure_ascii=False, indent=2)

    # Upload script.json
    try:
        script_gcs = upload_json_to_gcs(
            data=script_only,
            object_name=f"jobs/{job_id}/script.json",
            subdir="jobs",
            filename_hint="script.json",
            cache_control="no-cache",
            make_signed_url=True,
        )
    except Exception as e:
        log.exception(f"Failed to upload script.json to GCS: {e}")
        script_gcs = None

    # Apply derived delta to lookbook and upload
    lb = _lb_load(os.path.join(workdir, "lookbook.json")) or LookbookDoc()
    lb = _apply_delta_to_lookbook(lb, script.lookbook_delta)
    _lb_save(os.path.join(workdir, "lookbook.json"), lb)

    try:
        lookbook_gcs = upload_json_to_gcs(
            data=json.loads(lb.model_dump_json()),
            object_name=f"jobs/{job_id}/lookbook.json",
            subdir="jobs",
            filename_hint="lookbook.json",
            cache_control="no-cache",
            make_signed_url=True,
        )
    except Exception as e:
        log.exception(f"Failed to upload lookbook.json to GCS: {e}")
        lookbook_gcs = None

    return {
        "job_id": job_id,
        "script_gcs": script_gcs,
        "lookbook_delta": script.lookbook_delta.model_dump(),
        "lookbook_gcs": lookbook_gcs,
        "next": {
            "enqueue_ref_assets_url": "/api/v1/lookbook/enqueue-ref-assets",
            "note": "Use lookbook_delta IDs (or any missing types) with force=true to create reference assets."
        },
    }
