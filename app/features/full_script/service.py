import hashlib
import json
import os
import time
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from pydantic import ValidationError

from app.config import config
from app.lib.openai_client import client
from app.lib.paths import job_dir
from app.features.lookbook_seed.schemas import LookbookDoc
from .schemas import (
    FullScriptPagesResponse,
    FullScriptRequest,
)

from .prompt import (
    _format_known,
    _targets_for_pages,
    build_full_script_prompt,
)

RAW_DIR = "app/output/full_script_raw"


# ---------- Lookbook helpers ----------

def _load_lookbook(job_id: str | None) -> LookbookDoc | None:
    if not job_id:
        return None
    path = os.path.join(job_dir(job_id), "lookbook.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return LookbookDoc.model_validate(json.load(f))
    except Exception:
        return None


def _index_lookbook(lb: LookbookDoc | None) -> Dict[str, List[Dict[str, str]]]:
    """
    Build a compact catalog of known entities for the prompt.
    For characters, include gender if available (prefer 'gender' field, else visual_canon['gender']).
    """
    if not lb:
        return {"characters": [], "locations": [], "props": []}

    known_chars: List[Dict[str, str]] = []
    for c in (lb.characters or []):
        # Try to pull a gender hint if present
        vis = c.visual_canon or {}
        notes = (vis.get("notes") or "").lower()
        gender = None
        # naive scrape from notes: "gender: male/female/unspecified"
        if "gender:" in notes:
            try:
                after = notes.split("gender:", 1)[1].strip()
                gender = after.split(";")[0].strip()
            except Exception:
                gender = None

        known_chars.append({
            "id": c.id,
            "display_name": c.display_name,
            "gender": (gender or "").strip(),
        })

    known_locs = [{"id": l.id, "name": l.name} for l in (lb.locations or [])]
    known_props = [{"id": p.id, "name": p.name} for p in (lb.props or [])]

    return {"characters": known_chars, "locations": known_locs, "props": known_props}


# ---------- JSON schema for response_format ----------

def _full_script_json_schema() -> dict:
    string = {"type": "string"}
    nonempty = {"type": "string", "minLength": 1}

    id_char = {"type": "string", "pattern": r"^char_[a-z0-9_]+$"}
    id_loc = {"type": "string", "pattern": r"^loc_[a-z0-9_]+$"}
    id_prop = {"type": "string", "pattern": r"^prop_[a-z0-9_]+$"}
    loc_or_empty = {"type": "string", "pattern": r"^(|loc_[a-z0-9_]+)$"}

    char_arr = {"type": "array", "items": id_char}
    prop_arr = {"type": "array", "items": id_prop}

    panel = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "panel_number": {"type": "integer", "minimum": 1},
            "art_description": string,
            "dialogue": string,
            "narration": string,
            "sfx": string,
            "characters": char_arr,
            "props": prop_arr,
            "location_id": loc_or_empty,
        },
        "required": [
            "panel_number",
            "art_description",
            "dialogue",
            "narration",
            "sfx",
            "characters",
            "props",
            "location_id",
        ],
    }

    page = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_number": {"type": "integer", "minimum": 1},
            "panels": {"type": "array", "minItems": 1, "items": panel},
            "location_id": loc_or_empty,
            "characters": char_arr,
            "props": prop_arr,
        },
        "required": ["page_number", "panels", "location_id", "characters", "props"],
    }

    item_char = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": id_char,
            "display_name": nonempty,
            "role": nonempty,
            "visual_stub": nonempty,
            "needs_concept_sheet": {"type": "boolean"},
        },
        "required": ["id", "display_name", "role", "visual_stub", "needs_concept_sheet"],
    }
    item_loc = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": id_loc,
            "name": nonempty,
            "visual_stub": nonempty,
            "needs_concept_sheet": {"type": "boolean"},
        },
        "required": ["id", "name", "visual_stub", "needs_concept_sheet"],
    }
    item_prop = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": id_prop,
            "name": nonempty,
            "visual_stub": nonempty,
            "needs_concept_sheet": {"type": "boolean"},
        },
        "required": ["id", "name", "visual_stub", "needs_concept_sheet"],
    }

    lookbook_delta = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "characters_to_add": {"type": "array", "items": item_char},
            "locations_to_add": {"type": "array", "items": item_loc},
            "props_to_add": {"type": "array", "items": item_prop},
        },
        "required": ["characters_to_add", "locations_to_add", "props_to_add"],
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "pages": {"type": "array", "minItems": 1, "items": page},
            "lookbook_delta": lookbook_delta,
        },
        "required": ["pages", "lookbook_delta"],
    }


