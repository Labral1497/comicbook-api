# app/schemas.py
from typing import List, Literal, Optional, Dict
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
    # Core
    name: str = Field(..., description="Main character name")            # [User_Name]
    theme: str = Field(..., description="Comic theme")                   # [User_Theme]
    gender: Optional[str] = Field(None, description="Main character gender")            # [User_Gender]
    purpose_of_gift: Optional[str] = Field(None, description="Occasion / Purpose of Gift")  # [Purpose_Of_Gift]
    user_answers_list: Dict[str, str] = Field(default_factory=dict, description="Comedic Q&A pairs (question → answer)")

class StoryIdea(BaseModel):
    title: str
    synopsis: str
class StoryIdeasResponse(BaseModel):
    ideas: List[StoryIdea]

class FullScriptRequest(BaseModel):
    title: str
    synopsis: str = Field(..., description="Story Synopsis to Adapt")
    user_name: str = Field(..., description="Main Character Name")
    user_gender: str = Field(..., description="Main Character Gender")
    character_description: str = Field(..., description="Definitive Character Description for illustration consistency")
    page_count: int = Field(..., gt=0, description="Total Page Count")
    user_theme: str = Field(..., description="Core Theme")
    user_answers_list: Dict[str, str] = Field(default_factory=dict, description="Comedic Q&A pairs (question → answer)")

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

class FullScriptPagesResponse(BaseModel):
    title: str
    tagline: str
    cover_art_description: str
    pages: List[ScriptPage]

class GenerateCoverRequest(BaseModel):
    cover_art_description: str = Field(..., min_length=5, description="Detailed cover prompt")
    user_theme: str = Field(..., min_length=1, description="Style/theme guidance")
    title: str
    tagline: str
    # Optional image provided as base64 or data URL (e.g., 'data:image/png;base64,....')
    image_base64: Optional[str] = Field(
        None, description="Optional PNG/JPEG base64 (raw or data URL)"
    )
    # How the API returns the result
    return_mode: Literal["signed_url", "inline", "base64"] = "signed_url"

class CoverScriptRequest(BaseModel):
    title: str = Field(..., description="The chosen comic idea title")
    synopsis: str = Field(..., description="The chosen comic idea synopsis")
    name: str = Field(..., description="Main character name")  # [User_Name]
    gender: Optional[str] = Field(None, description="Main character gender")  # [User_Gender]
    page_count: int = Field(..., description="Total page count")  # [Page_Count]
    theme: str = Field(..., description="Core comic theme")  # [User_Theme]
    user_answers_list: Dict[str, str] = Field(
        default_factory=dict, description="Comedic Q&A pairs (question → answer)"
    )

class CoverScriptResponse(BaseModel):
    title: str = Field(..., description="A catchy and funny title for the comic")
    tagline: str = Field(..., description="A hilarious subtitle or punchy quote")
    cover_art_description: str = Field(
        ...,
        description=(
            "A highly detailed description of a dynamic and exciting cover image. "
            "Describe the character's pose, expression, the background, the mood, "
            "and the central action. Like a 'movie poster' for the story."
        )
    )
    story_summary: str = Field(
        ...,
        description=(
            "A concise summary of the full story arc, 3–8 sentences long. "
            "Expands on the chosen synopsis and sets the stage for the full script."
        )
    )
