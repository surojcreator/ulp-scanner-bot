"""Self-verification test suite adhering to skill-tg verification requirements."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.keyboards as k
from src.bot import render
from src.emoji_map import GLYPH_TO_ID, premiumize


def test_render_formatting_rule():
    """Requirement 1 from skill-tg:
    Formatting — call real render() on a template containing <b> plus an interpolated
    value containing <. The output must contain a real <b> tag (NOT &lt;b&gt;) and the value's
    < must become &lt;.
    """
    template = "⚡ <b>{title}</b>\n\nValue is: <code>{val}</code>"
    out = render(template, title="Section <1>", val="a < b & c > d")

    # The template's <b> must NOT be escaped
    assert "<b>" in out, f"Template tag <b> was erroneously escaped: {out}"
    assert "</b>" in out, f"Template tag </b> was erroneously escaped: {out}"
    assert "&lt;b&gt;" not in out, f"Found &lt;b&gt; in output: {out}"

    # The interpolated values MUST be safely escaped
    assert "Section &lt;1&gt;" in out, f"Interpolated value '<1>' was not escaped: {out}"
    assert "a &lt; b &amp; c &gt; d" in out, f"Interpolated value was not escaped: {out}"
    print("Formatting verification passed!")


def test_design_and_ux_keyboards():
    """Requirement 2 from skill-tg:
    Design — run every screen through the checklist in reference/design-and-ux.md:
    - At most one `success` button per screen (zero on pure list screens).
    - Navigation (Back/Home) in the last row.
    """
    # 1. Queue Keyboard with items
    kb_with_items = k.queue_keyboard(5)
    success_count = 0
    for row in kb_with_items.inline_keyboard:
        for btn in row:
            if getattr(btn, "style", None) == "success":
                success_count += 1
    assert success_count <= 1, f"Expected <= 1 'success' button, found {success_count}"

    # 2. Queue List Keyboard (Pure list / menu screen -> 0 'success' buttons!)
    kb_list = k.queue_list_keyboard()
    success_count_list = 0
    for row in kb_list.inline_keyboard:
        for btn in row:
            if getattr(btn, "style", None) == "success":
                success_count_list += 1
    assert success_count_list == 0, f"Pure menu screen should have 0 'success' buttons, found {success_count_list}"

    # Navigation must be in the last row
    last_row_texts = [btn.text for btn in kb_list.inline_keyboard[-1]]
    assert any("Back" in t or "Home" in t or "⬅️" in t for t in last_row_texts), (
        f"Navigation missing from last row of queue list keyboard: {last_row_texts}"
    )

    # 3. Report Keyboard
    kb_report = k.report_keyboard(has_clean=True, has_errors=True)
    success_count_report = 0
    for row in kb_report.inline_keyboard:
        for btn in row:
            if getattr(btn, "style", None) == "success":
                success_count_report += 1
    assert success_count_report <= 1, f"Report screen has > 1 'success' button: {success_count_report}"

    last_row_report = [btn.text for btn in kb_report.inline_keyboard[-1]]
    assert any("Home" in t or "Back" in t for t in last_row_report), (
        f"Navigation missing from last row of report keyboard: {last_row_report}"
    )

    print("Design and UX keyboard verification passed!")


def test_premium_emoji_behavior():
    """Requirement 4:
    Premium emoji stays PREMIUM_EMOJI=off + empty GLYPH_TO_ID unless holding real IDs.
    When off, passes plain unicode. When on with mapped ID, wraps with <tg-emoji>.
    """
    # Default behavior: disabled
    text = "⚡ Cleaned 100 ⭐ files"
    out_disabled = premiumize(text, enabled=False)
    assert out_disabled == text
    assert "<tg-emoji" not in out_disabled

    # If enabled with a mock ID
    original_dict = dict(GLYPH_TO_ID)
    try:
        GLYPH_TO_ID["⭐"] = 5848259999763011021
        out_enabled = premiumize(text, enabled=True)
        assert '<tg-emoji emoji-id="5848259999763011021">⭐</tg-emoji>' in out_enabled
    finally:
        GLYPH_TO_ID.clear()
        GLYPH_TO_ID.update(original_dict)

    print("Premium emoji verification passed!")


if __name__ == "__main__":
    test_render_formatting_rule()
    test_design_and_ux_keyboards()
    test_premium_emoji_behavior()
    print("ALL skill-tg compliance tests PASSED!")
