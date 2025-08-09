# app/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

class Page(BaseModel):
    id: int = Field(..., ge=1)
    title: str
    panels: List[str]

    @field_validator("panels")
    @classmethod
    def panels_must_be_4(cls, v):
        if not isinstance(v, list) or len(v) != 4:
            raise ValueError("each page must have exactly 4 panels")
        if not all(isinstance(p, str) and p.strip() for p in v):
            raise ValueError("panels must be non-empty strings")
        return v

class ComicRequest(BaseModel):
    comic_title: str
    style: str
    character: str
    pages: List[Page]
    return_pdf: bool = False
    # Optional: allow a previously uploaded image reference URL/path
    image_ref: Optional[str] = None

class StoryIdeasRequest(BaseModel):
    name: str = Field(..., description="Main character name")
    theme: str
    job: str
    dream: str
    origin: str
    hobby: str
    catchphrase: str
    super_skill: str
    favorite_place: str
    taste_in_women: str

class StoryIdea(BaseModel):
    title: str
    synopsis: str

class StoryIdeasResponse(BaseModel):
    ideas: List[StoryIdea]
