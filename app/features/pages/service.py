# app/features/comic/service.py
from __future__ import annotations

import base64
import json
import os
from typing import List, Optional, Set, Dict, Tuple

from app.config import config
from app.features.full_script.schemas import Page, Panel
from app.logger import get_logger
from app.lib.openai_client import client
from app.lib.gcs_inventory import upload_to_gcs
from app.lib.jobs import load_manifest, mark_page_status

# NEW: Lookbook models + ref-asset generator
from app.features.lookbook_seed.schemas import LookbookDoc, ReferenceAsset
from app.features.lookbook_ref_assets.schemas import GenerateRefAssetsRequest
from app.features.lookbook_ref_assets.service import generate_ref_assets

from app.features.pages.schemas import ComicRequest

log = get_logger(__name__)

# -------------------------
# Lookbook helpers
# -------------------------

def _lookbook_path(workdir: str) -> str:
    return os.path.join(workdir, "lookbook.json")

def _load_lookbook(workdir: str) -> LookbookDoc:
    lb_path = _lookbook_path(workdir)
    if not os.path.exists(lb_path):
        raise FileNotFoundError("lookbook.json not found. Seed it with /lookbook/seed-from-cover first.")
    with open(lb_path, "r") as f:
        data = json.load(f)
    return LookbookDoc.model_validate(data)

def _index_lookbook(doc: LookbookDoc) -> Dict[str, Tuple[str, object]]:
    """
    Returns id -> (kind, obj) where kind in {"character","location","prop"}.
    """
    idx: Dict[str, Tuple[str, object]] = {}
    for c in doc.characters: idx[c.id] = ("character", c)
    for l in doc.locations: idx[l.id] = ("location", l)
    for p in doc.props:     idx[p.id] = ("prop", p)
    return idx

def _collect_page_ids(page: Page) -> Set[str]:
    ids: Set[str] = set()
    if getattr(page, "location_id", None):
        ids.add(page.location_id)
    for c in getattr(page, "characters", []) or []:
        ids.add(c)
    for p in getattr(page, "props", []) or []:
        ids.add(p)
    for pnl in page.panels:
        for c in getattr(pnl, "characters", []) or []: ids.add(c)
        if getattr(pnl, "location_id", None): ids.add(pnl.location_id)
        for pr in getattr(pnl, "props", []) or []: ids.add(pr)
    return ids

def _has_any_ref_assets(obj) -> bool:
    return bool(getattr(obj, "reference_assets", []) or [])

def _ensure_ref_assets_for_ids(job_id: str, workdir: str, doc: LookbookDoc, ids: Set[str]) -> Tuple[LookbookDoc, Dict[str, str]]:
    """
    Ensures each id has at least one reference asset.
    If some IDs exist in lookbook but have no assets, we auto-generate defaults.
    If an ID is completely missing from lookbook, we mark it missing and the page will block.
    Returns: (possibly-updated lookbook doc, missing map {id: reason})
    """
    idx = _index_lookbook(doc)
    missing: Dict[str, str] = {}

    # IDs missing from lookbook entirely
    for _id in ids:
        if _id not in idx:
            missing[_id] = "not_found_in_lookbook"

    # Generate assets for entries that exist but lack refs
    need_gen = []
    for _id in ids:
        if _id in idx:
            kind, obj = idx[_id]
            if not _has_any_ref_assets(obj):
                need_gen.append(_id)

    if need_gen:
        try:
            req = GenerateRefAssetsRequest(job_id=job_id, ids=need_gen, force=False)
            generate_ref_assets(req)  # will update lookbook.json on disk + GCS
            # Reload the lookbook to reflect new assets
            doc = _load_lookbook(workdir)
        except Exception as e:
            log.exception(f"auto-generate ref assets failed for {need_gen}: {e}")
            for _id in need_gen:
                missing[_id] = "ref_assets_generation_failed"

    # Final verification
    idx = _index_lookbook(doc)
    for _id in ids:
        if _id in idx:
            _, obj = idx[_id]
            if not _has_any_ref_assets(obj):
                missing[_id] = "no_reference_assets"
    return doc, missing

