from fastapi import APIRouter
from app.lib.cleanup import sweep_finished_jobs
from app.lib.paths import data_dir
from app.config import config

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

@router.post("/sweep")
async def sweep():
    base = data_dir()
    removed = sweep_finished_jobs(base, ttl_hours=config.sweep_ttl_hours)
    return {"removed": removed, "base_dir": base}
