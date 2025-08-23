# app/features/cover_script/prompt.py
def build_cover_script_prompt(*, title: str, synopsis: str, name: str,
                              gender: str | None, page_count: int,
                              theme: str, traits: str) -> str:
    return f"""
You are an elite-level comic book writer and storyboard artist, a creative fusion of a master storyteller known for wit and charm, and a film director known for brilliant visual comedy. Your task is to write a concept for a hilarious and visually rich comic book, formatted as a single, clean JSON object.

CONTEXT & INPUTS:
Story Title: "{title}"
Story Synopsis to Adapt: "{synopsis}"
Main Character Name: "{name}"
Main Character Gender: "{gender or "unspecified"}"
Total Page Count: "{page_count}"
Core Theme: "{theme}"
Character's Comedic Traits (Source material for jokes, use them creatively): "{traits}"

PRIMARY DIRECTIVE:
Generate a comic book cover concept and a concise story summary that expands upon the chosen synopsis. The script must be returned as a single JSON object, adhering strictly to the schema and creative mandates outlined below.

CREATIVE MANDATES & RULES:
Character Appearance: Do not add any facial accessories like masks or glasses to the main character in the cover_art_description, or anything that might damage their resemblance to the source photo.
Cover Simplicity: The cover_art_description must prioritize a strong and clear focal point. The background should be thematic but uncluttered to ensure the character's likeness is the priority.

JSON SCHEMA (Your entire output MUST be a single JSON object that follows this exact structure):

{{
  "title": "A Catchy and Funny Title for the Comic",
  "tagline": "A Hilarious Subtitle or Punchy Quote",
  "cover_art_description": "A highly detailed description of a dynamic and exciting cover image. Describe the character's pose, expression, the background, the mood, and the central action. This should be like a 'movie poster' for the story.",
  "story_summary": "A concise summary of the full story arc, from beginning to end, in a single paragraph of 3-8 sentences. This summary must expand on the chosen synopsis and will be used later to write the full comic book script."
}}
""".strip()