def _compact_canon(canon: dict) -> dict:
    """
    Keep lookbook slice small: pick a few key fields if present.
    """
    if not canon:
        return {}
    keys = ["face", "hair", "body", "palette", "costume_variants", "emblems", "key_props", "lighting", "negative_traits", "notes"]
    return {k: v for k, v in canon.items() if k in keys}

def _build_lookbook_slice(doc: LookbookDoc, ids: Set[str]) -> dict:
    idx = _index_lookbook(doc)
    slice_obj = {"characters": [], "locations": [], "props": []}
    for _id in ids:
        if _id not in idx:
            continue
        kind, obj = idx[_id]
        refs = (getattr(obj, "reference_assets", []) or [])[:3]  # cap to first 3
        entry = {
            "id": _id,
            "display_name": getattr(obj, "display_name", None) or getattr(obj, "name", None) or _id,
            "visual_canon": _compact_canon(getattr(obj, "visual_canon", {}) or {}),
            "reference_assets": [{"type": r.type, "url": r.url} for r in refs],
        }
        slice_obj[kind + "s"].append(entry)
    return slice_obj

def _json_inline(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)

# -------------------------
# Prompt builders
# -------------------------

def _numbered_panel_lines(panels: List[Panel]) -> List[str]:
    lines: List[str] = []
    for panel in panels:
        ln = f"{panel.panel_number}) Art: {panel.art_description.strip()}"
        if panel.dialogue.strip(): ln += f" | Dialogue: {panel.dialogue.strip()}"
        if panel.narration.strip(): ln += f" | Narration: {panel.narration.strip()}"
        if panel.sfx.strip(): ln += f" | SFX: {panel.sfx.strip()}"
        lines.append(ln)
    return lines

def _build_page_prompt(
    req: ComicRequest,
    page: Page,
    lookbook_slice: dict,
) -> str:
    numbered = _numbered_panel_lines(page.panels)
    return (
        f"{req.comic_title} — Page {page.page_number}\n\n"
        "**CONTINUITY (SCENE):**\n"
        "- Use the attached previous-page image ONLY for camera staging, layout, and lighting continuity.\n\n"
        "**IDENTITY (MANDATORY — from LOOKBOOK):**\n"
        "Use ONLY the following canonical entities for faces, bodies, outfits, props, and locations. "
        "Do NOT invent new characters/props/locations, and do NOT alter identity traits.\n"
        f"{_json_inline(lookbook_slice)}\n\n"
        "**STYLE (GLOBAL):**\n"
        f'The overall style must be consistent with the **\"{req.style}\"** theme. '
        "Bold, clean line work with dynamic lighting.\n\n"
        "**RULES:**\n"
        "- Identity comes from LOOKBOOK (above). Previous page is for scene only.\n"
        "- Keep main faces unobstructed; do not add glasses/masks unless specified.\n"
        "- Respect negative traits and outfit variants if present.\n\n"
        "**PANELS (ILLUSTRATE EXACTLY):**\n" + "\n".join(numbered)
    )

# -------------------------
# Renderer
# -------------------------

