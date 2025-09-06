# app/features/comic/service.py
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

from fastapi import HTTPException
import requests

from app.config import config
from app.features.full_script.schemas import Page, Panel
from app.features.lookbook_ref_assets.schemas import GenerateRefAssetsRequest
from app.features.lookbook_ref_assets.service import generate_ref_assets
from app.features.lookbook_seed.schemas import LookbookDoc
from app.features.pages.schemas import ComicRequest
from app.lib.gcs_inventory import download_gcs_object_to_file, upload_to_gcs
from app.lib.jobs import load_manifest, mark_page_status
from app.lib.openai_client import client
from app.logger import get_logger

log = get_logger(__name__)

# -------------------------------------------------------------------
# Lookbook IO + indexing
# -------------------------------------------------------------------

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
    Build id -> (kind, object) where kind in {"character","location","prop"}.
    """
    idx: Dict[str, Tuple[str, object]] = {}
    for c in doc.characters:
        idx[c.id] = ("character", c)
    for l in doc.locations:
        idx[l.id] = ("location", l)
    for p in doc.props:
        idx[p.id] = ("prop", p)
    return idx

# -------------------------------------------------------------------
# Page entity collection + lookbook slice building
# -------------------------------------------------------------------

def _collect_page_ids(page: Page) -> Set[str]:
    ids: Set[str] = set()
    if getattr(page, "location_id", None):
        if page.location_id:
            ids.add(page.location_id)
    for c in (getattr(page, "characters", None) or []):
        if c:
            ids.add(c)
    for p in (getattr(page, "props", None) or []):
        if p:
            ids.add(p)
    for pnl in page.panels:
        for c in (getattr(pnl, "characters", None) or []):
            if c:
                ids.add(c)
        if getattr(pnl, "location_id", None):
            if pnl.location_id:
                ids.add(pnl.location_id)
        for pr in (getattr(pnl, "props", None) or []):
            if pr:
                ids.add(pr)
    return ids

def _has_any_ref_assets(obj) -> bool:
    return bool(getattr(obj, "reference_assets", []) or [])

def _ensure_ref_assets_for_ids(
    job_id: str,
    workdir: str,
    doc: LookbookDoc,
    ids: Set[str],
) -> Tuple[LookbookDoc, Dict[str, str]]:
    """
    Ensure each used ID has at least one reference asset.
    - If an ID is missing from the lookbook entirely -> mark missing.
    - If present but has 0 refs -> call gen-ref-assets (force=False).
    Returns (possibly reloaded lookbook, missing map).
    """
    idx = _index_lookbook(doc)
    missing: Dict[str, str] = {}

    # IDs that don't exist
    for _id in ids:
        if _id not in idx:
            missing[_id] = "not_found_in_lookbook"

    # Generate for entries with no refs
    need_gen = []
    for _id in ids:
        if _id in idx:
            _, obj = idx[_id]
            if not _has_any_ref_assets(obj):
                need_gen.append(_id)

    if need_gen:
        try:
            req = GenerateRefAssetsRequest(job_id=job_id, ids=need_gen, force=False)
            generate_ref_assets(req)  # updates lookbook.json on disk/GCS
            doc = _load_lookbook(workdir)  # reload
        except Exception as e:
            log.exception(f"auto-generate ref assets failed for {need_gen}: {e}")
            for _id in need_gen:
                missing[_id] = "ref_assets_generation_failed"

    # Final verify
    idx = _index_lookbook(doc)
    for _id in ids:
        if _id in idx:
            _, obj = idx[_id]
            if not _has_any_ref_assets(obj):
                missing[_id] = "no_reference_assets"

    return doc, missing

def _compact_canon(canon: dict) -> dict:
    """
    Keep lookbook slice compact for prompts.
    """
    if not canon:
        return {}
    keys = [
        "face", "hair", "body", "palette", "costume_variants",
        "emblems", "key_props", "lighting", "negative_traits", "notes"
    ]
    return {k: v for k, v in canon.items() if k in keys}

# def _build_lookbook_slice(doc: LookbookDoc, ids: Set[str]) -> dict:
#     """
#     Build a small, page-scoped lookbook fragment:
#     {
#       "characters": [{id, display_name, visual_canon, reference_assets:[{type,url}]}],
#       "locations":  [...],
#       "props":      [...]
#     }
#     """
#     idx = _index_lookbook(doc)
#     out = {"characters": [], "locations": [], "props": []}
#     for _id in ids:
#         if _id not in idx:
#             continue
#         kind, obj = idx[_id]
#         refs = (getattr(obj, "reference_assets", []) or [])[:3]  # small cap
#         entry = {
#             "id": _id,
#             "display_name": getattr(obj, "display_name", None) or getattr(obj, "name", None) or _id,
#             "visual_canon": _compact_canon(getattr(obj, "visual_canon", {}) or {}),
#             "reference_assets": [{"type": r.type, "url": r.url} for r in refs],
#         }
#         out[kind + "s"].append(entry)
#     return out

