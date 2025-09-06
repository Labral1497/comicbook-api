# app/features/lookbook_ref_assets/service.py
import base64
import glob
import json
import os
from typing import Dict, List, Optional, Set, Tuple, Union

from app.logger import get_logger
from app.config import config
from app.lib.openai_client import client
from app.lib.paths import job_dir
from app.lib.gcs_inventory import download_gcs_object_to_file, upload_to_gcs, upload_json_to_gcs

from app.features.lookbook_seed.schemas import (
    LookbookDoc, ReferenceAsset
)
from .schemas import CleanAssetsRequest, CleanAssetsResponse, CleanAssetsResultItem, GenerateRefAssetsRequest, GenerateRefAssetsResponse, RefAssetResultItem
from .prompt import (
    character_portrait_prompt, character_turnaround_prompt,
    location_wide_prompt, prop_detail_prompt
)

log = get_logger(__name__)

# ---- Helpers ----

def _infer_job_id_from_lb_path(lb_path: str) -> Optional[str]:
    """
    Expecting .../jobs/<job_id>/lookbook.json (your existing layout).
    Returns <job_id> if it can be inferred, else None.
    """
    d = os.path.dirname(lb_path)                 # .../jobs/<job_id>
    parent = os.path.basename(os.path.dirname(d))# jobs
    jid = os.path.basename(d)                    # <job_id>
    if parent == "jobs" and jid:
        return jid
    # fallback: if your layout ever changes, try just returning the dir name
    return jid or None

def _load_lookbook(lb_path: str) -> LookbookDoc:
    """
    Load lookbook.json. If it's not on disk, try to fetch it from GCS:
    gs://<bucket>/jobs/<job_id>/lookbook.json
    """
    if not os.path.exists(lb_path):
        # Try GCS fallback
        bucket = getattr(config, "gcs_bucket", None) or getattr(config, "gcs_bucket_name", None)
        job_id = _infer_job_id_from_lb_path(lb_path)
        if bucket and job_id:
            os.makedirs(os.path.dirname(lb_path), exist_ok=True)
            gs_uri = f"gs://{bucket}/jobs/{job_id}/lookbook.json"
            try:
                log.debug(f"[lookbook] local missing; downloading {gs_uri} → {lb_path}")
                download_gcs_object_to_file(gs_uri, lb_path)
            except Exception as e:
                raise FileNotFoundError(
                    f"lookbook.json not found locally and failed to download from {gs_uri}: {e}"
                ) from e
        else:
            # No way to resolve; preserve the old error message
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


def _char_meta(doc: LookbookDoc, cid: str):
    """Return (display_name, visual_canon, gender_or_none)"""
    for c in doc.characters:
        if c.id == cid:
            vc = c.visual_canon or {}
            gender = getattr(c, "gender", None) or vc.get("gender")
            return c.display_name, vc, gender
    return cid, {}, None

def _find_asset(assets_list: List[ReferenceAsset], t: str) -> Optional[ReferenceAsset]:
    for a in assets_list or []:
        if a.type == t:
            return a
    return None

