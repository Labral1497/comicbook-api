from fastapi import FastAPI
from app.features.story_ideas.router import router as story_ideas_router
from app.features.cover.router import router as cover_router
from app.features.cover_script.router import router as cover_script_router
from app.features.full_script.router import router as full_script_router
from app.features.pages.router import router as pages_router  # optional

app = FastAPI(title="Comics API")

app.include_router(story_ideas_router)
app.include_router(cover_router)
app.include_router(cover_script_router)
app.include_router(full_script_router)
app.include_router(pages_router)