def _build_lookbook_slice(doc: LookbookDoc, ids: Set[str]) -> dict:
    idx = _index_lookbook(doc)
    out = {"characters": [], "locations": [], "props": []}
    for _id in ids:
        if _id not in idx:
            continue
        kind, obj = idx[_id]
        refs = (getattr(obj, "reference_assets", []) or [])[:3]
        entry = {
            "id": _id,
            "display_name": getattr(obj, "display_name", None) or getattr(obj, "name", None) or _id,
            "visual_canon": _compact_canon(getattr(obj, "visual_canon", {}) or {}),
            "reference_assets": [
                {
                    "type": r.type,
                    "url": getattr(r, "url", None),
                    "gs_uri": getattr(r, "gs_uri", None),
                }
                for r in refs
            ],
        }
        out[kind + "s"].append(entry)
    return out

def _collect_entity_names(lookbook_slice: dict) -> Tuple[List[str], List[str], List[str]]:
    chars = [c.get("display_name", c.get("id", "")) for c in lookbook_slice.get("characters", [])]
    locs  = [l.get("display_name", l.get("id", "")) for l in lookbook_slice.get("locations", [])]
    props = [p.get("display_name", p.get("id", "")) for p in lookbook_slice.get("props", [])]
    # remove empties
    chars = [x for x in chars if x]
    locs  = [x for x in locs if x]
    props = [x for x in props if x]
    return chars, locs, props

# -------------------------------------------------------------------
# Ref image resolution / caching
# -------------------------------------------------------------------

def _cache_dir(workdir: str) -> str:
    d = os.path.join(workdir, "ref_cache")
    os.makedirs(d, exist_ok=True)
    return d

def _safe_name(u: str) -> str:
    h = hashlib.sha1(u.encode("utf-8")).hexdigest()[:12]
    base = os.path.basename(urlparse(u).path) or "ref.png"
    return f"{h}_{base}"

def _resolve_asset_url_to_path(url: str, workdir: str) -> Optional[str]:
    """
    Save gs:// or http(s) asset to local cache and return path.
    """
    try:
        cdir = _cache_dir(workdir)
        local = os.path.join(cdir, _safe_name(url))
        if os.path.exists(local) and os.path.getsize(local) > 0:
            return local

        if url.startswith("gs://"):
            download_gcs_object_to_file(url, local)
            return local if os.path.exists(local) and os.path.getsize(local) > 0 else None

        if url.startswith("http://") or url.startswith("https://"):
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            with open(local, "wb") as f:
                f.write(r.content)
            return local if os.path.getsize(local) > 0 else None

    except Exception as e:
        log.warning(f"failed to resolve asset url -> path: {url} ({e})")
    return None

def _cache_dir(workdir: str) -> str:
    d = os.path.join(workdir, "_ref_cache")
    os.makedirs(d, exist_ok=True)
    return d

def _safe_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^A-Za-z0-9_.\-]+", "_", s)
    return s[:160] or "ref"

