# app/features/lookbook_ref_assets/service.py
import base64
import glob
import json
import os
from typing import Dict, List, Optional, Tuple, Union

from app.logger import get_logger
from app.config import config
from app.lib.openai_client import client
from app.lib.paths import job_dir
from app.lib.gcs_inventory import upload_to_gcs, upload_json_to_gcs

from app.features.lookbook_seed.schemas import (
    LookbookDoc, ReferenceAsset
)
from .schemas import GenerateRefAssetsRequest, GenerateRefAssetsResponse, RefAssetResultItem
from .prompt import (
    character_portrait_prompt, character_turnaround_prompt,
    location_wide_prompt, prop_detail_prompt
)

log = get_logger(__name__)

# ---- Helpers ----

def _load_lookbook(lb_path: str) -> LookbookDoc:
    if not os.path.exists(lb_path):
        raise FileNotFoundError("lookbook.json not found; seed it first")
    with open(lb_path, "r") as f:
        data = json.load(f)
    return LookbookDoc.model_validate(data)

def _save_lookbook(lb_path: str, doc: LookbookDoc) -> None:
    os.makedirs(os.path.dirname(lb_path), exist_ok=True)
    with open(lb_path, "w") as f:
        json.dump(json.loads(doc.model_dump_json()), f, ensure_ascii=False, indent=2)

def _detect_kind(_id: str) -> str:
    if _id.startswith("char_"):
        return "character"
    if _id.startswith("loc_"):
        return "location"
    if _id.startswith("prop_"):
        return "prop"
    return "unknown"

def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

def _save_b64_png(b64: str, out_path: str) -> None:
    _ensure_dir(out_path)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))

def _upload_image(out_path: str, object_name: str) -> Dict[str, str]:
    try:
        info = upload_to_gcs(out_path, object_name=object_name)  # preferred signature
    except TypeError:
        info = upload_to_gcs(out_path)  # fallback
    return info

def _pick_url(info: Dict[str, str]) -> str:
    return info.get("gcs_url") or info.get("public_url") or info.get("signed_url") or ""

# ---- Generation strategy ----

DEFAULT_TYPES = {
    "character": ["portrait", "turnaround"],
    "location": ["wide"],
    "prop": ["detail"],
}

def _types_for_id(_id: str, kind: str, req_map: Dict[str, List[str]]) -> List[str]:
    if _id in req_map and req_map[_id]:
        return req_map[_id]
    return DEFAULT_TYPES.get(kind, [])

def _has_type(existing_assets: List[ReferenceAsset], t: str) -> bool:
    return any(a.type == t for a in (existing_assets or []))

def _char_names(doc: LookbookDoc, cid: str) -> Tuple[str, Dict]:
    for c in doc.characters:
        if c.id == cid:
            return c.display_name, c.visual_canon
    return cid, {}

def _loc_names(doc: LookbookDoc, lid: str) -> Tuple[str, Dict]:
    for l in doc.locations:
        if l.id == lid:
            return l.name, l.visual_canon
    return lid, {}

def _prop_names(doc: LookbookDoc, pid: str) -> Tuple[str, Dict]:
    for p in doc.props:
        if p.id == pid:
            return p.name, p.visual_canon
    return pid, {}

def _ensure_list_ref_assets(obj) -> List[ReferenceAsset]:
    assets = getattr(obj, "reference_assets", None)
    if assets is None:
        obj.reference_assets = []
        return obj.reference_assets
    return assets

# ---- Base64 reference handling ----

def _strip_data_url(b64_or_data_url: str) -> str:
    """
    Accepts pure base64 OR data URLs like 'data:image/png;base64,AAAA...'
    Returns the base64 payload only.
    """
    s = b64_or_data_url.strip()
    if s.startswith("data:"):
        comma = s.find(",")
        if comma != -1:
            return s[comma + 1 :]
    return s

def _first_b64_for_id(ref_map: Dict[str, Union[str, List[str]]], _id: str) -> Optional[str]:
    """
    Pull the first usable base64 string for this id from reference_images_by_id.
    Value may be a single string or a list of strings.
    """
    if _id not in ref_map:
        return None
    val = ref_map[_id]
    if isinstance(val, list):
        for item in val:
            if isinstance(item, str) and item.strip():
                return _strip_data_url(item)
        return None
    if isinstance(val, str) and val.strip():
        return _strip_data_url(val)
    return None

def _b64_to_tmp_png(b64_payload: str, tmp_dir: str, tag: str) -> Optional[str]:
    """
    Write a base64 PNG to a temp file; return its path. If decode fails, return None.
    """
    if not b64_payload:
        return None
    os.makedirs(tmp_dir, exist_ok=True)
    out = os.path.join(tmp_dir, f"ref_{tag}.png")
    try:
        with open(out, "wb") as f:
            f.write(base64.b64decode(b64_payload))
        return out
    except Exception as e:
        log.warning(f"[ref-assets] invalid base64 for {_safe(tag)}: {e}")
        return None

def _safe(s: str) -> str:
    try:
        return s
    except Exception:
        return "<id>"

# ---- Image generation ----

def _gen_image(prompt: str) -> str:
    resp = client.images.generate(
        model=getattr(config, "openai_image_model", "gpt-image-1"),
        prompt=prompt,
        size=getattr(config, "image_size", "1024x1024"),
        n=1,
    )
    return resp.data[0].b64_json

