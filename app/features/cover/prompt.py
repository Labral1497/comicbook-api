# app/features/cover/prompt.py
def build_cover_prompt(
    *,
    title: str,
    tagline: str,
    cover_art_description: str,
    user_theme: str,
    character_names: list[str] | None = None,
    location_names: list[str] | None = None,
    prop_names: list[str] | None = None,
) -> str:
    """
    Cover prompt that assumes multiple reference images are attached:
    - character portraits (likeness)
    - location wides (architecture / mood)
    - prop details (design)
    """
    character_names = character_names or []
    location_names = location_names or []
    prop_names = prop_names or []

    char_line = (
        f"- Characters (match facial likeness precisely): {', '.join(character_names)}.\n"
        if character_names else ""
    )
    loc_line = (
        f"- Locations (architectural cues & lighting mood): {', '.join(location_names)}.\n"
        if location_names else ""
    )
    prop_line = (
        f"- Props (design & palette): {', '.join(prop_names)}.\n"
        if prop_names else ""
    )

    only_chars_line = (
        f"- Include ONLY these characters: {', '.join(character_names)}. "
        "No other people or background figures.\n"
        if character_names else
        "- Avoid unintended people or background figures.\n"
    )

    return (
        "Create a vibrant, ultra-high-resolution comic book cover. The artwork should be a masterpiece "
        "of digital illustration, suitable for a professional digital print.\n\n"
        "**ATTACHED REFERENCE IMAGES (HIGHEST PRIORITY):**\n"
        "Use the attached reference images strictly as guides for likeness, design, palette, and style. "
        "Respect likeness for faces and keep the rendering style consistent across all elements.\n"
        f"{char_line}{loc_line}{prop_line}"
        "\n"
        "**PRIMARY SUBJECT & SCENE (MANDATORY):**\n"
        f"* **Scene Description:** Bring this scene to life: \"{cover_art_description}\" "
        f"using the title: \"{title}\" and the tagline: \"{tagline}\". "
        "Capture the action, expression, and mood.\n"
        f"{only_chars_line}"
        "- The main character must be the clear focal point with strong, readable silhouette.\n\n"
        "**ARTISTIC STYLE & EXECUTION (MANDATORY):**\n"
        f"* **Theme Influence:** The visual style must be \"{user_theme}\" theme.\n"
        "* **Color Palette:** Vibrant, saturated, eye-catching; adapt if the theme demands otherwise.\n"
        "* **Lighting:** Cinematic; coherent with the references.\n"
        "* **Rendering:** Clean linework, polished color, no unintended text.\n\n"
        "**COMMERCIAL DETAILS (MANDATORY):**\n"
        "* Add a humorous, flashy sticker/starburst with a funny slogan (no brands). Keep it legible and stylish.\n\n"
        "**CRITICAL RULES:**\n"
        "* No real-world logos/brands/trademarks.\n"
        "* Do not add accessories that obscure the main character’s face.\n"
    )
