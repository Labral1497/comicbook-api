from typing import Dict, List, Tuple
from .schemas import FullScriptRequest


def _fmt_label(it: Dict[str, str]) -> str:
    """
    Render a human label and append gender if available.
    """
    label = it.get("display_name") or it.get("name") or it["id"]
    g = (it.get("gender") or "").strip()
    return f"\"{label}\" (gender: {g})" if g else f"\"{label}\""


def _format_known(title: str, items: List[Dict[str, str]]) -> str:
    """
    Render the known entities block for the prompt (IDs + labels).
    """
    if not items:
        return f"- {title}: (none)\n"
    lines = [f"- {title}:"]
    for it in items:
        lines.append(f"  • {it['id']} → {_fmt_label(it)}")
    return "\n".join(lines) + "\n"


def _targets_for_pages(pages: int) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """
    NEW minima for stories of length `pages` (counts of NEW entities to introduce).
    Return: (char_min,max), (loc_min,max), (prop_min,max)
    """
    if pages < 6:
        return (0, 1), (0, 1), (0, 2)
    if pages <= 15:
        return (2, 3), (2, 3), (1, 3)
    if pages <= 20:
        return (2, 3), (2, 3), (2, 3)
    return (2, 3), (2, 3), (2, 5)


def build_full_script_prompt(
    req: FullScriptRequest,
    known: Dict[str, List[Dict[str, str]]],
    need_chars: int,
    need_locs: int,
    need_props: int,
) -> str:
    traits = (
        ", ".join([f"{q} - {a}" for q, a in req.user_answers_list.items()])
        if req.user_answers_list
        else ""
    )

    known_block = (
        "KNOWN ENTITIES (reuse these IDs whenever applicable):\n"
        + _format_known("Characters", known.get("characters", []))
        + _format_known("Locations",  known.get("locations",  []))
        + _format_known("Props",      known.get("props",      []))
    )

    return f"""
Excellent. This is the final step in the scriptwriting process, used after payment. Expand the approved story summary into a full, multi-page comic script.

ROLE:
You are an elite comic writer and storyboard artist. Output ONLY a single JSON object that conforms to the JSON Schema enforced by the system (you will be validated strictly).

CONTEXT INPUTS:
- Story Summary: "{req.story_summary}"
- Comic Title: "{req.title}"
- Comic Tagline: "{req.tagline}"
- Main Character Name: "{req.user_name}"
- Main Character Gender: "{req.user_gender}"
- Total Page Count: {req.page_count}
- Core Theme: "{req.user_theme}"
- Comedic Traits (for jokes): "{traits}"

{known_block}
ID RULES (IMPORTANT):
- IDs are stable strings:
  • Character IDs start with "char_" (e.g., char_main, char_mike)
  • Location IDs start with "loc_" (e.g., loc_burj_khalifa_rooftop)
  • Prop IDs start with "prop_" (e.g., prop_wingsuit)
- ALWAYS reuse KNOWN ENTITIES when they fit; create NEW entities ONLY to meet the exact counts below.
- The main character MUST be "char_main". Use the human name in dialogue, but keep the ID "char_main" in lists.
- Background extras that are not story-relevant should NOT get IDs (mention them only in art_description).

GENDER CONSISTENCY (MANDATORY):
- Respect each known character’s gender listed above.
- For any NEW character, start lookbook_delta.characters_to_add[*].visual_stub with "gender: ...".

NEW-ENTITY INTRODUCTION TARGETS (HARD, EXACT):
- You MUST add exactly:
  • New Characters: {need_chars}
  • New Locations:  {need_locs}
  • New Props:      {need_props}
(If any of these are 0, DO NOT add any new items of that type.)

USAGE-FIRST & DELTA DERIVATION (HARD RULE):
- First, plan where each NEW entity will appear.
- Then write the pages.
- Finally, set lookbook_delta = (all IDs you actually used in pages) minus (KNOWN ENTITIES).
- DO NOT include any ID in lookbook_delta unless it is actually used in pages per the usage counts below.

USAGE COUNTS (MANDATORY):
- NEW Character IDs → appear in at least 2 distinct PANELS (panel.characters).
- NEW Location IDs  → used on at least 1 PAGE as page.location_id (preferred), OR appear in at least 2 PANELS via panel.location_id.
- NEW Prop IDs      → appear in at least 2 distinct PANELS (panel.props).
- If any NEW entity fails these counts, revise the pages before you output.

ACT PLACEMENT (RECOMMENDED):
- Introduce at least one NEW entity (character OR location OR prop) by page 4;
  another NEW entity by pages 8–10; and pay it off by the final two pages.

SCRIPT SHAPE & CONSTRAINTS:
- Pages: exactly {req.page_count}. Panels per page must vary and stay within [{req.min_panels_per_page}, {req.max_panels_per_page}].
- Provide detailed art_description (camera angle, actions, expressions, background, lighting).
- Do NOT obscure the main character’s face with accessories.
- If a field is not applicable, use "" for location_id and [] for characters/props.

FINAL SELF-CHECK (MANDATORY):
- Every ID in lookbook_delta appears in pages with the required usage counts.
- No ID used in pages/panels is missing from KNOWN ENTITIES or lookbook_delta.
- Genders are consistent.

OUTPUT:
- Return ONLY a single JSON object complying with the enforced JSON Schema (arrays present even if empty).
- No commentary, no markdown, no extra keys.
""".strip()