SYSTEM_MSG = (
    "You are an elite-level comic writer & storyboard artist. "
    "Return ONLY a single JSON object that strictly conforms to the provided JSON Schema. "
    "No commentary, no markdown."
)


# ---------- small IO helpers ----------

def _extract_json_str(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    s = raw.find("{")
    e = raw.rfind("}")
    if s != -1 and e != -1 and e > s:
        return raw[s : e + 1]
    return raw


def _save_raw(job_id: str | None, payload: str, suffix: str):
    os.makedirs(RAW_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    jid = job_id or "nojob"
    h = hashlib.sha1((payload or "").encode("utf-8")).hexdigest()[:8]
    path = os.path.join(RAW_DIR, f"{jid}-{stamp}-{suffix}-{h}.txt")
    try:
        with open(path, "w") as f:
            f.write(payload or "")
    except Exception:
        pass
    return path


def _max_tokens_for(req: FullScriptRequest) -> int:
    # rough budget: 600 per page + headroom, capped
    return min(8192, 600 * max(1, req.page_count) + 800)


async def _call_llm(prompt: str, max_tokens: int, short_mode: bool = False) -> str:
    schema = _full_script_json_schema()
    final_prompt = prompt
    if short_mode:
        final_prompt += (
            "\n\nOUTPUT BREVITY OVERRIDE:\n"
            "- Keep dialogue ≤ 120 chars, narration ≤ 120 chars, sfx ≤ 20 chars.\n"
            "- If at risk of overflow, abbreviate descriptions.\n"
            "- Always return VALID JSON per the schema."
        )

    resp = client.chat.completions.create(
        model=getattr(config, "openai_text_model", "gpt-4o-mini"),
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "FullScriptPagesResponse", "schema": schema, "strict": True},
        },
        messages=[{"role": "system", "content": SYSTEM_MSG}, {"role": "user", "content": final_prompt}],
    )
    content = resp.choices[0].message.content or ""
    return content.strip()


# ---------- usage audit & repair ----------

def _collect_usage(script: FullScriptPagesResponse) -> Tuple[dict, dict, dict]:
    # id -> {"count": int, "pages": set()}
    char_usage: Dict[str, Dict[str, object]] = {}
    loc_usage: Dict[str, Dict[str, object]] = {}
    prop_usage: Dict[str, Dict[str, object]] = {}

    def bump(d, _id: str, page_num: int):
        ent = d.setdefault(_id, {"count": 0, "pages": set()})
        ent["count"] = int(ent["count"]) + 1  # type: ignore
        ent["pages"].add(page_num)            # type: ignore

    for page in script.pages:
        pnum = page.page_number
        if page.location_id:
            bump(loc_usage, page.location_id, pnum)
        for cid in (page.characters or []):
            bump(char_usage, cid, pnum)
        for pid in (page.props or []):
            bump(prop_usage, pid, pnum)
        for panel in page.panels:
            for cid in (panel.characters or []):
                bump(char_usage, cid, pnum)
            for pid in (panel.props or []):
                bump(prop_usage, pid, pnum)
            if panel.location_id:
                bump(loc_usage, panel.location_id, pnum)

    return char_usage, loc_usage, prop_usage


