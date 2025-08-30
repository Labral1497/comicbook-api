# app/features/full_script/prompt.py
from .schemas import FullScriptRequest

def build_full_script_prompt(req: FullScriptRequest) -> str:
    traits = ", ".join([f"{q} - {a}" for q, a in req.user_answers_list.items()]) if req.user_answers_list else ""
    return f"""
Excellent. This is the final step in the scriptwriting process, used after payment. Expand the approved story summary into a full, multi-page comic script.

ROLE:
You are an elite comic writer and storyboard artist. Output ONLY a single JSON object that conforms to the schema below.

CONTEXT INPUTS:
- Story Summary: "{req.story_summary}"
- Comic Title: "{req.title}"
- Comic Tagline: "{req.tagline}"
- Main Character Name: "{req.user_name}"
- Main Character Gender: "{req.user_gender}"
- Total Page Count: {req.page_count}
- Core Theme: "{req.user_theme}"
- Comedic Traits (for jokes): "{traits}"

PRIMARY DIRECTIVE:
Expand the Story Summary faithfully into {req.page_count} pages. Vary panel counts per page between {req.min_panels_per_page} and {req.max_panels_per_page}. Provide extremely detailed art_descriptions (camera angle, actions, expressions, background elements, lighting). Do NOT obscure the main character’s face with accessories.

ENTITY & LOOKBOOK RULES:
- Every character/prop/location used MUST reference a stable ID string.
- Use IDs in two places: (1) page-level lists (characters/props/location_id), and (2) per-panel overrides where needed.
- The main character MUST use id "char_main". Use the provided name "{req.user_name}" in dialogue, but keep the ID "char_main".
- If you need a new entity that is not already known, add a stub to lookbook_delta.*_to_add with:
  - a unique "id" (e.g., "char_yaron", "loc_studio", "prop_laptop"),
  - a human name ("display_name" or "name"),
  - a brief "visual_stub" description,
  - "needs_concept_sheet": true.
- Do NOT invent unnamed entities; everything must be referenced by ID or declared in lookbook_delta.

STRICT JSON SCHEMA (your entire output MUST be a single JSON object with exactly these fields):
{{
  "pages": [
    {{
      "page_number": 1,
      "location_id": "loc_id_or_null",
      "characters": ["char_main", "char_support_1"],
      "props": ["prop_laptop"],
      "panels": [
        {{
          "panel_number": 1,
          "art_description": "EXTREMELY detailed visual description incl. camera angle, action, expression, background, and lighting.",
          "dialogue": "Character Name: 'The dialogue for this panel.' or '' if none.",
          "narration": "Narration text or '' if none.",
          "sfx": "Onomatopoeia or '' if none.",
          "characters": ["char_main"],
          "props": ["prop_laptop"],
          "location_id": "loc_id_or_null"
        }}
      ]
    }}
  ],
  "lookbook_delta": {{
    "characters_to_add": [
      {{
        "id": "char_support_1",
        "display_name": "Yaron",
        "role": "co-founder",
        "visual_stub": "tall, shaved head, warm smile, casual blazer",
        "needs_concept_sheet": true
      }}
    ],
    "locations_to_add": [
      {{
        "id": "loc_studio",
        "name": "Indie studio",
        "visual_stub": "brick wall, neon sign, dual monitors, warm practical lights",
        "needs_concept_sheet": true
      }}
    ],
    "props_to_add": [
      {{
        "id": "prop_laptop",
        "name": "Laptop",
        "visual_stub": "no brand logo, two small stickers on lid",
        "needs_concept_sheet": true
      }}
    ]
  }}
}}

MANDATES:
- Pacing: clear beginning → rise → comedic climax → satisfying, funny resolution on the final page.
- Panels per page: choose randomly in [{req.min_panels_per_page}, {req.max_panels_per_page}] and vary across pages unless narratively justified.
- No extra commentary or markdown. Output ONLY the JSON object.
""".strip()
