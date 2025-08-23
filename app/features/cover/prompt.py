# app/features/cover/prompt.py
def build_cover_prompt(*, title: str, tagline: str, cover_art_description: str,
                       user_theme: str, image_ref_path: str | None) -> str:
    return (
        "Create a vibrant, ultra-high-resolution comic book cover. The artwork should be a masterpiece "
        "of digital illustration, suitable for a professional digital print.\n\n"
        f"**REFERENCE (HIGHEST PRIORITY):** The main character's face and unique features MUST closely match "
        f"the person in the reference image provided at **{image_ref_path}**.\n\n"
        "**PRIMARY SUBJECT & SCENE (MANDATORY):**\n"
        f"* **Scene Description:** **[\"title\": \"{title}\", \"tagline\": \"{tagline}\", "
        f"\"cover_art_description\": \"{cover_art_description}\"]**\n\n"
        "**ARTISTIC STYLE & EXECUTION (MANDATORY):**\n"
        "* Core Style: Professional digital comic book art. Cinematic lighting and shadows.\n"
        f"* Theme Influence: The visual style should be influenced by **\"{user_theme}\"**.\n"
        "* Color Palette: Vibrant, saturated, eye-catching.\n"
        "* Quality: Hyper-detailed, sharp focus (4K spirit).\n\n"
        "**COMMERCIAL DETAILS (MANDATORY):**\n"
        "* Include a realistic barcode in a corner and a humorous sticker/burst with abstract symbols (no legible text or real brands).\n"
    )
