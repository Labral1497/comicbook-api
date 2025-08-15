# app/__init__.py
from .config import config, make_job_dir
from .logger import get_logger
from .main import  generate_pages, make_pdf, story_ideas, generate_comic_cover, generate_full_script
from .schemas import ComicRequest, StoryIdeasRequest, StoryIdeasResponse, StoryIdea, FullScriptResponse, FullScriptRequest
from .api import app  # if the instance is defined in app/api.py


__all__ = ["app",
           "config",
           "make_job_dir",
           "get_logger",
           "generate_pages",
           "make_pdf",
           "ComicRequest",
           "StoryIdeasRequest",
           "StoryIdeasResponse",
           "StoryIdea",
           "story_ideas",
           "generate_comic_cover",
           "FullScriptRequest",
           "FullScriptResponse",
           "generate_full_script"
           ]
