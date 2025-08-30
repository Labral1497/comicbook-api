# app/features/full_script/schemas.py
from typing import Dict
from pydantic import BaseModel, Field

# ----- Lookbook delta stubs -----

class CharacterToAdd(BaseModel):
    id: str
    display_name: str
    role: str | None = None
    visual_stub: str | None = None
    needs_concept_sheet: bool = True

class LocationToAdd(BaseModel):
    id: str
    name: str
    visual_stub: str | None = None
    needs_concept_sheet: bool = True

class PropToAdd(BaseModel):
    id: str
    name: str
    visual_stub: str | None = None
    needs_concept_sheet: bool = True

class LookbookDelta(BaseModel):
    characters_to_add: list[CharacterToAdd] = Field(default_factory=list)
    locations_to_add: list[LocationToAdd] = Field(default_factory=list)
    props_to_add: list[PropToAdd] = Field(default_factory=list)

# ----- Script models -----

class Panel(BaseModel):
    panel_number: int
    art_description: str
    dialogue: str
    narration: str
    sfx: str
    # NEW: entity references per panel (optional)
    characters: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    location_id: str | None = None

class Page(BaseModel):
    page_number: int
    panels: list[Panel]
    # NEW: page-level entity declarations (optional; panels can override)
    location_id: str | None = None
    characters: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)

class FullScriptPagesResponse(BaseModel):
    pages: list[Page]
    # NEW: allows the writer to declare new entities needed
    lookbook_delta: LookbookDelta = LookbookDelta()

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