def _https_to_gs(url: str) -> str | None:
    """
    Convert common GCS HTTPS forms to gs://bucket/key
    Works for:
      https://storage.googleapis.com/<bucket>/<key>[?...]
      https://<bucket>.storage.googleapis.com/<key>[?...]
      https://storage.cloud.google.com/<bucket>/<key>[?...]
    """
    try:
        u = urlparse(url)
        host = u.netloc.lower()
        path = unquote(u.path)

        if host == "storage.googleapis.com":
            # /bucket/key...
            parts = path.lstrip("/").split("/", 1)
            if len(parts) == 2:
                bucket, key = parts
                return f"gs://{bucket}/{key}"

        if host.endswith(".storage.googleapis.com"):
            # bucket.storage.googleapis.com/key...
            bucket = host.split(".storage.googleapis.com", 1)[0]
            key = path.lstrip("/")
            if bucket and key:
                return f"gs://{bucket}/{key}"

        if host == "storage.cloud.google.com":
            # /bucket/key...
            parts = path.lstrip("/").split("/", 1)
            if len(parts) == 2:
                bucket, key = parts
                return f"gs://{bucket}/{key}"
    except Exception:
        pass
    return None

def _resolve_asset_ref_to_path(ref: dict, workdir: str) -> str | None:
    """
    Prefer gs://; fall back to HTTP; if HTTP fails, convert to gs:// and try again.
    `ref` may contain {"url": "...", "gs_uri": "..."}.
    """
    gs = (ref.get("gs_uri") or "").strip()
    url = (ref.get("url") or "").strip()
    cache = _cache_dir(workdir)

    print("gs is", gs)
    # Try gs:// first (most reliable)
    if gs:
        print("yoyo0")
        local = os.path.join(cache, _safe_name(gs) + ".png")
        if os.path.exists(local) and os.path.getsize(local) > 0:
            print("yoyo1")
            return local
        try:
            print("yoyo2")
            download_gcs_object_to_file(gs, local)
            return local if os.path.getsize(local) > 0 else None
        except Exception as e:
            print("yoyo3")
            log.warning(f"failed gs fetch {gs}: {e}")

    # Try HTTP second
    if url.startswith("http://") or url.startswith("https://"):
        local = os.path.join(cache, _safe_name(url) + ".png")
        if os.path.exists(local) and os.path.getsize(local) > 0:
            return local
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            with open(local, "wb") as f:
                f.write(r.content)
            if os.path.getsize(local) > 0:
                return local
        except requests.HTTPError as e:
            # On 400/403 likely expired signed URL → convert to gs:// and retry
            alt_gs = _https_to_gs(url)
            if alt_gs:
                try:
                    local2 = os.path.join(cache, _safe_name(alt_gs) + ".png")
                    download_gcs_object_to_file(alt_gs, local2)
                    return local2 if os.path.getsize(local2) > 0 else None
                except Exception as e2:
                    log.warning(f"fallback gs fetch failed {alt_gs}: {e2}")
            else:
                log.warning(f"http fetch failed and no gs fallback for {url}: {e}")
        except Exception as e:
            log.warning(f"http fetch failed {url}: {e}")

    return None

