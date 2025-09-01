from fastapi import APIRouter, HTTPException, Request
import json, os
from app.logger import get_logger
from app.config import config
from app.lib.paths import ensure_job_dir, job_dir
from app.lib.gcs_inventory import upload_json_to_gcs, download_gcs_object_to_file
from app.lib.cloud_tasks import create_task
from .schemas import CleanAssetsRequest, CleanAssetsResponse, GenerateRefAssetsRequest, GenerateRefAssetsResponse
from .service import clean_lookbook_assets, generate_ref_assets

router = APIRouter(prefix="/api/v1", tags=["lookbook"])
log = get_logger(__name__)

@router.post("/lookbook/enqueue-ref-assets", status_code=202)
async def enqueue_ref_assets(req: GenerateRefAssetsRequest) -> dict:
    """
    Fire-and-forget: persists request.json and enqueues a Cloud Task to do the work.
    """
    job_id = req.job_id
    workdir = ensure_job_dir(job_id)

    # save local request.json (source of truth for worker)
    req_path = os.path.join(workdir, "ref_assets_request.json")
    with open(req_path, "w") as f:
        json.dump(req.model_dump(), f, indent=2)

    # upload to GCS so worker can pull it
    req_info = upload_json_to_gcs(
        req.model_dump(),
        object_name=f"jobs/{job_id}/ref_assets_request.json",
        subdir="jobs",
        filename_hint="ref_assets_request.json",
        cache_control="no-cache",
        make_signed_url=False,
    )

    task_url = f"{config.public_base_url}/api/v1/tasks/worker/lookbook/ref-assets/{job_id}"
    task = create_task(
        queue=config.tasks_queue,
        url=task_url,
        payload={"job_id": job_id, "request_gcs": req_info["gs_uri"]},
        schedule_in_seconds=0,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "worker_url": task_url,
        "request_gcs": req_info["gs_uri"],
        "task_name": task.name,
    }

@router.post("/tasks/worker/lookbook/ref-assets/{job_id}")
async def worker_ref_assets(job_id: str, request: Request) -> GenerateRefAssetsResponse:
    """
    Cloud Task target: loads request and runs generation. Idempotent-ish: safe to retry.
    """
    try:
        workdir = job_dir(job_id)
        body = await request.json()
        request_gcs = body.get("request_gcs")

        req_path = os.path.join(workdir, "ref_assets_request.json")
        if not os.path.exists(req_path):
            if not request_gcs:
                raise HTTPException(400, "missing request_gcs")
            download_gcs_object_to_file(request_gcs, req_path)

        with open(req_path, "r") as f:
            req_dict = json.load(f)
        req = GenerateRefAssetsRequest(**req_dict)

        return generate_ref_assets(req)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception(f"worker ref-assets failed: {e}")
        raise HTTPException(500, "worker ref-assets failed")


@router.post("/lookbook/clean-assets", response_model=CleanAssetsResponse)
async def lookbook_clean_assets(req: CleanAssetsRequest) -> CleanAssetsResponse:
    try:
        return clean_lookbook_assets(req)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception(f"lookbook clean-assets failed: {e}")
        raise HTTPException(500, "lookbook clean-assets failed")
