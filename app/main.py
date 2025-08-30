from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.config import config
from app.features.story_ideas.router import router as story_ideas_router
from app.features.cover.router import router as cover_router
from app.features.cover_script.router import router as cover_script_router
from app.features.full_script.router import router as full_script_router
from app.features.pages.router import router as pages_router
from app.features.admin.router import router as admin_router
from app.features.lookbook_seed.router import router as lookbook_seed_router
from app.features.lookbook_ref_assets.router import router as lookbook_ref_assets_router
from fastapi.middleware.cors import CORSMiddleware

from app.lib.cleanup import sweep_finished_jobs
from app.lib.paths import data_dir


app = FastAPI(title="Comics API")

# set this to your real front-end origins
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://your-frontend-domain.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # use ["*"] only if you don't send cookies/Authorization
    allow_credentials=True,            # set False if you keep allow_origins=["*"]
    allow_methods=["*"],               # includes OPTIONS automatically
    allow_headers=["*"],               # allow Content-Type, Authorization, etc.
    expose_headers=["Content-Disposition"],  # for downloads via FileResponse
)

app.include_router(story_ideas_router)
app.include_router(cover_router)
app.include_router(cover_script_router)
app.include_router(full_script_router)
app.include_router(pages_router)
app.include_router(admin_router)
app.include_router(lookbook_seed_router)
app.include_router(lookbook_ref_assets_router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.sweep_jobs_on_startup:
        sweep_finished_jobs(data_dir(), ttl_hours=config.sweep_ttl_hours)