def render_pages_chained(
    *,
    job_id: str,            # NEW
    req: ComicRequest,
    workdir: str,
    cover_image_ref: str,
    manifest_file: str,
    gcs_prefix: Optional[str] = None,
) -> List[str]:
    """
    Sequential generation where page N uses page N-1 as a reference image,
    and IDENTITY comes from Lookbook slice for the page's required IDs.
    Page 1 uses the cover image as reference.
    """
    out_prefix = os.path.join(workdir, "page")
    results: List[str] = []
    prev_ref = cover_image_ref

    # Load lookbook once (we'll reload only if we auto-generate assets)
    try:
        lookbook = _load_lookbook(workdir)
    except FileNotFoundError as e:
        # block whole job early
        log.error(str(e))
        return results

    for idx, page in enumerate(req.pages):
        mf = load_manifest(manifest_file)
        if mf.get("cancelled"):
            log.info(f"[job cancelled] stopping at page {idx+1}")
            break

        page_no = idx + 1

        # ---- Collect IDs for this page ----
        ids = _collect_page_ids(page)

        # ---- Ensure reference assets exist (auto-generate if missing) ----
        lookbook, missing = _ensure_ref_assets_for_ids(job_id, workdir, lookbook, ids)
        if missing:
            # Mark and stop the chain; caller can re-enqueue after fixing/generating assets
            mark_page_status(
                manifest_file,
                page_no,
                "blocked_missing_refs",
                {"ids": sorted(list(missing.keys())), "reasons": missing}
            )
            log.warning(f"[page {page_no}] blocked; missing lookbook refs: {missing}")
            break

        # ---- Build lookbook slice for prompt ----
        slice_obj = _build_lookbook_slice(lookbook, ids)

        prompt = _build_page_prompt(req, page, slice_obj)

        # mark running
        mark_page_status(
            manifest_file,
            page_no,
            "running",
            {
                "prompt_chars": len(prompt),
                "prev_ref": prev_ref,
                "ids_used": sorted(list(ids)),
                "refs_used": {
                    "characters": [r["url"] for c in slice_obj["characters"] for r in c["reference_assets"]],
                    "locations":  [r["url"] for l in slice_obj["locations"]  for r in l["reference_assets"]],
                    "props":      [r["url"] for p in slice_obj["props"]      for r in p["reference_assets"]],
                },
            },
        )

        filename = f"{out_prefix}-{page_no}.png"
        tmpname = f"{filename}.part"
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

        model = config.openai_image_model
        size = config.image_size
        retries = 3
        delay = 2.0
        last_error = None

        for attempt in range(1, retries + 1):
            try:
                mark_page_status(manifest_file, page_no, "running", {"attempts": attempt})
                with open(prev_ref, "rb") as ref_f:
                    resp = client.images.edit(
                        model=model,
                        prompt=prompt,
                        size=size,
                        n=1,
                        image=ref_f,
                    )
                b64 = resp.data[0].b64_json

                # atomic write
                with open(tmpname, "wb") as f:
                    f.write(base64.b64decode(b64))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmpname, filename)

                mark_page_status(
                    manifest_file,
                    page_no,
                    "rendered",
                    {"attempts": attempt, "local": filename},
                )

                # try upload this page
                if gcs_prefix:
                    try:
                        object_name = f"{gcs_prefix}/pages/page-{page_no}.png"
                        info = upload_to_gcs(filename, object_name=object_name)
                        mark_page_status(
                            manifest_file,
                            page_no,
                            "done",
                            {"attempts": attempt, "uploaded": True, "gcs": info, "local": filename},
                        )
                    except Exception as up_e:
                        log.exception(f"GCS upload failed for page {page_no}: {up_e}")
                        mark_page_status(
                            manifest_file,
                            page_no,
                            "rendered",
                            {"attempts": attempt, "uploaded": False, "upload_error": str(up_e), "local": filename},
                        )

                # success — chain next page to this output
                results.append(filename)
                prev_ref = filename
                break

            except Exception as e:
                last_error = str(e)
                log.warning(f"[page {page_no}] generate failed attempt {attempt}/{retries}: {e}")
                if attempt < retries:
                    import random, time
                    time.sleep((delay * (2 ** (attempt - 1))) + random.uniform(0, 0.5))

        if not os.path.exists(filename):
            # final failure for this page; mark and stop the chain
            mark_page_status(manifest_file, page_no, "failed", {"last_error": last_error})
            break

    return results