def _collect_ref_paths_for_slice(
    *,
    workdir: str,
    lookbook_slice: dict,
    max_per_entity: int = 2,
    total_cap: int = 10,
) -> Tuple[List[str], str]:
    candidates = []
    print("lookbook_slice", lookbook_slice)
    def add_from(group_key: str):
        group = lookbook_slice.get(group_key, []) or []
        for entry in group:
            ent_id = (entry.get("id") or "").strip()
            name   = (entry.get("display_name") or entry.get("name") or ent_id).strip()
            refs   = entry.get("reference_assets", []) or []
            for r in refs[:max_per_entity]:
                p = _resolve_asset_ref_to_path(r or {}, workdir)
                if p:
                    candidates.append({
                        "path": p,
                        "id": ent_id,
                        "name": name,
                        "type": (r or {}).get("type", "") or "ref",
                        "group": group_key,
                    })

    add_from("characters")
    add_from("locations")
    add_from("props")
    print("candidates are ", candidates)

    # dedup & cap
    seen = set()
    uniq = []
    for it in candidates:
        if it["path"] in seen:
            continue
        seen.add(it["path"])
        uniq.append(it)
    uniq = uniq[:total_cap]

    ordered_paths = [it["path"] for it in uniq]

    # ordered block
    if not ordered_paths:
        return [], ""
    indices: dict[str, list[int]] = {}
    lines = []
    for i, it in enumerate(uniq, 1):
        lines.append(f"[{i}] {it['id']} • {it['type']} — {it['name']} ({it['group'][:-1]})")
        indices.setdefault(it["id"], []).append(i)

    def bind_line(it):
        idxs = ",".join(str(i) for i in indices.get(it["id"], []))
        g = it["group"]
        if g == "characters":
            return f"- {it['name']} ({it['id']}) ⇢ use refs [{idxs}] for facial likeness, hair, outfit."
        if g == "locations":
            return f"- {it['name']} ({it['id']}) ⇢ use refs [{idxs}] for architecture and lighting mood."
        return f"- {it['name']} ({it['id']}) ⇢ use refs [{idxs}] for design, scale, and palette."

    bindings = []
    for g in ("characters", "locations", "props"):
        added = set()
        for it in uniq:
            if it["group"] == g and it["id"] not in added:
                bindings.append(bind_line(it))
                added.add(it["id"])

    ordered_block = (
        "**ATTACHED REFERENCE IMAGES (ORDERED):**\n"
        + "\n".join(lines)
        + "\n\n**BINDING (MANDATORY):**\n"
        + "\n".join(bindings)
    )
    return ordered_paths, ordered_block


# def _collect_ref_paths_for_slice(
#     *,
#     workdir: str,
#     lookbook_slice: dict,
#     max_per_entity: int = 2,
#     total_cap: int = 10,
# ) -> Tuple[List[str], str]:
#     """
#     Turn page-scoped lookbook slice into local image paths with a global cap,
#     using the project's working _resolve_asset_url_to_path(url, workdir).

#     Returns:
#       - ordered_paths: List[str] — local file paths in the EXACT order to pass to images.edit(image=[...])
#       - ordered_block: str — a text block describing that order + explicit entity bindings
#     """
#     candidates: List[Dict] = []
#     print("candidates are ")
#     print("lookbook_slice", lookbook_slice)

#     def add_from(group_key: str):
#         group = lookbook_slice.get(group_key, []) or []
#         for entry in group:
#             ent_id = (entry.get("id") or "").strip()
#             name   = (entry.get("display_name") or entry.get("name") or ent_id).strip()
#             refs   = entry.get("reference_assets", []) or []
#             for r in refs[:max_per_entity]:
#                 # url = (r or {}).get("url", "") or ""
#                 typ = (r or {}).get("type", "") or "ref"
#                 p = _resolve_asset_url_to_path(r.get("url", ""), workdir)  # <-- YOUR resolver
#                 if p:
#                     candidates.append({
#                         "path": p,
#                         "id": ent_id,
#                         "name": name,
#                         "type": typ,
#                         "group": group_key,  # "characters" | "locations" | "props"
#                     })

#     # priority: characters → locations → props
#     add_from("characters")
#     add_from("locations")
#     add_from("props")

#     print("candidates are ", candidates, "\n")

#     # Dedup by path (preserve order), then cap
#     seen_paths = set()
#     unique: List[Dict] = []
#     for it in candidates:
#         p = it["path"]
#         if p in seen_paths:
#             continue
#         seen_paths.add(p)
#         unique.append(it)

#     unique = unique[:total_cap]

#     ordered_paths = [it["path"] for it in unique]
#     if not ordered_paths:
#         return [], ""