def _gen_image_with_optional_ref(prompt: str, ref_image_path: Optional[str]) -> str:
    """
    If ref_image_path is provided, use images.edit with that file (style/likeness guidance).
    Otherwise, generate from scratch.
    Returns base64 PNG.
    """
    try:
        if ref_image_path:
            with open(ref_image_path, "rb") as ref_f:
                resp = client.images.edit(
                    model=getattr(config, "openai_image_model", "gpt-image-1"),
                    prompt=prompt,
                    size=getattr(config, "image_size", "1024x1024"),
                    n=1,
                    image=ref_f,
                )
            return resp.data[0].b64_json
        return _gen_image(prompt)
    except Exception as e:
        raise RuntimeError(f"image gen failed: {e}") from e

# ---- Main entrypoint ----

def generate_ref_assets(req: GenerateRefAssetsRequest) -> GenerateRefAssetsResponse:
    """
    Generate (or regenerate) reference assets for the given Lookbook IDs, using
    **per-ID base64** reference images when provided.

    Overwrite mode:
    - When `force=True` OR caller explicitly requested types for an ID, we overwrite
      those types: write to stable names (e.g., portrait.png) and replace the
      matching entry in reference_assets.
    - When `force=False` and the type already exists, we skip.
    """
    workdir = job_dir(req.job_id)
    lb_path = os.path.join(workdir, "lookbook.json")
    doc = _load_lookbook(lb_path)

    results: List[RefAssetResultItem] = []

    # Build an index from lookbook
    idx = {
        **{c.id: ("character", c) for c in doc.characters},
        **{l.id: ("location", l) for l in doc.locations},
        **{p.id: ("prop", p) for p in doc.props},
    }

    tmpdir = os.path.join(workdir, "lookbook", "_tmp")

    for _id in req.ids:
        kind, obj = idx.get(_id, (_detect_kind(_id), None))
        result = RefAssetResultItem(id=_id, kind=kind, generated=[], skipped_types=[])

        if obj is None:
            result.message = "ID not found in lookbook"
            results.append(result)
            continue

        want_types = _types_for_id(_id, kind, req.asset_types)
        if not want_types:
            result.message = "No asset types requested for this ID"
            results.append(result)
            continue

        assets_list: List[ReferenceAsset] = _ensure_list_ref_assets(obj)
        id_folder = os.path.join(workdir, "lookbook", _id)

        # Per-ID base64 reference (first valid only). If none -> generate-only path.
        b64_ref = _first_b64_for_id(req.reference_images_by_id, _id)
        ref_path = _b64_to_tmp_png(b64_ref, tmpdir, tag=_id) if b64_ref else None

        for t in want_types:
            already = _has_type(assets_list, t)
            will_overwrite = req.force or (_id in req.asset_types and t in req.asset_types[_id])

            if already and not will_overwrite:
                result.skipped_types.append(t)
                continue

            # ----- Build prompt with style theme injection -----
            try:
                if kind == "character":
                    name, canon = _char_names(doc, _id)
                    if t == "portrait":
                        prompt = character_portrait_prompt(name, canon, req.user_theme)
                    elif t == "turnaround":
                        prompt = character_turnaround_prompt(name, canon, req.user_theme)
                    else:
                        prompt = character_portrait_prompt(name, canon, req.user_theme) + f" (variant: {t})"

                elif kind == "location":
                    name, canon = _loc_names(doc, _id)
                    if t == "wide":
                        prompt = location_wide_prompt(name, canon, req.user_theme)
                    else:
                        prompt = location_wide_prompt(name, canon, req.user_theme) + f" (variant: {t})"

                elif kind == "prop":
                    name, canon = _prop_names(doc, _id)
                    if t == "detail":
                        prompt = prop_detail_prompt(name, canon, req.user_theme)
                    else:
                        prompt = prop_detail_prompt(name, canon, req.user_theme) + f" (variant: {t})"

                else:
                    result.skipped_types.append(t)
                    result.message = (result.message + "; unknown kind" if result.message else "unknown kind")
                    continue

                # ----- Generate or Edit (based on per-ID base64 ref) -----
                b64 = _gen_image_with_optional_ref(prompt, ref_path)

                # ----- Stable filename (overwrite) -----
                local_path = os.path.join(id_folder, f"{t}.png")
                _save_b64_png(b64, local_path)

                # ----- Stable GCS object (overwrite) -----
                object_name = f"jobs/{req.job_id}/lookbook/{_id}/{t}.png"
                info = _upload_image(local_path, object_name)

                # Replace prior entry of same type
                assets_list[:] = [a for a in assets_list if a.type != t]
                ref = ReferenceAsset(
                    type=t,
                    url=_pick_url(info),
                    gs_uri=info.get("gs_uri"),
                )
                assets_list.append(ref)
                result.generated.append(ref)

            except Exception as e:
                log.exception(f"Failed generating asset for id={_id}, type={t}: {e}")
                result.message = (result.message + f"; {t} failed" if result.message else f"{t} failed")

        results.append(result)

    # Persist + upload lookbook
    _save_lookbook(lb_path, doc)
    try:
        gcs_info = upload_json_to_gcs(
            data=json.loads(doc.model_dump_json()),
            object_name=f"jobs/{req.job_id}/lookbook.json",
            subdir="jobs",
            filename_hint="lookbook.json",
            cache_control="no-cache",
            make_signed_url=True,
        )
    except Exception as e:
        log.exception(f"Failed to upload lookbook.json to GCS: {e}")
        gcs_info = None

    return GenerateRefAssetsResponse(job_id=req.job_id, results=results, lookbook_gcs=gcs_info)