def _audit_usage(
    script: FullScriptPagesResponse,
    known: Dict[str, List[Dict[str, str]]],
    minima: Tuple[int, int, int],  # (NEW char min, NEW loc min, NEW prop min)
) -> dict:
    new_chars = [c.id for c in (script.lookbook_delta.characters_to_add or [])]
    new_locs = [l.id for l in (script.lookbook_delta.locations_to_add or [])]
    new_props = [p.id for p in (script.lookbook_delta.props_to_add or [])]

    known_char_ids = {it["id"] for it in known.get("characters", [])}
    known_loc_ids = {it["id"] for it in known.get("locations", [])}
    known_prop_ids = {it["id"] for it in known.get("props", [])}

    allowed_chars = known_char_ids | set(new_chars)
    allowed_locs = known_loc_ids | set(new_locs)
    allowed_props = known_prop_ids | set(new_props)

    # panel-level counts
    char_panel_counts = defaultdict(int)
    prop_panel_counts = defaultdict(int)
    loc_page_counts = defaultdict(int)
    loc_panel_counts = defaultdict(int)

    for page in script.pages:
        if page.location_id:
            loc_page_counts[page.location_id] += 1
        for panel in page.panels:
            for cid in (panel.characters or []):
                char_panel_counts[cid] += 1
            for pid in (panel.props or []):
                prop_panel_counts[pid] += 1
            if panel.location_id:
                loc_panel_counts[panel.location_id] += 1

    used_chars = set(char_panel_counts.keys())
    used_props = set(prop_panel_counts.keys())
    used_locs = set(loc_page_counts.keys()) | set(loc_panel_counts.keys())

    unknown = {
        "char": sorted(used_chars - allowed_chars),
        "loc": sorted(used_locs - allowed_locs),
        "prop": sorted(used_props - allowed_props),
    }

    issues: List[str] = []
    if unknown["char"]:
        issues.append(f"Unknown character IDs used: {', '.join(unknown['char'])}.")
    if unknown["loc"]:
        issues.append(f"Unknown location IDs used: {', '.join(unknown['loc'])}.")
    if unknown["prop"]:
        issues.append(f"Unknown prop IDs used: {', '.join(unknown['prop'])}.")

    missing = {"char": [], "loc": [], "prop": []}

    for cid in new_chars:
        n = char_panel_counts.get(cid, 0)
        if n < 2:
            missing["char"].append(cid)
            issues.append(f"character {cid}: {n} panel uses; needs ≥2.")

    for pid in new_props:
        n = prop_panel_counts.get(pid, 0)
        if n < 2:
            missing["prop"].append(pid)
            issues.append(f"prop {pid}: {n} panel uses; needs ≥2.")

    for lid in new_locs:
        pgs = loc_page_counts.get(lid, 0)
        pnl = loc_panel_counts.get(lid, 0)
        if pgs < 1 and pnl < 2:
            missing["loc"].append(lid)
            issues.append(
                f"location {lid}: {pgs} pages, {pnl} panels; needs ≥1 page.location_id OR ≥2 panels."
            )

    cmin, lmin, pmin = minima
    need_more = {
        "char": max(0, cmin - len(new_chars)),
        "loc": max(0, lmin - len(new_locs)),
        "prop": max(0, pmin - len(new_props)),
    }
    if need_more["char"]:
        issues.append(f"Need at least {cmin} NEW characters (have {len(new_chars)}).")
    if need_more["loc"]:
        issues.append(f"Need at least {lmin} NEW locations (have {len(new_locs)}).")
    if need_more["prop"]:
        issues.append(f"Need at least {pmin} NEW props (have {len(new_props)}).")

    ok = len(issues) == 0

    return {
        "ok": ok,
        "issues": issues,
        "missing_usage": {k: v for k, v in missing.items() if v},
        "need_more": {k: v for k, v in need_more.items() if v},
        "unknown_used": {k: v for k, v in unknown.items() if v},
        "counts": {
            "new": {"char": len(new_chars), "loc": len(new_locs), "prop": len(new_props)},
            "usage": {
                "char_panels": dict(char_panel_counts),
                "prop_panels": dict(prop_panel_counts),
                "loc_pages": dict(loc_page_counts),
                "loc_panels": dict(loc_panel_counts),
            },
        },
    }


async def _repair_script_once(
    req: FullScriptRequest,
    known: Dict[str, List[Dict[str, str]]],
    original: FullScriptPagesResponse,
    audit: dict,
) -> FullScriptPagesResponse:
    """
    Minimal edit pass to meet NEW minima and usage counts with zero schema/key changes.
    """
    known_chars_txt = _format_known("Characters", known.get("characters", []))
    known_locs_txt = _format_known("Locations", known.get("locations", []))
    known_props_txt = _format_known("Props", known.get("props", []))

    issues_text = "\n".join(f"- {m}" for m in audit.get("issues", [])) or "- none"

    original_json = original.model_dump_json()

    repair_prompt = f"""
REPAIR TASK (MAKE MINIMAL, TARGETED EDITS ONLY):

A) DO NOT change keys, schema, or page_number. Keep the exact structure. Return a single VALID JSON object.

B) NEW ENTITY MINIMA (MANDATORY):
   - If lookbook_delta is below minima from the user brief, ADD missing NEW entities:
       • Characters: reach the minimum count; each NEW character appears in ≥2 distinct panels.
       • Locations:  reach the minimum count; each NEW location is used as page.location_id on ≥1 page OR appears in ≥2 panels.
       • Props:      reach the minimum count; each NEW prop appears in ≥2 distinct panels.
   - IDs: char_*, loc_*, prop_* (slugify display names).
   - For NEW characters, visual_stub MUST begin with "gender: ...".
   - NEVER duplicate any ID from KNOWN ENTITIES.

C) USAGE CONSISTENCY (MANDATORY):
   - NEW chars/props must be referenced in ≥2 panels.
   - NEW locations: ≥1 page.location_id OR ≥2 panel mentions.
   - If an added NEW ID cannot be reasonably used, remove it from lookbook_delta.

D) MINIMAL CONTENT CHANGES:
   - Only adjust panel characters/props/location_id and brief art_description/dialogue where strictly needed.

E) DELTA EXACTNESS:
   - After edits, set lookbook_delta to EXACTLY the set of IDs used in pages that are NOT in KNOWN ENTITIES, with proper stubs.

KNOWN ENTITIES (reuse only; do not re-add to delta):
{known_chars_txt}{known_locs_txt}{known_props_txt}

ISSUES TO FIX:
{issues_text}

CURRENT SCRIPT JSON (fix and return as a COMPLETE, VALID JSON object):
{original_json}
""".strip()

    raw = await _call_llm(repair_prompt, max_tokens=_max_tokens_for(req), short_mode=True)
    cleaned = _extract_json_str(raw)
    return FullScriptPagesResponse.model_validate_json(cleaned)