#     # Build the ordered block + explicit bindings
#     ordered_lines: List[str] = []
#     indices_by_entity: Dict[str, List[int]] = {}
#     name_by_entity: Dict[str, str] = {}
#     group_by_entity: Dict[str, str] = {}

#     for idx, it in enumerate(unique, start=1):
#         ent_id = it["id"]
#         name   = it["name"]
#         typ    = it["type"] or "ref"
#         group  = it["group"]
#         ordered_lines.append(f"[{idx}] {ent_id} • {typ} — {name} ({group[:-1]})")
#         indices_by_entity.setdefault(ent_id, []).append(idx)
#         name_by_entity[ent_id]  = name
#         group_by_entity[ent_id] = group

#     def _binding_line(ent_id: str) -> str:
#         idxs  = indices_by_entity.get(ent_id, [])
#         name  = name_by_entity.get(ent_id, ent_id)
#         group = group_by_entity.get(ent_id, "characters")
#         idx_str = ",".join(map(str, idxs))
#         if group == "characters":
#             return f"- {name} ({ent_id}) ⇢ use refs [{idx_str}] for facial likeness, hair, outfit details."
#         if group == "locations":
#             return f"- {name} ({ent_id}) ⇢ use refs [{idx_str}] for architecture, materials, and lighting mood."
#         return f"- {name} ({ent_id}) ⇢ use refs [{idx_str}] for design, scale, and palette."

#     bindings: List[str] = []
#     for g in ("characters", "locations", "props"):
#         added = set()
#         for it in unique:
#             if it["group"] != g:
#                 continue
#             ent_id = it["id"]
#             if ent_id in added:
#                 continue
#             bindings.append(_binding_line(ent_id))
#             added.add(ent_id)

#     ordered_block = (
#         "**ATTACHED REFERENCE IMAGES (ORDERED):**\n"
#         + "\n".join(ordered_lines)
#         + "\n\n**BINDING (MANDATORY):**\n"
#         + "\n".join(bindings)
#     )

#     return ordered_paths, ordered_block
# -------------------------------------------------------------------
# Prompt builders (page-level; cover-style sections)
# -------------------------------------------------------------------

def _json_inline(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)

def _numbered_panel_lines(panels: List[Panel]) -> List[str]:
    lines: List[str] = []
    for panel in panels:
        ln = f"{panel.panel_number}) Art: {panel.art_description.strip()}"
        if panel.dialogue and panel.dialogue.strip():
            ln += f" | Dialogue: {panel.dialogue.strip()}"
        if panel.narration and panel.narration.strip():
            ln += f" | Narration: {panel.narration.strip()}"
        if panel.sfx and panel.sfx.strip():
            ln += f" | SFX: {panel.sfx.strip()}"
        lines.append(ln)
    return lines

def _prev_context_from_page(prev: Page) -> dict:
    """
    Small continuity context from previous page's script object.
    """
    return {
        "prev_page_number": prev.page_number,
        "prev_location_id": prev.location_id or "",
        "prev_characters": prev.characters or [],
        "prev_props": prev.props or [],
    }

def _entities_by_panel(page: Page) -> Dict[int, Dict[str, List[str]]]:
    """
    Useful for manifest/debugging.
    """
    out: Dict[int, Dict[str, List[str]]] = {}
    for pnl in page.panels:
        out[pnl.panel_number] = {
            "characters": pnl.characters or [],
            "props": pnl.props or [],
            "location_id": [pnl.location_id] if getattr(pnl, "location_id", None) else [],
        }
    return out

def _identity_for_prompt(lookbook_slice: dict) -> dict:
    """
    Copy of lookbook_slice with reference_assets removed (no URLs in prompt).
    Keeps only id, display/display_name, and visual_canon.
    """
    out = {"characters": [], "locations": [], "props": []}
    for group in ("characters", "locations", "props"):
        for e in lookbook_slice.get(group, []) or []:
            out[group].append({
                "id": e.get("id"),
                "display_name": e.get("display_name") or e.get("name"),
                "visual_canon": e.get("visual_canon") or {},
                # intentionally drop reference_assets (URLs/types) from the prompt
            })
    return out

