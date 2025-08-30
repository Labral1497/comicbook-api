import json, re, unicodedata
from pydantic import ValidationError
from app.lib.openai_client import client
from .schemas import CoverScriptRequest, CoverScriptResponse
from .prompt import build_cover_script_prompt

SYSTEM = (
    "You are a witty, concise comic writer and storyboard artist. "
    "Return STRICT JSON only — exactly one JSON object with the keys "
    "'title', 'tagline', 'cover_art_description', 'story_summary', "
    "'cover_entities', and 'seed_request_template'. "
    "Inside cover_entities, include arrays for 'characters', 'locations', 'props', a 'hints' map, "
    "and an optional 'notes' map (id → short description). "
    "No extra text, no comments, no markdown."
)

def _slugify(label: str) -> str:
    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "unnamed"

def _ensure_char_main(data: dict, main_name: str) -> dict:
    ce = data.setdefault("cover_entities", {})
    ids = ce.setdefault("characters", [])
    if "char_main" not in ids:
        ids.insert(0, "char_main")
    hints = ce.setdefault("hints", {})
    hints.setdefault("char_main", main_name)
    ce.setdefault("notes", {})
    srt = data.setdefault("seed_request_template", {})
    initial = srt.setdefault("initial_ids", {})
    chars = initial.setdefault("characters", [])
    if "char_main" not in chars:
        chars.insert(0, "char_main")
    srt_hints = srt.setdefault("hints", {})
    srt_hints.setdefault("char_main", main_name)
    return data

def _normalize_entity_ids(data: dict) -> dict:
    """
    If the model emitted generic IDs (e.g., char_support_1, loc_rooftop),
    rewrite them to slugs derived from their display names in hints.
    Keeps arrays + hints + notes + seed_request_template in sync.
    """
    ce = data.get("cover_entities", {})
    hints = ce.get("hints", {})
    notes = ce.get("notes", {})

    def remap(kind_key: str, prefix: str):
        ids = ce.get(kind_key, []) or []
        new_ids = []
        changed = []
        for _id in ids:
            if kind_key == "characters" and _id == "char_main":
                new_ids.append(_id)
                continue
            display = hints.get(_id)
            if display:
                target = f"{prefix}{_slugify(display)}"
                if target != _id:
                    # migrate hint + note to new key
                    hints[target] = hints.pop(_id)
                    if _id in notes:
                        notes[target] = notes.pop(_id)
                    changed.append((_id, target))
                    new_ids.append(target)
                else:
                    new_ids.append(_id)
            else:
                new_ids.append(_id)
        ce[kind_key] = new_ids

        # keep seed_request_template aligned
        srt = data.get("seed_request_template", {})
        init = srt.get("initial_ids", {})
        arr = init.get(kind_key, []) or []
        for old, new in changed:
            arr = [new if x == old else x for x in arr]
        init[kind_key] = arr

        # also mirror hints map
        srt_h = srt.get("hints", {})
        for old, new in changed:
            if old in srt_h:
                srt_h[new] = srt_h.pop(old)

    remap("characters", "char_")
    remap("locations", "loc_")
    remap("props", "prop_")
    return data

async def generate_cover_script(req: CoverScriptRequest) -> CoverScriptResponse:
    traits = ", ".join(f"{q} - {a}" for q, a in req.user_answers_list.items()) if req.user_answers_list else ""
    prompt = build_cover_script_prompt(
        title=req.title, synopsis=req.synopsis, name=req.name,
        gender=req.gender, page_count=req.page_count, theme=req.theme, traits=traits
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.7,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\nRaw: {raw}") from e

    data = _ensure_char_main(data, req.name)
    data = _normalize_entity_ids(data)

    try:
        return CoverScriptResponse(**data)
    except ValidationError as e:
        raise ValueError(f"Model JSON failed validation: {e}\nData: {data}") from e