def _prune_unused_from_delta(script: FullScriptPagesResponse):
    """
    Remove any delta items that do not meet the required usage thresholds.
    """
    char_panel_counts = defaultdict(int)
    prop_panel_counts = defaultdict(int)
    loc_page_counts = defaultdict(int)
    loc_panel_counts = defaultdict(int)

    for page in script.pages:
        if page.location_id:
            loc_page_counts[page.location_id] += 1
        for panel in page.panels:
            for cid in (panel.characters or []):
                char_panel_counts[cid] += 1
            for pid in (panel.props or []):
                prop_panel_counts[pid] += 1
            if panel.location_id:
                loc_panel_counts[panel.location_id] += 1

    script.lookbook_delta.characters_to_add = [
        c for c in (script.lookbook_delta.characters_to_add or []) if char_panel_counts.get(c.id, 0) >= 2
    ]
    script.lookbook_delta.props_to_add = [
        p for p in (script.lookbook_delta.props_to_add or []) if prop_panel_counts.get(p.id, 0) >= 2
    ]
    script.lookbook_delta.locations_to_add = [
        l
        for l in (script.lookbook_delta.locations_to_add or [])
        if (loc_page_counts.get(l.id, 0) >= 1) or (loc_panel_counts.get(l.id, 0) >= 2)
    ]


def _required_new_counts(page_count: int) -> Tuple[int, int, int]:
    """
    For simplicity: we ALWAYS want the NEW minima by page count (not total-minus-known).
    """
    (cmin, _), (lmin, _), (pmin, _) = _targets_for_pages(page_count)
    return cmin, lmin, pmin


# ---------- main entry ----------

async def generate_full_script(req: FullScriptRequest) -> FullScriptPagesResponse:
    lb = _load_lookbook(req.job_id)
    known = _index_lookbook(lb)

    need_chars, need_locs, need_props = _required_new_counts(req.page_count)
    prompt = build_full_script_prompt(req, known, need_chars, need_locs, need_props)
    max_tokens = _max_tokens_for(req)

    raw = await _call_llm(prompt, max_tokens=max_tokens, short_mode=False)
    _save_raw(getattr(req, "job_id", None), raw, "try1")
    cleaned = _extract_json_str(raw)

    try:
        script = FullScriptPagesResponse.model_validate_json(cleaned)
    except Exception:
        raw2 = await _call_llm(prompt, max_tokens=max_tokens, short_mode=True)
        _save_raw(getattr(req, "job_id", None), raw2, "try2")
        cleaned2 = _extract_json_str(raw2)
        script = FullScriptPagesResponse.model_validate_json(cleaned2)

    # Audit & optional repair with the same NEW minima
    audit = _audit_usage(script, known, minima=(need_chars, need_locs, need_props))
    if not audit["ok"]:
        try:
            repaired = await _repair_script_once(req, known, script, audit)
            _save_raw(getattr(req, "job_id", None), repaired.model_dump_json(), "repair1")
            audit2 = _audit_usage(repaired, known, minima=(need_chars, need_locs, need_props))
            if audit2["ok"]:
                script = repaired
            else:
                _prune_unused_from_delta(repaired)
                script = repaired
        except Exception:
            _prune_unused_from_delta(script)

    return script
