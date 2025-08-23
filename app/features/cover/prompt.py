# app/features/cover/prompt.py
def build_cover_prompt(*, title: str, tagline: str, cover_art_description: str,
                       user_theme: str, image_ref_path: str | None) -> str:
    return (
        "Create a vibrant, ultra-high-resolution comic book cover. The artwork should be a masterpiece "
        "of digital illustration, suitable for a professional digital print.\n\n"
        f"**REFERENCE (HIGHEST PRIORITY):** The main character's face and unique features MUST closely match "
        f"the person in the reference image provided at **{image_ref_path}**. This is the most important rule.\n\n"
        "**PRIMARY SUBJECT & SCENE (MANDATORY):**\n\n"
        f"* **Scene Description:** The illustration must bring this scene to life: **\"{cover_art_description}\"** "
        f"using the title: **\"{title}\"** and the tagline **\"{tagline}\"**. Capture the action, expression, and mood "
        "described in the scene, ensuring the main character is central to this scene and rendered with the specified resemblance.\n\n"
        "**ARTISTIC STYLE & EXECUTION (MANDATORY):**\n\n"
        f"* **Theme Influence:** The visual style must be **\"{user_theme}\"** theme.\n"
        "* **Color Palette:** Use a vibrant, saturated, and eye-catching color palette that makes the cover pop. "
        "Unless the user_theme requires a different color palette.\n\n"
        "**COMMERCIAL DETAILS (MANDATORY):**\n\n"
        "* To make this look like an authentic comic book you would find in a store, you MUST include a humorous, fun, "
        "flashy sticker or starburst shape somewhere on the cover with a funny sentence/slogan.\n\n"
        "**CRITICAL RULE:**\n"
        "* **No real-world brands or text and avoid any trademark issues.**\n"
    )
