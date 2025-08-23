# app/features/cover_script/schemas.py
from pydantic import BaseModel, Field
from typing import Dict, Optional

class CoverScriptRequest(BaseModel):
    title: str = Field(..., description="The chosen comic idea title")
    synopsis: str = Field(..., description="The chosen comic idea synopsis")
    name: str = Field(..., description="Main character name")
    gender: Optional[str] = Field(None, description="Main character gender")
    page_count: int = Field(..., description="Total page count")
    theme: str = Field(..., description="Core comic theme")
    user_answers_list: Dict[str, str] = Field(default_factory=dict, description="Comedic Q&A pairs (question → answer)")

class CoverScriptResponse(BaseModel):
    title: str
    tagline: str
    cover_art_description: str
    story_summary: str
