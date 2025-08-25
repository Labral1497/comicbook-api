# app/features/full_script/router.py
from fastapi import APIRouter
from .schemas import FullScriptRequest, FullScriptPagesResponse
from .service import generate_full_script

router = APIRouter(prefix="/api/v1", tags=["full-script"])

@router.post("/generate/comic/full-script", response_model=FullScriptPagesResponse)
async def full_script_endpoint(req: FullScriptRequest) -> FullScriptPagesResponse:
    return await generate_full_script(req)
