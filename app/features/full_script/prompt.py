from .schemas import FullScriptRequest
from typing import Dict, List, Tuple

def _fmt_label(it: Dict[str, str]) -> str:
    label = it.get("display_name") or it.get("name") or it["id"]
    g = (it.get("gender") or "").strip()
    return f"\"{label}\" (gender: {g})" if g else f"\"{label}\""

def _format_known(title: str, items: List[Dict[str, str]]) -> str:
    if not items:
        return f"- {title}: (none)\n"
    lines = [f"- {title}:"]
    for it in items:
        lines.append(f"  • {it['id']} → {_fmt_label(it)}")
    return "\n".join(lines) + "\n"

def build_full_script_prompt(
    req: FullScriptRequest,
    known: Dict[str, List[Dict[str, str]]],
) -> str:
    traits = ", ".join([f"{q} - {a}" for q, a in (req.user_answers_list or {}).items()]) if getattr(req, "user_answers_list", None) else ""
    known_block = (
        "KNOWN ENTITIES (primary cast & spaces — reuse these IDs when they fit):\n"
        + _format_known("Characters", known.get("characters", []))
        + _format_known("Locations",  known.get("locations",  []))
        + _format_known("Props",      known.get("props",      []))
    )

    return f"""
Expand the approved story summary into a full, multi-page comic script.

ROLE:
You are an elite comic writer + storyboard artist. Output ONLY a single JSON object that conforms to the JSON Schema (strictly validated).

CONTEXT INPUTS:
- Story Summary: "{req.story_summary}"
- Comic Title: "{req.title}"
- Comic Tagline: "{req.tagline}"
- Main Character Name: "{req.user_name}"
- Main Character Gender: "{req.user_gender}"
- Total Page Count: {req.page_count}
- Core Theme: "{req.user_theme}"
- Comedic Traits: "{traits}"

{known_block}

ID & CONSISTENCY RULES:
- Stable ID prefixes:
  • Characters:  char_*   (e.g., char_main)
  • Locations:   loc_*    (e.g., loc_burj_khalifa_rooftop)
  • Props:       prop_*   (e.g., prop_wingsuit)
- Favor and reuse KNOWN IDs above. Introduce NEW IDs only if the story benefits.
- If you introduce a NEW recurring entity, keep its ID consistent across pages/panels.
- Background one-off extras and throwaway gags should NOT get IDs; just describe them in art_description.

VARIETY & RECURRING IDS (NATURAL, NO QUOTAS):
- If a non-core character speaks, is named, or appears on ≥2 pages (or ≥3 panels), give them a char_* ID and tag them in panel.characters when on-camera.
- Avoid leaving page.location_id empty; when the scene continues across pages, reuse the prior page’s location_id. For broad aerial runs, define a canonical setting (e.g., loc_sky_over_dubai) and reuse it.
- If a prop is story-relevant and visible across ≥2 pages (or ≥3 panels), assign a prop_* ID and include it in panel.props wherever visible.
- Only include recurring entities in lookbook_delta. One-offs remain anonymous in art_description.

GENDER NOTE (only if you add new characters and you decide to include them in lookbook_delta):
- Begin lookbook_delta.characters_to_add[*].visual_stub with "gender: ...".
- The server derives lookbook_delta automatically; you MAY leave lookbook_delta arrays empty.

OUTPUT SHAPE (IMPORTANT):
- pages: exactly {req.page_count}; panels per page within [{req.min_panels_per_page}, {req.max_panels_per_page}] and varied.
- Provide cinematic art_description (camera, actions, expressions, background, lighting).
- Keep the main character’s face readable (no full obstruction).
- Use "" for missing location_id and [] for empty characters/props arrays.
- You MAY leave lookbook_delta empty — the system will compute it from recurring usage.

NATURAL WRITING:
- Prioritize natural story flow and visual clarity.
- Reuse the core cast and spaces above; organically introduce new ones only when they add value (e.g., new venue, helper, vehicle).
- Recurring entities should reappear logically across pages; cameos stay un-ID’d.

FINAL CHECKLIST BEFORE YOU OUTPUT:
- JSON-only, no commentary/markdown.
- Every ID used in pages is consistently spelled.
- If you chose to include lookbook_delta, include only recurring entities (not one-offs).

RETURN:
- A single JSON object that conforms to the provided JSON Schema (arrays present even if empty).
""".strip()
