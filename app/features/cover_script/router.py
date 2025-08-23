# app/features/cover_script/router.py
from fastapi import APIRouter
from .schemas import CoverScriptRequest, CoverScriptResponse
from .service import generate_cover_script

router = APIRouter(prefix="/api/v1", tags=["cover-script"])

@router.post("/generate/comic/cover-script", response_model=CoverScriptResponse)
async def cover_script_endpoint(req: CoverScriptRequest) -> CoverScriptResponse:
    return await generate_cover_script(req)
