from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator

# ----- Lookbook delta stubs -----
# Minimal requirements so server-side derivation can populate safely.

class CharacterToAdd(BaseModel):
    id: str
    display_name: str
    role: str = ""                  # present key, allow empty string if you like
    visual_stub: str                # required
    needs_concept_sheet: bool = True

class LocationToAdd(BaseModel):
    id: str
    name: str
    visual_stub: str = ""  # default if missing

    @field_validator("visual_stub", mode="before")
    @classmethod
    def coerce_none_to_empty(cls, v):
        return "" if v is None else v
    needs_concept_sheet: bool = True

class PropToAdd(BaseModel):
    id: str
    name: str
    visual_stub: str                # required
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
    characters: list[str] = Field(default_factory=list)  # char_* IDs
    props: list[str] = Field(default_factory=list)        # prop_* IDs
    location_id: str | None = None                        # "" or loc_* ID

class Page(BaseModel):
    page_number: int
    panels: list[Panel]
    location_id: str | None = None                        # "" or loc_* ID
    characters: list[str] = Field(default_factory=list)   # optional page-level mentions
    props: list[str] = Field(default_factory=list)

class FullScriptPagesResponse(BaseModel):
    pages: list[Page]
    lookbook_delta: LookbookDelta = LookbookDelta()

class FullScriptRequest(BaseModel):
    job_id: str | None = None
    title: str
    tagline: str
    story_summary: str
    user_name: str
    user_gender: str
    page_count: int
    user_theme: str
    user_answers_list: Dict[str, str] = Field(default_factory=dict)
    min_panels_per_page: int = 3
    max_panels_per_page: int = 6