def _download_to(tmp_dir: str, url_or_gs: str, filename: str) -> Optional[str]:
    if not url_or_gs:
        return None
    os.makedirs(tmp_dir, exist_ok=True)
    out = os.path.join(tmp_dir, filename)
    try:
        if url_or_gs.startswith("gs://"):
            download_gcs_object_to_file(url_or_gs, out)
        else:
            import urllib.request
            with urllib.request.urlopen(url_or_gs) as r, open(out, "wb") as f:
                f.write(r.read())
        return out
    except Exception as e:
        log.warning(f"[ref-assets] download failed {url_or_gs}: {e}")
        return None

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
        tmpdir = os.path.join(workdir, "lookbook", "_tmp")

        # ---- choose a general fallback reference (usually from cover) ----
        entity_cover_ra = _find_asset(assets_list, "cover")
        general_ref = (getattr(entity_cover_ra, "gs_uri", None) or getattr(entity_cover_ra, "url", None))
        general_ref_path = _download_to(tmpdir, general_ref, f"{_id}_cover_ref.png") if general_ref else None

        # ---- ensure character types run in a safe order: portrait -> turnaround ----
        if kind == "character":
            order = {"portrait": 0, "turnaround": 1}
            want_types.sort(key=lambda t: order.get(t, 99))

        # track the portrait we generate (or already have)
        portrait_local_path: Optional[str] = None
        if kind == "character" and _find_asset(assets_list, "portrait") and "turnaround" in want_types:
            # if a portrait already exists, fetch it to use as ref for turnaround
            existing_portrait = _find_asset(assets_list, "portrait")
            portrait_ref = getattr(existing_portrait, "gs_uri", None) or getattr(existing_portrait, "url", None)
            portrait_local_path = _download_to(tmpdir, portrait_ref, f"{_id}_portrait_ref.png")

        for t in want_types:
            already = _has_type(assets_list, t)
            will_overwrite = req.force or (_id in req.asset_types and t in req.asset_types[_id])

            if already and not will_overwrite:
                result.skipped_types.append(t)
                continue

            # ----- build prompt (with gender if available) -----
            if kind == "character":
                name, canon, gender = _char_meta(doc, _id)
                if t == "portrait":
                    prompt = character_portrait_prompt(name, canon, req.user_theme, gender)
                elif t == "turnaround":
                    prompt = character_turnaround_prompt(name, canon, req.user_theme, gender)
                else:
                    prompt = character_portrait_prompt(name, canon, req.user_theme, gender) + f" (variant: {t})"

            elif kind == "location":
                name, canon = _loc_names(doc, _id)
                prompt = location_wide_prompt(name, canon, req.user_theme) if t == "wide" \
                       else location_wide_prompt(name, canon, req.user_theme) + f" (variant: {t})"

            elif kind == "prop":
                name, canon = _prop_names(doc, _id)
                prompt = prop_detail_prompt(name, canon, req.user_theme) if t == "detail" \
                       else prop_detail_prompt(name, canon, req.user_theme) + f" (variant: {t})"
            else:
                result.skipped_types.append(t)
                result.message = (result.message + "; unknown kind" if result.message else "unknown kind")
                continue

            # ----- choose the best reference for THIS type -----
            ref_for_this: Optional[str] = None
            if kind == "character" and t == "turnaround":
                # strongest: the just-generated portrait
                if portrait_local_path and os.path.exists(portrait_local_path):
                    ref_for_this = portrait_local_path
                # otherwise: a previously existing portrait
                elif _find_asset(assets_list, "portrait"):
                    if not portrait_local_path:
                        existing_portrait = _find_asset(assets_list, "portrait")
                        pr = getattr(existing_portrait, "gs_uri", None) or getattr(existing_portrait, "url", None)
                        portrait_local_path = _download_to(tmpdir, pr, f"{_id}_portrait_ref.png")
                    ref_for_this = portrait_local_path or general_ref_path
                else:
                    ref_for_this = general_ref_path  # last resort
            else:
                # portrait: if caller provided a per-id ref_image (handled earlier in your code), use it
                # else fall back to general cover ref if available
                ref_for_this = general_ref_path

            # ----- generate (edit if ref present) -----
            try:
                b64 = _gen_image_with_optional_ref(prompt, ref_for_this)

                local_path = os.path.join(id_folder, f"{t}.png")  # overwrite-stable
                _save_b64_png(b64, local_path)

                object_name = f"jobs/{req.job_id}/lookbook/{_id}/{t}.png"
                info = _upload_image(local_path, object_name)

                # replace prior entry of same type
                assets_list[:] = [a for a in assets_list if a.type != t]
                ref = ReferenceAsset(
                    type=t,
                    url=info.get("public_url") or info.get("gcs_url") or info.get("signed_url"),
                    gs_uri=info.get("gs_uri"),
                )
                assets_list.append(ref)
                result.generated.append(ref)

                # remember portrait for later turnaround in this same run
                if kind == "character" and t == "portrait":
                    portrait_local_path = local_path

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

# --- Cleanup API ---

def _entity_by_id(doc: LookbookDoc, _id: str):
    for c in doc.characters:
        if c.id == _id:
            return "character", c
    for l in doc.locations:
        if l.id == _id:
            return "location", l
    for p in doc.props:
        if p.id == _id:
            return "prop", p
    return "unknown", None


def _delete_local_files(workdir: str, entity_id: str, types: Set[str]) -> None:
    base = os.path.join(workdir, "lookbook", entity_id)
    for t in types:
        # stable
        f = os.path.join(base, f"{t}.png")
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass
        # versioned
        for vf in glob.glob(os.path.join(base, f"{t}_v*.png")):
            try:
                os.remove(vf)
            except Exception:
                pass


def _delete_gcs_objects(job_id: str, entity_id: str, types: Set[str]) -> None:
    """
    Delete both stable and versioned objects:
      jobs/{job}/lookbook/{id}/{type}.png
      jobs/{job}/lookbook/{id}/{type}_v*.png
    Uses your gcs_inventory helpers if available.
    """
    try:
        from app.lib.gcs_inventory import delete_gcs_object, list_objects, delete_objects  # if you have these
    except Exception:
        delete_gcs_object = None
        list_objects = None
        delete_objects = None

    prefix_base = f"jobs/{job_id}/lookbook/{entity_id}/"
    if list_objects and delete_objects:
        for t in types:
            # stable
            keys = [prefix_base + f"{t}.png"]
            # versioned
            keys += [o for o in list_objects(prefix_base) if o.rsplit("/", 1)[-1].startswith(f"{t}_v")]
            try:
                delete_objects(keys)
            except Exception:
                # try single deletes as fallback
                if delete_gcs_object:
                    for k in keys:
                        try:
                            delete_gcs_object(k)
                        except Exception:
                            pass
    elif delete_gcs_object:
        for t in types:
            for key in (prefix_base + f"{t}.png",):  # stable only if no listing
                try:
                    delete_gcs_object(key)
                except Exception:
                    pass
    else:
        # No deletion helpers wired; silently skip
        pass

