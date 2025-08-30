def build_cover_script_prompt(*, title: str, synopsis: str, name: str,
                              gender: str | None, page_count: int,
                              theme: str, traits: str) -> str:
  return f"""
You are an elite comic writer + storyboard artist. Output ONLY one JSON object matching the schema below.

CONTEXT INPUTS:
- Title: "{title}"
- Synopsis: "{synopsis}"
- Main Character Name: "{name}"
- Main Character Gender: "{gender or "unspecified"}"
- Total Page Count: {page_count}
- Visual Theme / Style: "{theme}"
- Q&A (free-form details you may mine for names/roles/locations/props/quirks):
  {traits or "(none)"}

GOALS:
1) Propose an exciting cover concept and a concise story summary.
2) Extract the initial Lookbook entities that are visible or implied by the **cover_art_description** you propose and by the Q&A/synopsis.

ENTITY & ID RULES (MANDATORY):
- Use STABLE IDS built from human-readable names you actually mention:
  - Characters: "char_<slug>" (the main character MUST be "char_main")
  - Locations:  "loc_<slug>"
  - Props:      "prop_<slug>"
- Slugging: lowercase; words joined by underscores; ASCII; strip punctuation; no spaces; e.g.:
  "Mike" -> "char_mike"
  "Burj Khalifa Rooftop" -> "loc_burj_khalifa_rooftop"
  "Wingsuit" -> "prop_wingsuit"
- **Do NOT** output generic placeholders like "char_support_1", "loc_rooftop", "prop_laptop" unless those exact generic things are literally what your description uses.
- The "hints" map must give display names for every ID (e.g., {{"char_main":"{name}"}}). Names should match your description.
- Include an optional "notes" map with 1–2 sentence visual descriptors per ID (derived from Q&A/synopsis/description).
- Keep seeding modest: protagonist always, plus at most 2 more characters, 1 location, up to 2 props.

STRICT JSON SHAPE (exact keys; fill with your derived values):
{{
  "title": "...",
  "tagline": "...",
  "cover_art_description": "...",
  "story_summary": "...",
  "cover_entities": {{
    "characters": ["char_main", "<char_slug_if_any>"],
    "locations": ["<loc_slug_if_any>"],
    "props": ["<prop_slug_if_any>"],
    "hints": {{
      "char_main": "{name}"
      // add display names for every other id you emit
    }},
    "notes": {{
      // optional: id -> 1–2 sentences on look/role
    }}
  }},
  "seed_request_template": {{
    "initial_ids": {{
      "characters": ["char_main", "<same_char_slug_if_any>"],
      "locations": ["<same_loc_slug_if_any>"],
      "props": ["<same_prop_slug_if_any>"]
    }},
    "hints": {{
      // EXACTLY the same mapping as cover_entities.hints
    }}
  }}
}}
Return only that JSON object. No explanations.
""".strip()
