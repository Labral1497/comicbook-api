# app/features/lookbook_ref_assets/prompt.py
from typing import Dict

def _style_line(style_theme: str | None) -> str:
    return f" Match the overall visual style: {style_theme}." if style_theme else ""

def _canon_str(visual_canon: Dict[str, str] | Dict) -> str:
    if not visual_canon:
        return ""
    # Compact "k:v" lines; avoid dumping huge JSON blobs
    parts = []
    for k, v in visual_canon.items():
        if isinstance(v, (list, tuple)):
            v = ", ".join(map(str, v))
        parts.append(f"{k}: {v}")
    return " | ".join(parts)

# ---------------- Characters ----------------

def character_portrait_prompt(display_name: str, visual_canon: Dict, style_theme: str | None) -> str:
    canon = _canon_str(visual_canon)
    return (
        f"Character concept PORTRAIT of {display_name}. "
        "Single subject only. Chest-up framing on a neutral background with studio lighting. "
        "Face fully visible (no occlusion), natural expression, clean silhouette. "
        "Consistent facial features and hairstyle for production continuity. "
        f"{canon}{_style_line(style_theme)} "
        "If a reference image is provided for this character, strictly preserve the person’s likeness and proportions, "
        "and keep palette/lighting consistent with that reference. "
        "Do NOT add other people, hands, or text. No labels or watermarks."
    ).strip()

def character_turnaround_prompt(display_name: str, visual_canon: Dict, style_theme: str | None) -> str:
    canon = _canon_str(visual_canon)
    return (
        f"Full-body character TURNAROUND sheet of {display_name}: front, side, and back views on a single canvas. "
        "Neutral background, flat even lighting, consistent proportions and costume details. "
        f"{canon}{_style_line(style_theme)} "
        "If a reference image is provided for this character, keep likeness (face/head/hairstyle) and overall style consistent. "
        "No additional characters, no props in hand, no text or labels."
    ).strip()

# ---------------- Locations ----------------

def location_wide_prompt(name: str, visual_canon: Dict, style_theme: str | None) -> str:
    canon = _canon_str(visual_canon)
    return (
        f"Location concept art — WIDE establishing shot of {name}. "
        "Environment-only rendering that emphasizes architecture, scale, lighting, and mood. "
        f"{canon}{_style_line(style_theme)} "
        "Do NOT include people, silhouettes, crowds, characters, or figures of any kind. "
        "Avoid vehicles/animals unless essential to the identity of the place. "
        "Clean presentation; no signage text, no labels, no watermarks."
    ).strip()

# ---------------- Props ----------------

def prop_detail_prompt(name: str, visual_canon: Dict, style_theme: str | None) -> str:
    canon = _canon_str(visual_canon)
    return (
        f"Prop concept image: {name}. "
        "Centered product-style render on a neutral background with soft studio lighting. "
        "Orthographic/three-quarter clarity; show silhouette and key material details. "
        f"{canon}{_style_line(style_theme)} "
        "If a reference image is provided for this prop, keep materials, palette, and finish consistent. "
        "Do NOT include hands, models, or people. No text, logos, or labels unless specified."
    ).strip()
