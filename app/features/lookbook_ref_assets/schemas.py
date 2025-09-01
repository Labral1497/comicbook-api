# app/features/lookbook_ref_assets/schemas.py
from typing import Dict, List, Optional, Literal, Union
from pydantic import BaseModel, Field

from app.features.lookbook_seed.schemas import ReferenceAsset, LookbookDoc
from app.lib.gcs_inventory import GCSInfo

Kind = Literal["character", "location", "prop", "unknown"]

class GenerateRefAssetsRequest(BaseModel):
    job_id: str
    ids: List[str] = Field(..., description="Lookbook IDs to (ensure) have ref assets")
    force: bool = Field(False, description="Regenerate even if assets already exist for the requested types")
    asset_types: Dict[str, List[str]] = Field(default_factory=dict)
    user_theme: Optional[str] = Field(None, description="Global style to match (same as cover)")

    # ✅ Keep only per-ID reference overrides (single URI or list).
    reference_images_by_id: Dict[str, Union[str, List[str]]] = Field(
        default_factory=dict,
        description="Per-ID reference override. Value may be a single URI or a list; first valid is used."
    )

    # Optional, but helpful if legacy callers still send extra fields.
    model_config = {"extra": "ignore"}

class RefAssetResultItem(BaseModel):
    id: str
    kind: Kind
    generated: List[ReferenceAsset] = Field(default_factory=list)
    skipped_types: List[str] = Field(default_factory=list)
    message: Optional[str] = None

class GenerateRefAssetsResponse(BaseModel):
    job_id: str
    results: List[RefAssetResultItem]
    lookbook_gcs: Optional[GCSInfo] = None

# --- Cleanup API ---

class CleanAssetsRequest(BaseModel):
    job_id: str
    ids: List[str]
    asset_types: Dict[str, List[str]] = Field(default_factory=dict)  # {"char_x": ["portrait","turnaround"]} or {"char_x":["*"]}
    include_cover: bool = False
    delete_local: bool = True
    delete_gcs: bool = True
    dry_run: bool = False
    prune_empty_entities: bool = True

class CleanAssetsResultItem(BaseModel):
    id: str
    kind: str
    removed_types: List[str] = Field(default_factory=list)
    skipped_types: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

class CleanAssetsResponse(BaseModel):
    job_id: str
    results: List[CleanAssetsResultItem]
    lookbook_gcs: Optional[GCSInfo] = None
