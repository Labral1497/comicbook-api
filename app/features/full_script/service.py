from collections import defaultdict
from pydantic import ValidationError
import json, os, hashlib, time
from typing import Dict, List, Tuple, Set
from app.lib.openai_client import client
from app.config import config
from .schemas import FullScriptRequest, FullScriptPagesResponse, LookbookDelta, CharacterToAdd, LocationToAdd, PropToAdd
from .prompt import build_full_script_prompt

# load lookbook to reuse IDs
from app.lib.paths import job_dir
from app.features.lookbook_seed.schemas import LookbookDoc

RAW_DIR = "app/output/full_script_raw"

# -------- Lookbook I/O --------

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
    if not lb:
        return {"characters": [], "locations": [], "props": []}

    known_chars: List[Dict[str, str]] = []
    for c in (lb.characters or []):
        g = getattr(c, "gender", None) or (c.visual_canon or {}).get("gender") or ""
        known_chars.append({"id": c.id, "display_name": c.display_name, "gender": g})

    known_locs = [{"id": l.id, "name": l.name} for l in (lb.locations or [])]
    known_props = [{"id": p.id, "name": p.name} for p in (lb.props or [])]
    return {"characters": known_chars, "locations": known_locs, "props": known_props}

# -------- JSON Schema for response_format (OpenAI-compatible subset) --------

def _full_script_json_schema() -> dict:
    # primitives
    string   = {"type": "string"}
    nonempty = {"type": "string", "minLength": 1}

    # id patterns
    id_char = {"type": "string", "pattern": r"^char_[a-z0-9_]+$"}
    id_loc  = {"type": "string", "pattern": r"^loc_[a-z0-9_]+$"}
    id_prop = {"type": "string", "pattern": r"^prop_[a-z0-9_]+$"}
    loc_or_empty = {"type": "string", "pattern": r"^(|loc_[a-z0-9_]+)$"}

    # arrays (no uniqueItems in strict mode)
    char_arr = {"type": "array", "items": id_char}
    prop_arr = {"type": "array", "items": id_prop}

    def obj(props: dict) -> dict:
        # strict-mode friendly: required must list every key in properties
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": props,
            "required": list(props.keys()),
        }

    panel = obj({
        "panel_number": {"type": "integer", "minimum": 1},
        "art_description": string,
        "dialogue": string,
        "narration": string,
        "sfx": string,
        "characters": char_arr,
        "props": prop_arr,
        "location_id": loc_or_empty,
    })

    page = obj({
        "page_number": {"type": "integer", "minimum": 1},
        "panels": {"type": "array", "minItems": 1, "items": panel},
        "location_id": loc_or_empty,
        "characters": char_arr,
        "props": prop_arr,
    })

    item_char = obj({
        "id": id_char,
        "display_name": nonempty,
        "role": string,  # key must exist; allow empty value if not meaningful
        "visual_stub": nonempty,
        "needs_concept_sheet": {"type": "boolean"},
    })

    item_loc = obj({
        "id": id_loc,
        "name": nonempty,
        "visual_stub": nonempty,
        "needs_concept_sheet": {"type": "boolean"},
    })

    item_prop = obj({
        "id": id_prop,
        "name": nonempty,
        "visual_stub": nonempty,
        "needs_concept_sheet": {"type": "boolean"},
    })

    lookbook_delta = obj({
        "characters_to_add": {"type": "array", "items": item_char},
        "locations_to_add":  {"type": "array", "items": item_loc},
        "props_to_add":      {"type": "array", "items": item_prop},
    })

    return obj({
        "pages": {"type": "array", "minItems": 1, "items": page},
        "lookbook_delta": lookbook_delta,
    })

SYSTEM_MSG = (
    "You are a top-tier comic writer & storyboard artist. "
    "Return ONLY a single JSON object that strictly conforms to the provided JSON Schema. "
    "No commentary, no markdown."
)

# -------- helpers: raw saving, token sizing, LLM call --------

