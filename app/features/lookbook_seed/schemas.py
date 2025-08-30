from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.lib.gcs_inventory import GCSInfo

# --- Common ---

class ReferenceAsset(BaseModel):
    type: str  # e.g., "cover"
    url: Optional[str] = None            # signed/public https URL (may expire)
    gs_uri: Optional[str] = None         # stable gs://bucket/object

# Canon is intentionally loose — enriched later by concept sheets
class LookbookCharacter(BaseModel):
    id: str
    display_name: str
    role: Optional[str] = None
    visual_canon: Dict[str, str] = Field(default_factory=dict)
    reference_assets: List[ReferenceAsset] = Field(default_factory=list)
    created_from: str = "cover_v1"

class LookbookLocation(BaseModel):
    id: str
    name: str
    visual_canon: Dict[str, str] = Field(default_factory=dict)
    reference_assets: List[ReferenceAsset] = Field(default_factory=list)
    created_from: str = "cover_v1"

class LookbookProp(BaseModel):
    id: str
    name: str
    visual_canon: Dict[str, str] = Field(default_factory=dict)
    reference_assets: List[ReferenceAsset] = Field(default_factory=list)
    created_from: str = "cover_v1"

class LookbookDoc(BaseModel):
    version: str = "1.0.0"
    characters: List[LookbookCharacter] = Field(default_factory=list)
    locations: List[LookbookLocation] = Field(default_factory=list)
    props: List[LookbookProp] = Field(default_factory=list)
    # optional global style/profile info (e.g., user_theme from cover/campaign)
    style_profile: Dict[str, Any] = Field(default_factory=dict)

# --- Request/Response ---

class InitialIds(BaseModel):
    characters: List[str] = Field(default_factory=list)
    locations: List[str]  = Field(default_factory=list)
    props: List[str]      = Field(default_factory=list)

class SeedFromCoverRequest(BaseModel):
    job_id: str
    # Both cover refs are OPTIONAL now — lets you seed before the cover exists.
    cover_gs_uri: Optional[str] = Field(None, description="gs://bucket/object for the cover image")
    cover_image_url: Optional[str] = Field(None, description="Signed/public https URL for the cover image")
    initial_ids: InitialIds
    hints: Dict[str, str] = Field(default_factory=dict)
    user_theme: Optional[str] = None
    # NEW: free-text descriptors coming from cover_script (id -> short text)
    notes: Optional[Dict[str, str]] = None

class LookbookUpserts(BaseModel):
    characters: List[LookbookCharacter] = Field(default_factory=list)
    locations: List[LookbookLocation]   = Field(default_factory=list)
    props: List[LookbookProp]           = Field(default_factory=list)

class SeedFromCoverResponse(BaseModel):
    job_id: str
    lookbook_upserts: LookbookUpserts
    lookbook_gcs: Optional[GCSInfo] = None
