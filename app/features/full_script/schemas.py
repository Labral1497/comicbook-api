# app/features/full_script/schemas.py
from typing import Dict
from pydantic import BaseModel, Field

class Panel(BaseModel):
    panel_number: int
    art_description: str
    dialogue: str
    narration: str
    sfx: str

class Page(BaseModel):
    page_number: int
    panels: list[Panel]

class FullScriptPagesResponse(BaseModel):
    pages: list[Page]

class FullScriptRequest(BaseModel):
    title: str
    tagline: str
    story_summary: str                 # <-- replaces 'synopsis'
    user_name: str
    user_gender: str
    page_count: int                    # [Page_Count]
    user_theme: str                    # [User_Theme]
    user_answers_list: Dict[str, str] = Field(default_factory=dict)  # Q&A dict
    min_panels_per_page: int = 3
    max_panels_per_page: int = 6
