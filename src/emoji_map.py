"""Premium (custom) emoji mapping and rendering (Bot API 9.4).
Follows the skill-tg specification.
"""

from __future__ import annotations

from typing import Dict

# Real document_ids for custom emojis (empty by default; populated when holding real IDs)
GLYPH_TO_ID: Dict[str, int] = {
    # e.g., "⚡": 5447644880572643929,
}


def premiumize(text: str, enabled: bool = False) -> str:
    """Wrap known glyphs in <tg-emoji>.
    Input is already-safe HTML — do NOT html.escape here.
    """
    if not enabled or not GLYPH_TO_ID:
        return text
    for glyph, eid in GLYPH_TO_ID.items():
        text = text.replace(glyph, f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>')
    return text