# All types your system might emit; include "cover" so "*" can truly mean all
ALL_ASSET_TYPES = {"portrait", "turnaround", "wide", "detail", "cover"}


def _count_local_matches(workdir: str, _id: str, t: str) -> int:
    """Count local files for a given id/type (stable + versioned)."""
    folder = os.path.join(workdir, "lookbook", _id)
    return (
        len(glob.glob(os.path.join(folder, f"{t}.png"))) +
        len(glob.glob(os.path.join(folder, f"{t}_v*.png")))
    )

def _remove_entity(doc, kind: str, _id: str) -> bool:
    if kind == "character":
        lst = doc.characters
    elif kind == "location":
        lst = doc.locations
    elif kind == "prop":
        lst = doc.props
    else:
        return False
    for i, e in enumerate(lst):
        if getattr(e, "id", None) == _id:
            del lst[i]
            return True
    return False

def clean_lookbook_assets(req: CleanAssetsRequest) -> CleanAssetsResponse:
    workdir = job_dir(req.job_id)
    lb_path = os.path.join(workdir, "lookbook.json")
    doc = _load_lookbook(lb_path)

    results: List[CleanAssetsResultItem] = []
    changed = False

    for _id in req.ids:
        kind, ent = _entity_by_id(doc, _id)
        item = CleanAssetsResultItem(id=_id, kind=kind)

        if not ent:
            item.notes.append("ID not found in lookbook")
            results.append(item)
            continue

        # What types did the caller ask to remove for this ID?
        requested_raw = req.asset_types.get(_id, [])
        if not requested_raw:
            item.notes.append("No types requested (or present)")
            results.append(item)
            continue

        # Expand "*" to all known types; optionally drop "cover"
        if "*" in requested_raw:
            desired_types = set(ALL_ASSET_TYPES)
        else:
            desired_types = set(requested_raw)

        if not req.include_cover:
            desired_types.discard("cover")

        if not desired_types:
            item.notes.append("Nothing to remove for this id")
            results.append(item)
            continue

        # Types that are present in lookbook (these we remove from reference_assets)
        ras: List[ReferenceAsset] = getattr(ent, "reference_assets", []) or []
        existing_types = {a.type for a in ras}
        lookbook_types_to_remove = desired_types & existing_types

        # --- DRY RUN: show what would happen (files + lookbook) ---
        if req.dry_run and req.prune_empty_entities:
            # If entity would have zero assets after removal, say so
            would_assets = [a for a in ras if a.type not in lookbook_types_to_remove]
            if len(would_assets) == 0:
                item.notes.append("Would remove entity from lookbook (no reference_assets remain)")

        # --- REAL RUN: actually prune if requested ---
        if (not req.dry_run) and req.prune_empty_entities:
            ras_now = getattr(ent, "reference_assets", []) or []
            if len(ras_now) == 0:
                if _remove_entity(doc, kind, _id):
                    changed = True
                    item.notes.append("Removed entity from lookbook (no reference_assets remain)")

        if req.dry_run:
            # Count local matches even if lookbook has none (orphan files)
            for t in sorted(desired_types):
                local_count = _count_local_matches(workdir, _id, t)
                in_lb = "yes" if t in existing_types else "no"
                lb_action = "remove from lookbook" if t in lookbook_types_to_remove else "no lookbook ref"
                item.notes.append(f"[{t}] local={local_count} | in_lookbook={in_lb} → {lb_action}")

            # We still fill removed_types for visibility (only those in lookbook)
            item.removed_types = sorted(list(lookbook_types_to_remove))
            results.append(item)
            continue

        # --- REAL RUN: mutate lookbook if needed ---
        if lookbook_types_to_remove:
            new_assets = [a for a in ras if a.type not in lookbook_types_to_remove]
            if len(new_assets) != len(ras):
                setattr(ent, "reference_assets", new_assets)
                changed = True

        # Always attempt to delete local & GCS files for desired_types (even if not in lookbook)
        if req.delete_local:
            _delete_local_files(workdir, _id, desired_types)

        if req.delete_gcs:
            try:
                _delete_gcs_objects(req.job_id, _id, desired_types)
            except NameError:
                # If your gcs delete helper isn't available in this env
                item.notes.append("GCS deletion helper not found; skipped GCS deletes")

        item.removed_types = sorted(list(lookbook_types_to_remove))
        results.append(item)

    # Save and upload lookbook if we changed it and not dry-run
    gcs_info = None
    if changed and not req.dry_run:
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
            log.warning(f"Failed uploading lookbook.json after clean: {e}")

    return CleanAssetsResponse(job_id=req.job_id, results=results, lookbook_gcs=gcs_info)
