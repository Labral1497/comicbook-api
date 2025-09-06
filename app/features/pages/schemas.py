from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from app.features.full_script.schemas import Page

class ComicRequest(BaseModel):
    job_id: str
    comic_title: str
    style: str
    pages: Optional[List[Page]] = None

    # ✅ optional pointer to script in GCS (or signed https URL)
    script_gcs_uri: Optional[str] = Field(
        default=None,
        description="gs://... or https://... to script.json containing {'pages': [...]}"
    )
    return_pdf: bool = False
    image_ref: Optional[str] = Field(
        None,
        description="PNG/JPEG base64 (raw or data URL). Optional; will fall back to gs://.../cove.png",
    )
    return_mode: Literal["inline", "base64", "signed_url"] = "inline"
