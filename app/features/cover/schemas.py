# app/features/cover/schemas.py
from pydantic import BaseModel, Field
from typing import Literal, Optional

class GenerateCoverRequest(BaseModel):
    cover_art_description: str = Field(..., min_length=5, description="Detailed cover prompt")
    user_theme: str = Field(..., min_length=1, description="Style/theme guidance")
    title: str
    tagline: str
    image_base64: Optional[str] = Field(None, description="Optional PNG/JPEG base64 (raw or data URL)")
    return_mode: Literal["signed_url", "inline", "base64"] = "signed_url"