def _extract_json_str(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    s = raw.find("{"); e = raw.rfind("}")
    if s != -1 and e != -1 and e > s:
        return raw[s:e+1]
    return raw

def _save_raw(job_id: str | None, payload: str, suffix: str):
    os.makedirs(RAW_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    jid = job_id or "nojob"
    h = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
    path = os.path.join(RAW_DIR, f"{jid}-{stamp}-{suffix}-{h}.txt")
    try:
        with open(path, "w") as f:
            f.write(payload)
    except Exception:
        pass
    return path

def _max_tokens_for(req: FullScriptRequest) -> int:
    # generous, but bounded
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
        temperature=0.25,
        max_tokens=max_tokens,
        response_format={"type": "json_schema","json_schema":{"name":"FullScriptPagesResponse","schema": schema,"strict": True}},
        messages=[{"role": "system", "content": SYSTEM_MSG},{"role": "user", "content": final_prompt}],
    )
    content = resp.choices[0].message.content or ""
    return content.strip()

# -------- recurrence thresholds & delta derivation --------

CHAR_PANEL_MIN = 3
CHAR_PAGE_MIN  = 2

PROP_PANEL_MIN = 3
PROP_PAGE_MIN  = 2

LOC_PAGE_MIN   = 2
LOC_PANEL_MIN  = 4
LOC_PANEL_PAGES_MIN = 2  # the 4 panels must span at least 2 pages (for robustness)

def _slug_to_title(_id: str, prefix: str) -> str:
    # char_cool_pilot -> "Cool Pilot"
    base = _id[len(prefix):].lstrip("_")
    words = [w for w in base.split("_") if w]
    return " ".join(w.capitalize() for w in words) or _id

def _collect_usage_counts(script: FullScriptPagesResponse):
    char_panels = defaultdict(int)
    char_pages  = defaultdict(set)

    prop_panels = defaultdict(int)
    prop_pages  = defaultdict(set)

    loc_pages   = defaultdict(int)   # page.location_id usage
    loc_panels  = defaultdict(int)
    loc_panel_pages = defaultdict(set)

    for page in script.pages:
        pnum = page.page_number
        if page.location_id:
            loc_pages[page.location_id] += 1

        for panel in page.panels:
            for cid in (panel.characters or []):
                char_panels[cid] += 1
                char_pages[cid].add(pnum)
            for pid in (panel.props or []):
                prop_panels[pid] += 1
                prop_pages[pid].add(pnum)
            if panel.location_id:
                lid = panel.location_id
                loc_panels[lid] += 1
                loc_panel_pages[lid].add(pnum)

    # convert page sets to counts
    char_pages_cnt = {k: len(v) for k, v in char_pages.items()}
    prop_pages_cnt = {k: len(v) for k, v in prop_pages.items()}
    loc_panel_pages_cnt = {k: len(v) for k, v in loc_panel_pages.items()}

    return {
        "char_panels": dict(char_panels),
        "char_pages": char_pages_cnt,
        "prop_panels": dict(prop_panels),
        "prop_pages": prop_pages_cnt,
        "loc_pages": dict(loc_pages),
        "loc_panels": dict(loc_panels),
        "loc_panel_pages": loc_panel_pages_cnt,
    }

def _derive_delta(script: FullScriptPagesResponse, known: Dict[str, List[Dict[str, str]]]) -> LookbookDelta:
    known_chars = {c["id"] for c in known.get("characters", [])}
    known_locs  = {l["id"] for l in known.get("locations",  [])}
    known_props = {p["id"] for p in known.get("props",      [])}

    counts = _collect_usage_counts(script)

    # Decide recurring characters/props
    rec_chars = []
    for cid, pcount in counts["char_panels"].items():
        if cid in known_chars:
            continue
        pages = counts["char_pages"].get(cid, 0)
        if pcount >= CHAR_PANEL_MIN or pages >= CHAR_PAGE_MIN:
            rec_chars.append(cid)

    rec_props = []
    for pid, pcount in counts["prop_panels"].items():
        if pid in known_props:
            continue
        pages = counts["prop_pages"].get(pid, 0)
        if pcount >= PROP_PANEL_MIN or pages >= PROP_PAGE_MIN:
            rec_props.append(pid)

    rec_locs = []
    for lid, page_uses in counts["loc_pages"].items():
        if lid in known_locs:
            continue
        # either used as page.location_id on >=2 pages
        # or appears in >=4 panels across >=2 pages
        pnl = counts["loc_panels"].get(lid, 0)
        pnl_pages = counts["loc_panel_pages"].get(lid, 0)
        if page_uses >= LOC_PAGE_MIN or (pnl >= LOC_PANEL_MIN and pnl_pages >= LOC_PANEL_PAGES_MIN):
            rec_locs.append(lid)

    # Build delta entries from IDs (names derived from IDs; visual_stub optional)
    chars_to_add = [
        CharacterToAdd(
            id=cid,
            display_name=_slug_to_title(cid, "char_"),
            role=None,
            visual_stub=None,
            needs_concept_sheet=True,
        )
        for cid in rec_chars
    ]
    locs_to_add = [
        LocationToAdd(
            id=lid,
            name=_slug_to_title(lid, "loc_"),
            visual_stub=None,
            needs_concept_sheet=True,
        )
        for lid in rec_locs
    ]
    props_to_add = [
        PropToAdd(
            id=pid,
            name=_slug_to_title(pid, "prop_"),
            visual_stub=None,
            needs_concept_sheet=True,
        )
        for pid in rec_props
    ]

    return LookbookDelta(
        characters_to_add=chars_to_add,
        locations_to_add=locs_to_add,
        props_to_add=props_to_add,
    )

# -------- public entry --------

async def generate_full_script(req: FullScriptRequest) -> FullScriptPagesResponse:
    lb = _load_lookbook(req.job_id)
    known = _index_lookbook(lb)

    prompt = build_full_script_prompt(req, known)
    max_tokens = _max_tokens_for(req)

    raw = await _call_llm(prompt, max_tokens=max_tokens, short_mode=False)
    _save_raw(getattr(req, "job_id", None), raw, "try1")
    cleaned = _extract_json_str(raw)

    try:
        script = FullScriptPagesResponse.model_validate_json(cleaned)
    except Exception:
        # short retry
        raw2 = await _call_llm(prompt, max_tokens=max_tokens, short_mode=True)
        _save_raw(getattr(req, "job_id", None), raw2, "try2")
        cleaned2 = _extract_json_str(raw2)
        script = FullScriptPagesResponse.model_validate_json(cleaned2)

    # Derive delta from actual usage (recurring-only) and overwrite any model-provided delta
    script.lookbook_delta = _derive_delta(script, known)
    return script
