# app/features/lookbook_seed/router.py
from fastapi import APIRouter, HTTPException
from app.logger import get_logger
from .schemas import SeedFromCoverRequest, SeedFromCoverResponse
from .service import seed_from_cover

router = APIRouter(prefix="/api/v1", tags=["lookbook"])
log = get_logger(__name__)

@router.post("/lookbook/seed-from-cover", status_code=201, response_model=SeedFromCoverResponse)
async def lookbook_seed_from_cover(req: SeedFromCoverRequest) -> SeedFromCoverResponse:
    """
    Seed initial Lookbook entries (with or without a cover image).
    - Creates/updates jobs/{job_id}/lookbook.json
    - Upserts entities from `initial_ids` using display names from `hints`
    - If a cover image is provided, attaches it as a 'cover' ReferenceAsset
    - Injects `notes[id]` into visual_canon.notes when present
    """
    try:
        return seed_from_cover(req)
    except Exception as e:
        log.exception(f"lookbook seed-from-cover failed: {e}")
        raise HTTPException(status_code=500, detail="lookbook seed-from-cover failed")
