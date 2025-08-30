# app/features/lookbook_seed/service.py
import json
import os
from typing import Dict, List

from fastapi import HTTPException
from app.logger import get_logger
from app.lib.gcs_inventory import upload_json_to_gcs
from app.lib.paths import job_dir
from .schemas import (
    SeedFromCoverRequest, SeedFromCoverResponse, LookbookDoc,
    LookbookCharacter, LookbookLocation, LookbookProp,
    LookbookUpserts, ReferenceAsset
)

log = get_logger(__name__)

def _pretty_from_id(_id: str) -> str:
    # "char_roey" -> "Roey", "loc_studio" -> "Studio"
    s = _id
    for pref in ("char_", "loc_", "prop_"):
        if s.startswith(pref):
            s = s[len(pref):]
            break
    return s.replace("_", " ").strip().title() or _id

def _load_lookbook(lb_path: str) -> LookbookDoc:
    if os.path.exists(lb_path):
        with open(lb_path, "r") as f:
            data = json.load(f)
        try:
            return LookbookDoc.model_validate(data)
        except Exception as e:
            log.warning(f"Existing lookbook.json invalid, starting fresh: {e}")
    return LookbookDoc()

def _save_lookbook(lb_path: str, doc: LookbookDoc) -> None:
    os.makedirs(os.path.dirname(lb_path), exist_ok=True)
    with open(lb_path, "w") as f:
        json.dump(json.loads(doc.model_dump_json()), f, ensure_ascii=False, indent=2)

def _get_by_id(items: List, _id: str):
    for it in items:
        if getattr(it, "id", None) == _id:
            return it
    return None

def _list_from(obj, key: str) -> List[str]:
    """
    Return a list from either a Pydantic object with attribute `key`
    (InitialIds) or a dict-like with `key`.
    """
    if obj is None:
        return []
    if isinstance(obj, dict):
        val = obj.get(key, [])
    else:
        val = getattr(obj, key, [])
    if val is None:
        return []
    if not isinstance(val, list):
        raise HTTPException(422, f"initial_ids.{key} must be a list")
    for v in val:
        if not isinstance(v, str):
            raise HTTPException(422, f"initial_ids.{key} must be a list of strings")
    return val

def seed_from_cover(req: SeedFromCoverRequest) -> SeedFromCoverResponse:
    workdir = job_dir(req.job_id)
    os.makedirs(workdir, exist_ok=True)
    lb_path = os.path.join(workdir, "lookbook.json")

    lookbook = _load_lookbook(lb_path)

    # Optional: persist user_theme globally for later ref-assets/page gen
    if req.user_theme:
        lookbook.style_profile = lookbook.style_profile or {}
        lookbook.style_profile["user_theme"] = req.user_theme

    # Build a cover ref only if we actually have one
    cover_ref = None
    if req.cover_gs_uri or req.cover_image_url:
        cover_ref = ReferenceAsset(
            type="cover",
            url=req.cover_image_url,
            gs_uri=req.cover_gs_uri,
        )

    created_from = "cover_v1" if cover_ref else "cover_script_v1"

    up_chars, up_locs, up_props = [], [], []

    char_ids = _list_from(req.initial_ids, "characters")
    loc_ids  = _list_from(req.initial_ids, "locations")
    prop_ids = _list_from(req.initial_ids, "props")

    # Helper to build/merge visual canon from notes
    def _canon_for(_id: str, existing: Dict[str, str] | None) -> Dict[str, str]:
        canon = (existing or {}).copy()
        note = (req.notes or {}).get(_id)
        if note:
            canon["notes"] = note
        elif "notes" not in canon:
            canon["notes"] = "Seeded from cover/script; refine with concept sheet."
        return canon

    # ---------- Characters ----------
    for cid in char_ids:
        display_name = req.hints.get(cid) or _pretty_from_id(cid)
        existing = _get_by_id(lookbook.characters, cid)
        if existing:
            existing.display_name = existing.display_name or display_name
            existing.visual_canon = _canon_for(cid, existing.visual_canon)
            existing.reference_assets = existing.reference_assets or []
            if cover_ref and not any((ra.type == "cover") for ra in existing.reference_assets):
                existing.reference_assets.append(cover_ref)
            if not getattr(existing, "created_from", None):
                existing.created_from = created_from
            char = existing
        else:
            char = LookbookCharacter(
                id=cid,
                display_name=display_name,
                visual_canon=_canon_for(cid, None),
                reference_assets=[cover_ref] if cover_ref else [],
                created_from=created_from,
            )
            lookbook.characters.append(char)
        up_chars.append(char)

    # ---------- Locations ----------
    for lid in loc_ids:
        name = req.hints.get(lid) or _pretty_from_id(lid)
        existing = _get_by_id(lookbook.locations, lid)
        if existing:
            existing.name = existing.name or name
            existing.visual_canon = _canon_for(lid, existing.visual_canon)
            existing.reference_assets = existing.reference_assets or []
            if cover_ref and not any((ra.type == "cover") for ra in existing.reference_assets):
                existing.reference_assets.append(cover_ref)
            if not getattr(existing, "created_from", None):
                existing.created_from = created_from
            loc = existing
        else:
            loc = LookbookLocation(
                id=lid,
                name=name,
                visual_canon=_canon_for(lid, None),
                reference_assets=[cover_ref] if cover_ref else [],
                created_from=created_from,
            )
            lookbook.locations.append(loc)
        up_locs.append(loc)

    # ---------- Props ----------
    for pid in prop_ids:
        name = req.hints.get(pid) or _pretty_from_id(pid)
        existing = _get_by_id(lookbook.props, pid)
        if existing:
            existing.name = existing.name or name
            existing.visual_canon = _canon_for(pid, existing.visual_canon)
            existing.reference_assets = existing.reference_assets or []
            if cover_ref and not any((ra.type == "cover") for ra in existing.reference_assets):
                existing.reference_assets.append(cover_ref)
            if not getattr(existing, "created_from", None):
                existing.created_from = created_from
            prop = existing
        else:
            prop = LookbookProp(
                id=pid,
                name=name,
                visual_canon=_canon_for(pid, None),
                reference_assets=[cover_ref] if cover_ref else [],
                created_from=created_from,
            )
            lookbook.props.append(prop)
        up_props.append(prop)

    # Persist locally
    _save_lookbook(lb_path, lookbook)

    # Upload to GCS (non-fatal on failure)
    try:
        gcs_info = upload_json_to_gcs(
            data=json.loads(lookbook.model_dump_json()),
            object_name=f"jobs/{req.job_id}/lookbook.json",
            subdir="jobs",
            filename_hint="lookbook.json",
            cache_control="no-cache",
            make_signed_url=True,
        )
    except Exception as e:
        log.exception(f"Failed to upload lookbook.json to GCS: {e}")
        gcs_info = None

    return SeedFromCoverResponse(
        job_id=req.job_id,
        lookbook_upserts=LookbookUpserts(
            characters=up_chars,
            locations=up_locs,
            props=up_props,
        ),
        lookbook_gcs=gcs_info,
    )
