from typing import List, Literal
from pydantic import BaseModel, Field, field_validator
from app.features.full_script.schemas import Page

class ComicRequest(BaseModel):
    comic_title: str
    style: str
    pages: List[Page]
    return_pdf: bool = False
    image_ref: str = Field(None, description="PNG/JPEG base64")
    return_mode: Literal["inline", "base64", "signed_url"] = "inline"