def _build_page_prompt(
    *,
    req: ComicRequest,
    page: Page,
    lookbook_slice: dict,
    ref_order_block: Optional[str] = None,
    prev_context: Optional[dict] = None,  # kept for compatibility
) -> str:
    """
    Page prompt mirroring the cover prompt structure, using ONLY attached lookbook refs.
    We do NOT include any asset URLs in the prompt.
    """
    numbered = _numbered_panel_lines(page.panels)

    # Display names for human-readable lines
    char_names, loc_names, prop_names = _collect_entity_names(lookbook_slice)

    char_line = f"- Characters (match facial likeness precisely): {', '.join(char_names)}.\n" if char_names else ""
    loc_line  = f"- Locations (architectural cues & lighting mood): {', '.join(loc_names)}.\n" if loc_names else ""
    prop_line = f"- Props (design & palette): {', '.join(prop_names)}.\n" if prop_names else ""

    only_chars_line = (
        f"- Include ONLY these characters: {', '.join(char_names)}. No other people or background figures.\n"
        if char_names else
        "- Avoid unintended people or background figures.\n"
    )

    # use identity without URLs for the prompt
    identity_slice_prompt = _json_inline(_identity_for_prompt(lookbook_slice))

    # optional ordered block describing image indices → entities
    ref_block = (ref_order_block.strip() + "\n") if ref_order_block else ""

    return (
        f"Create a finished interior comic page — **{req.comic_title}**, Page {page.page_number}.\n\n"
        "**ATTACHED REFERENCE IMAGES (HIGHEST PRIORITY):**\n"
        f"{ref_block}"
        "- Lookbook reference images for likeness, design, palette, and rendering style. "
        "Use character portraits, location wides, and prop details as available.\n"
        f"{char_line}{loc_line}{prop_line}\n"
        "**IDENTITY (MANDATORY — from LOOKBOOK):**\n"
        "Use ONLY the following canonical entities for faces, bodies, outfits, props, and locations. "
        "Do NOT invent new characters/props/locations and do NOT alter identity traits. "
        "Map the scene strictly to these IDs (URLs omitted by design):\n"
        f"{identity_slice_prompt}\n\n"
        "**PRIMARY SCENE (MANDATORY):**\n"
        "- Render the following panels exactly:\n"
        + "\n".join([f"  • {ln}" for ln in numbered])
        + "\n\n"
        "**ARTISTIC STYLE & EXECUTION (MANDATORY):**\n"
        f"* Theme/Style: \"{req.style}\" look. Bold, clean line work with dynamic, cinematic lighting.\n"
        "* Respect the attached references for likeness, materials, and color palette.\n"
        "* Keep main faces unobstructed; no added glasses/masks unless specified.\n\n"
        "**CRITICAL RULES:**\n"
        "* No unintended text, captions, speech bubbles, UI, or signage. Render pure artwork only.\n"
        "* No real-world brands/logos/trademarks.\n"
        f"{only_chars_line}"
    )



# -------------------------------------------------------------------
# Renderer (sequential; prev page + lookbook refs)
# -------------------------------------------------------------------

