from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# ----- Lookbook delta stubs -----

class CharacterToAdd(BaseModel):
    id: str
    display_name: str
    role: Optional[str] = None
    visual_stub: Optional[str] = None
    needs_concept_sheet: bool = True


class LocationToAdd(BaseModel):
    id: str
    name: str
    visual_stub: Optional[str] = None
    needs_concept_sheet: bool = True


class PropToAdd(BaseModel):
    id: str
    name: str
    visual_stub: Optional[str] = None
    needs_concept_sheet: bool = True


class LookbookDelta(BaseModel):
    characters_to_add: List[CharacterToAdd] = Field(default_factory=list)
    locations_to_add: List[LocationToAdd] = Field(default_factory=list)
    props_to_add: List[PropToAdd] = Field(default_factory=list)


# ----- Script models -----

class Panel(BaseModel):
    panel_number: int
    art_description: str
    dialogue: str
    narration: str
    sfx: str
    characters: List[str] = Field(default_factory=list)  # char_* ids
    props: List[str] = Field(default_factory=list)       # prop_* ids
    location_id: Optional[str] = None                    # "" or loc_*


class Page(BaseModel):
    page_number: int
    panels: List[Panel]
    location_id: Optional[str] = None                    # "" or loc_*
    characters: List[str] = Field(default_factory=list)  # char_* ids (optional per page)
    props: List[str] = Field(default_factory=list)       # prop_* ids (optional per page)


class FullScriptPagesResponse(BaseModel):
    pages: List[Page]
    lookbook_delta: LookbookDelta = LookbookDelta()


class FullScriptRequest(BaseModel):
    job_id: Optional[str] = None
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
