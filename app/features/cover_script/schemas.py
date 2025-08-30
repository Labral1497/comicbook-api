# app/features/cover_script/schemas.py
from pydantic import BaseModel, Field
from typing import Dict, Optional, List

class CoverScriptRequest(BaseModel):
    title: str = Field(..., description="The chosen comic idea title")
    synopsis: str = Field(..., description="The chosen comic idea synopsis")
    name: str = Field(..., description="Main character name")
    gender: Optional[str] = Field(None, description="Main character gender")
    page_count: int = Field(..., description="Total page count")
    theme: str = Field(..., description="Core comic theme")
    user_answers_list: Dict[str, str] = Field(default_factory=dict, description="Comedic Q&A pairs (question → answer)")

# --- Lookbook seeding helpers (aligns with /lookbook/seed-from-cover) ---

class InitialIds(BaseModel):
    characters: List[str] = Field(default_factory=list)
    locations: List[str]  = Field(default_factory=list)
    props: List[str]      = Field(default_factory=list)

class CoverEntities(BaseModel):
    characters: List[str] = Field(default_factory=list)  # e.g., ["char_main", "char_yaron"]
    locations: List[str]  = Field(default_factory=list)  # e.g., ["loc_rooftop"]
    props: List[str]      = Field(default_factory=list)  # e.g., ["prop_laptop"]
    hints: Dict[str, str] = Field(default_factory=dict)  # id -> display name (e.g., {"char_main":"Roey"})
    notes: Dict[str, str] = Field(                      # id -> short canonical description (from Q&A if any)
        default_factory=dict,
        description="Optional 1–2 sentence descriptors per ID derived from Q&A/synopsis"
    )

class SeedRequestTemplate(BaseModel):
    initial_ids: InitialIds = InitialIds()
    hints: Dict[str, str] = Field(default_factory=dict)

class CoverScriptResponse(BaseModel):
    title: str
    tagline: str
    cover_art_description: str
    story_summary: str
    # NEW: data to seed Lookbook before/alongside cover generation
    cover_entities: CoverEntities
    seed_request_template: SeedRequestTemplate