def render_pages_chained(
    *,
    job_id: str,
    req: ComicRequest,
    workdir: str,
    cover_image_ref: str,
    manifest_file: str,
    gcs_prefix: Optional[str] = None,
) -> List[str]:
    """
    Sequentially generate pages where page N uses:
      - previous rendered page (or cover for page 1) as first ref
      - plus lookbook reference images for the page's used IDs

    If a required ID is missing from the lookbook or lacks refs, the chain
    is blocked and the manifest marks which IDs need attention.
    """
    results: List[str] = []
    prev_ref = cover_image_ref
    out_prefix = os.path.join(workdir, "page")

    # Load lookbook initially
    try:
        lookbook = _load_lookbook(workdir)
    except FileNotFoundError as e:
        log.error(str(e))
        return results

    for idx, page in enumerate(req.pages):
        # cancellation check
        mf = load_manifest(manifest_file)
        if mf.get("cancelled"):
            log.info(f"[job cancelled] stopping at page {idx + 1}")
            break

        page_no = idx + 1

        # Collect IDs for this page
        ids = _collect_page_ids(page)

        # Ensure refs exist (auto-generate when possible)
        lookbook, missing = _ensure_ref_assets_for_ids(job_id, workdir, lookbook, ids)
        if missing:
            mark_page_status(
                manifest_file,
                page_no,
                "blocked_missing_refs",
                {"ids": sorted(list(missing.keys())), "reasons": missing},
            )
            log.warning(f"[page {page_no}] blocked; missing lookbook refs: {missing}")
            break

        # Build page-scoped lookbook slice + prev context
        slice_obj = _build_lookbook_slice(lookbook, ids)
        prev_ctx = _prev_context_from_page(req.pages[idx - 1]) if idx > 0 else None

        # Gather local ref files: previous page first + lookbook refs
        lookbook_ref_paths, lookbook_ref_paths_desc = _collect_ref_paths_for_slice(
            workdir=workdir,
            lookbook_slice=slice_obj,
            max_per_entity=2,
            total_cap=10,
        )
        image_paths_to_send = lookbook_ref_paths
        # Prompt (cover-style sections)
        prompt = _build_page_prompt(req=req, page=page, lookbook_slice=slice_obj, ref_order_block=lookbook_ref_paths_desc)

        # manifest: mark running + diagnostics
        panel_cast = _entities_by_panel(page)
        mark_page_status(
            manifest_file,
            page_no,
            "running",
            {
                "prompt_chars": len(prompt),
                "prev_ref": prev_ref,
                "ids_used": sorted(list(ids)),
                "panel_cast": panel_cast,
                "prev_context": prev_ctx or {},
                "refs_used": {
                    "characters": [r["url"] for c in slice_obj["characters"] for r in c["reference_assets"]],
                    "locations":  [r["url"] for l in slice_obj["locations"]  for r in l["reference_assets"]],
                    "props":      [r["url"] for p in slice_obj["props"]      for r in p["reference_assets"]],
                },
                "ref_paths_resolved": image_paths_to_send,
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

        def _open_files(paths: List[str]):
            return [open(p, "rb") for p in paths if p and os.path.exists(p)]

        for attempt in range(1, retries + 1):
            try:
                mark_page_status(manifest_file, page_no, "running", {"attempts": attempt})

                files = _open_files(image_paths_to_send)
                try:
                    resp = client.images.edit(
                        model=model,
                        prompt=prompt,
                        size=size,
                        n=1,
                        image=files,
                    )
                finally:
                    for f in files:
                        try:
                            f.close()
                        except Exception:
                            pass

                b64 = resp.data[0].b64_json
                with open(tmpname, "wb") as f:
                    f.write(base64.b64decode(b64))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmpname, filename)

                mark_page_status(
                    manifest_file,
                    page_no,
                    "rendered",
                    {
                        "attempts": attempt,
                        "local": filename,
                        "used_ref_paths": image_paths_to_send,
                    },
                )

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
                            {
                                "attempts": attempt,
                                "uploaded": False,
                                "upload_error": str(up_e),
                                "local": filename,
                            },
                        )

                results.append(filename)
                prev_ref = filename  # chain
                break

            except Exception as e:
                last_error = str(e)
                log.warning(f"[page {page_no}] generate failed attempt {attempt}/{retries}: {e}")
                if attempt < retries:
                    import random, time
                    time.sleep((delay * (2 ** (attempt - 1))) + random.uniform(0, 0.5))

        if not os.path.exists(filename):
            # final failure for this page; stop chain
            mark_page_status(manifest_file, page_no, "failed", {"last_error": last_error})
            break

    return results
