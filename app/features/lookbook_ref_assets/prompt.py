# app/features/lookbook_ref_assets/prompt.py
from typing import Dict

def _style_line(style_theme: str | None) -> str:
    return f" Match the overall visual style: {style_theme}." if style_theme else ""

def _canon_str(visual_canon: Dict[str, str] | Dict) -> str:
    if not visual_canon:
        return ""
    parts = []
    for k, v in visual_canon.items():
        if isinstance(v, (list, tuple)):
            v = ", ".join(map(str, v))
        parts.append(f"{k}: {v}")
    return " | ".join(parts)

# ---- Characters ----

def character_portrait_prompt(
    display_name: str,
    visual_canon: Dict,
    style_theme: str | None,
    gender: str | None = None,
) -> str:
    canon = _canon_str(visual_canon)
    gender_line = f" Gender presentation: {gender}." if gender else ""
    return (
        f"Character concept portrait of {display_name}. "
        "Neutral background, studio lighting. Chest-up framing. "
        "Face fully visible (no occlusion). Natural expression. "
        f"Consistent features for comic production.{gender_line} {canon}"
        f"{_style_line(style_theme)} "
        "If a likeness reference is attached, match facial structure and key features. "
        "Clean linework and color; no text or labels."
    ).strip()

def character_turnaround_prompt(
    display_name: str,
    visual_canon: Dict,
    style_theme: str | None,
    gender: str | None = None,
) -> str:
    canon = _canon_str(visual_canon)
    gender_line = f" Gender presentation: {gender}." if gender else ""
    return (
        f"Full-body character turnaround sheet of {display_name}: front, side, and back views on a single sheet. "
        "Neutral background, flat even lighting. Consistent proportions for comic production."
        f"{gender_line} {canon}"
        f"{_style_line(style_theme)} "
        "Use the supplied portrait (if available) as the primary likeness reference. "
        "Maintain identical face, hairstyle, and body type as the portrait. "
        "Clean linework and color; no text or labels."
    ).strip()

# ---- Locations ----

def location_wide_prompt(name: str, visual_canon: Dict, style_theme: str | None) -> str:
    canon = _canon_str(visual_canon)
    return (
        f"Location concept art: wide establishing shot of {name}. "
        f"Emphasize canonical features. {canon}"
        f"{_style_line(style_theme)} "
        "No people or characters in frame. "
        "Match the rendering style and palette of other assets. "
        "Clean presentation; no signage text; no labels."
    ).strip()

# ---- Props ----

def prop_detail_prompt(name: str, visual_canon: Dict, style_theme: str | None) -> str:
    canon = _canon_str(visual_canon)
    return (
        f"Prop concept image: {name}. Product-photo style on neutral background. "
        "Orthographic feel; show silhouette and key details. "
        f"{canon}{_style_line(style_theme)} "
        "Match rendering style and palette of other assets. "
        "No logos unless specified; no text or labels."
    ).strip()
