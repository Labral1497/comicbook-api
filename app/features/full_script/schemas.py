# app/features/full_script/schemas.py
from typing import Dict, List
from pydantic import BaseModel, Field

class Panel(BaseModel):
    panel_number: int
    art_description: str
    dialogue: str
    narration: str
    sfx: str

class Page(BaseModel):
    page_number: int
    panels: List[Panel]

class FullScriptResponse(BaseModel):
    title: str
    tagline: str
    cover_art_description: str
    pages: List[Page]

class FullScriptRequest(BaseModel):
    title: str
    synopsis: str
    user_name: str
    user_gender: str
    page_count: int
    user_theme: str
    user_answers_list: Dict[str, str] = Field(default_factory=dict)
    min_panels_per_page: int
    max_panels_per_page: int
