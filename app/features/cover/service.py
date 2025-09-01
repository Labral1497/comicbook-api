# app/features/cover/service.py
import base64
import os
import urllib.request
from typing import List, Tuple

from fastapi import HTTPException
from app.config import config
from app.lib.imaging import maybe_decode_image_to_path
from app.lib.openai_client import client
from app.logger import get_logger

# Lookbook access + GCS helper
from app.features.lookbook_ref_assets.service import _load_lookbook  # reuse
from app.features.lookbook_seed.schemas import LookbookDoc, ReferenceAsset
from app.lib.gcs_inventory import download_gcs_object_to_file

from .schemas import GenerateCoverRequest
from .prompt import build_cover_prompt

log = get_logger(__name__)


def _dl_to(path: str, url: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if url.startswith("gs://"):
        download_gcs_object_to_file(url, path)
    else:
        with urllib.request.urlopen(url) as r, open(path, "wb") as f:
            f.write(r.read())
    return path


def _collect_cover_refs(workdir: str, lb: LookbookDoc) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    From lookbook.json, gather best-available reference images for:
      - characters: prefer portrait, then turnaround
      - locations : wide
      - props     : detail

    Returns: (ref_paths, character_names, location_names, prop_names)
    """
    ref_paths: List[str] = []
    char_names: List[str] = []
    loc_names: List[str] = []
    prop_names: List[str] = []

    def best_asset(assets: List[ReferenceAsset], wanted: List[str]) -> ReferenceAsset | None:
        for w in wanted:
            for a in assets or []:
                if getattr(a, "type", None) == w:
                    return a
        return None

    # Characters
    for c in lb.characters or []:
        a = best_asset(c.reference_assets, ["portrait", "turnaround"])
        if a and (a.gs_uri or a.url):
            out = os.path.join(workdir, "cover_refs", f"char_{c.id}.png")
            src = a.gs_uri or a.url
            try:
                _dl_to(out, src)
                ref_paths.append(out)
                char_names.append(c.display_name or c.id)
            except Exception as e:
                log.warning(f"Failed downloading char ref for {c.id}: {e}")

    # Locations
    for l in lb.locations or []:
        a = best_asset(l.reference_assets, ["wide"])
        if a and (a.gs_uri or a.url):
            out = os.path.join(workdir, "cover_refs", f"loc_{l.id}.png")
            src = a.gs_uri or a.url
            try:
                _dl_to(out, src)
                ref_paths.append(out)
                loc_names.append(l.name or l.id)
            except Exception as e:
                log.warning(f"Failed downloading location ref for {l.id}: {e}")

    # Props
    for p in lb.props or []:
        a = best_asset(p.reference_assets, ["detail"])
        if a and (a.gs_uri or a.url):
            out = os.path.join(workdir, "cover_refs", f"prop_{p.id}.png")
            src = a.gs_uri or a.url
            try:
                _dl_to(out, src)
                ref_paths.append(out)
                prop_names.append(p.name or p.id)
            except Exception as e:
                log.warning(f"Failed downloading prop ref for {p.id}: {e}")

    return ref_paths, char_names, loc_names, prop_names


def _make_prompt_with_lookbook(
    *,
    workdir: str,
    req: GenerateCoverRequest,
) -> Tuple[str, List[str]]:
    """
    Build the cover prompt and collect reference images from the lookbook.
    Also uses req.image_base64 (if provided) as a HIGH-PRIORITY extra ref
    (first in the list) for main-character likeness.
    """
    # Load lookbook if present
    lb_path = os.path.join(workdir, "lookbook.json")
    has_lb = os.path.exists(lb_path)
    char_names: List[str] = []
    loc_names: List[str] = []
    prop_names: List[str] = []
    ref_paths: List[str] = []

    if has_lb:
        try:
            lb = _load_lookbook(lb_path)
            refs, char_names, loc_names, prop_names = _collect_cover_refs(workdir, lb)
            ref_paths.extend(refs)
        except Exception as e:
            log.warning(f"Could not load/use lookbook refs: {e}")

    # If user supplied a direct face ref (main), prepend it to refs (highest priority).
    # This preserves backwards-compatibility and makes likeness lock tighter.
    face_ref_path = maybe_decode_image_to_path(req.image_base64, workdir)
    if face_ref_path:
        ref_paths.insert(0, face_ref_path)

    prompt = build_cover_prompt(
        title=req.title,
        tagline=req.tagline,
        cover_art_description=req.cover_art_description,
        user_theme=req.user_theme,
        character_names=char_names,
        location_names=loc_names,
        prop_names=prop_names,
    )
    return prompt, ref_paths


def generate_comic_cover(req: GenerateCoverRequest, *, out_path: str, workdir: str) -> str:
    """
    Generate the cover using multiple lookbook reference images when available.
    - If we have any refs -> images.edit with a LIST of files
    - Else -> images.generate
    """
    prompt, ref_paths = _make_prompt_with_lookbook(workdir=workdir, req=req)
    log.debug(f"cover prompt is: {prompt}")

    try:
        if ref_paths:
            files = [open(p, "rb") for p in ref_paths]
            try:
                resp = client.images.edit(
                    model=config.openai_image_model,
                    prompt=prompt,
                    size=config.image_size,
                    n=1,
                    image=files,  # list of files: likeness + style guidance
                )
            finally:
                for f in files:
                    try:
                        f.close()
                    except Exception:
                        pass
        else:
            # No references at all → plain generate
            resp = client.images.generate(
                model=config.openai_image_model,
                prompt=prompt,
                size=config.image_size,
                n=1,
            )

        b64 = resp.data[0].b64_json
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return out_path

    except Exception as e:
        raise HTTPException(500, f"Cover generation failed: {e}")
