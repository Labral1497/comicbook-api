# app/features/cover/schemas.py
from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class GenerateCoverRequest(BaseModel):
    job_id: Optional[str] = None
    cover_art_description: str = Field(..., min_length=5, description="Detailed cover prompt")
    user_theme: str = Field(..., min_length=1, description="Style/theme guidance")
    title: str
    tagline: str
    image_base64: Optional[str] = Field(None, description="Optional PNG/JPEG base64")
    return_mode: Literal["signed_url", "inline", "base64"] = "signed_url"
    main_character_name: Optional[str] = Field(None, description="Display name for char_main (e.g., 'Roey')")
    extra_character_names: List[str] = Field(default_factory=list, description="Other visible people on the cover")
    cover_location_hint: Optional[str] = Field(None, description="Primary location visible on the cover (e.g., 'Rooftop')")
    cover_props: List[str] = Field(default_factory=list, description="Distinct props visible on the cover (e.g., 'Laptop')")
    overwrite: bool = True                              # NEW: overwrite cover.png if inputs changed
    versioned: bool = False                             # NEW: also write cover_v{n}.png when inputs change
