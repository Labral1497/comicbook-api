# app/features/lookbook_seed/service_delta.py
import json, os
from typing import List
from app.logger import get_logger
from app.lib.paths import job_dir
from app.lib.gcs_inventory import upload_json_to_gcs
from ..full_script.schemas import LookbookDoc, LookbookCharacter, LookbookLocation, LookbookProp
from app.features.full_script.schemas import LookbookDelta, CharacterToAdd, LocationToAdd, PropToAdd

log = get_logger(__name__)

def _load_lookbook(path: str) -> LookbookDoc:
    if os.path.exists(path):
        try:
            return LookbookDoc.model_validate_json(open(path).read())
        except Exception as e:
            log.warning(f"Invalid lookbook at {path}, starting fresh: {e}")
    return LookbookDoc()

def _save_lookbook(path: str, doc: LookbookDoc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(json.loads(doc.model_dump_json()), f, ensure_ascii=False, indent=2)

def _get_by_id(items: List, _id: str):
    for it in items:
        if getattr(it, "id", None) == _id:
            return it
    return None

def _merge_visual_stub(entity, stub: str | None, default_note: str):
    entity.visual_canon = entity.visual_canon or {}
    if stub:
        # keep author’s stub as a readable “description”
        if not entity.visual_canon.get("description"):
            entity.visual_canon["description"] = stub
    if "notes" not in entity.visual_canon:
        entity.visual_canon["notes"] = default_note

class SeedFromDeltaResult:
    def __init__(self):
        self.characters: List[str] = []
        self.locations: List[str] = []
        self.props: List[str] = []

def seed_lookbook_from_delta(*, job_id: str, delta: LookbookDelta, user_theme: str | None = None) -> SeedFromDeltaResult:
    """
    Idempotent: merges LookbookDelta into jobs/{job_id}/lookbook.json.
    Returns the list of IDs that were upserted (new or touched).
    """
    workdir = job_dir(job_id)
    os.makedirs(workdir, exist_ok=True)
    lb_path = os.path.join(workdir, "lookbook.json")

    doc = _load_lookbook(lb_path)

    # optionally persist theme at the root if you’ve added that field to LookbookDoc
    if hasattr(doc, "style_profile") and user_theme:
        doc.style_profile = (getattr(doc, "style_profile", None) or {})
        doc.style_profile["user_theme"] = user_theme

    out = SeedFromDeltaResult()

    # ----- characters -----
    for c in delta.characters_to_add:
        assert isinstance(c, CharacterToAdd)
        existing = _get_by_id(doc.characters, c.id)
        if existing:
            if not existing.display_name:
                existing.display_name = c.display_name
            if c.role and not existing.role:
                existing.role = c.role
            _merge_visual_stub(existing, c.visual_stub, "Seeded from full script; refine with concept sheet.")
            out.characters.append(existing.id)
        else:
            ent = LookbookCharacter(
                id=c.id,
                display_name=c.display_name,
                role=c.role,
                visual_canon={},
                reference_assets=[],
                created_from="script_v1",
            )
            _merge_visual_stub(ent, c.visual_stub, "Seeded from full script; refine with concept sheet.")
            doc.characters.append(ent)
            out.characters.append(ent.id)

    # ----- locations -----
    for l in delta.locations_to_add:
        assert isinstance(l, LocationToAdd)
        existing = _get_by_id(doc.locations, l.id)
        if existing:
            if not existing.name:
                existing.name = l.name
            _merge_visual_stub(existing, l.visual_stub, "Seeded from full script; refine with concept sheet.")
            out.locations.append(existing.id)
        else:
            ent = LookbookLocation(
                id=l.id,
                name=l.name,
                visual_canon={},
                reference_assets=[],
                created_from="script_v1",
            )
            _merge_visual_stub(ent, l.visual_stub, "Seeded from full script; refine with concept sheet.")
            doc.locations.append(ent)
            out.locations.append(ent.id)

    # ----- props -----
    for p in delta.props_to_add:
        assert isinstance(p, PropToAdd)
        existing = _get_by_id(doc.props, p.id)
        if existing:
            if not existing.name:
                existing.name = p.name
            _merge_visual_stub(existing, p.visual_stub, "Seeded from full script; refine with concept sheet.")
            out.props.append(existing.id)
        else:
            ent = LookbookProp(
                id=p.id,
                name=p.name,
                visual_canon={},
                reference_assets=[],
                created_from="script_v1",
            )
            _merge_visual_stub(ent, p.visual_stub, "Seeded from full script; refine with concept sheet.")
            doc.props.append(ent)
            out.props.append(ent.id)

    # persist + upload
    _save_lookbook(lb_path, doc)
    try:
        from app.lib.gcs_inventory import upload_json_to_gcs
        gcs_info = upload_json_to_gcs(
            data=json.loads(doc.model_dump_json()),
            object_name=f"jobs/{job_id}/lookbook.json",
            subdir="jobs",
            filename_hint="lookbook.json",
            cache_control="no-cache",
            make_signed_url=True,
        )
        _ = gcs_info
    except Exception as e:
        log.warning(f"Failed to upload lookbook.json: {e}")

    return out
