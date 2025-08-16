# app/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

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
    character_description: str
    cover_art_description: str

class StoryIdeasResponse(BaseModel):
    ideas: List[StoryIdea]

class FullScriptRequest(BaseModel):
    chosen_story_idea: str = Field(..., description="Story Synopsis to Adapt")
    user_name: str = Field(..., description="Main Character Name")
    user_gender: str = Field(..., description="Main Character Gender")
    character_description: str = Field(..., description="Definitive Character Description for illustration consistency")
    page_count: int = Field(..., gt=0, description="Total Page Count")
    user_theme: str = Field(..., description="Core Theme")
    user_answers_list: List[str] = Field(default_factory=list, description="Comedic traits / joke sources")

    # NEW: user-provided panel bounds
    min_panels_per_page: int = Field(4, ge=1, description="Minimum panels per page")
    max_panels_per_page: int = Field(4, ge=1, description="Maximum panels per page")

    @model_validator(mode="after")
    def _check_panel_bounds(self):
        if self.max_panels_per_page < self.min_panels_per_page:
            raise ValueError("max_panels_per_page must be >= min_panels_per_page")
        # (Optional) put a soft upper limit if you want, e.g. <= 12
        return self

class ScriptPanel(BaseModel):
    panel_number: int
    art_description: str
    dialogue: str
    narration: str
    sfx: str

class ScriptPage(BaseModel):
    page_number: int
    panels: List[ScriptPanel]

class FullScriptResponse(BaseModel):
    title: str
    tagline: str
    cover_art_description: str
    pages: List[ScriptPage]
