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
    overwrite: bool = True                              # NEW: overwrite cover.png if inputs changed
    versioned: bool = False                             # NEW: also write cover_v{n}.png when inputs change
