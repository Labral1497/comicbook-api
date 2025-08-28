# app/features/full_script/router.py
from fastapi import APIRouter, HTTPException
import json, os, uuid
from typing import Any, Dict
from app.logger import get_logger
from app.lib.paths import make_job_dir_with_id
from app.lib.gcs_inventory import upload_json_to_gcs
from .schemas import FullScriptRequest, FullScriptPagesResponse
from .service import generate_full_script  # your function that calls LLM and parses

router = APIRouter(prefix="/api/v1", tags=["full-script"])
log = get_logger(__name__)

@router.post("/generate/comic/full-script", status_code=201)
async def full_script_create_job(req: FullScriptRequest) -> Dict[str, Any]:
    """
    Generate the full script and assign a fresh job_id.
    Persist script.json under that job and upload to GCS.
    """
    # 1) Generate script (returns FullScriptPagesResponse)
    script: FullScriptPagesResponse = await generate_full_script(req)

    # 2) Create job id + directory
    job_id, workdir = make_job_dir_with_id()

    # 3) Save script.json locally for reproducibility
    script_path = os.path.join(workdir, "script.json")
    with open(script_path, "w") as f:
        json.dump(json.loads(script.model_dump_json()), f, ensure_ascii=False, indent=2)

    # 4) Upload to GCS under this job
    try:
        gcs_info = upload_json_to_gcs(
            data=json.loads(script.model_dump_json()),
            object_name=f"jobs/{job_id}/script.json",
            subdir="jobs",
            filename_hint="script.json",
            cache_control="no-cache",
            make_signed_url=True,
        )
    except Exception as e:
        # Don’t fail the endpoint on upload errors—return local info
        log.exception(f"Failed to upload script.json to GCS: {e}")
        gcs_info = None

    # 5) Return job_id + script + pointers to comic-generation endpoint
    return {
        "job_id": job_id,
        "script": script.model_dump(),   # the parsed JSON (same schema)
        "script_gcs": gcs_info,          # may be None if upload failed
        "next": {
            "enqueue_comic_url": f"/api/v1/generate/comic",
            "note": "Pass this job_id in the body so pages & final artifact are saved under the same job."
        }
    }
