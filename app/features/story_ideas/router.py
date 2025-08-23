# app/features/story_ideas/router.py
from fastapi import APIRouter
from .schemas import StoryIdeasRequest, StoryIdeasResponse
from .service import generate_story_ideas

router = APIRouter(prefix="/api/v1", tags=["story-ideas"])

@router.post("/generate/story-ideas", response_model=StoryIdeasResponse)
async def story_ideas_endpoint(req: StoryIdeasRequest):
    return await generate_story_ideas(req)
