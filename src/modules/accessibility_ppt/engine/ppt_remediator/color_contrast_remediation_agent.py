"""
color_contrast_remediation_agent.py
===================================
ColorContrastRemediationAgent — raises failing TEXT contrast to WCAG 1.4.3 AA by
recolouring the offending runs, mutating context["presentation"] in place.

Rules handled (supported_rules)
    PPT-COLOR-001  Normal text < 4.5:1  -> recolour run to >= 4.5:1
    PPT-COLOR-002  Large text  < 3:1    -> recolour run to >= 3:1

NOT handled here (reported by the validator, not safely auto-fixable):
    PPT-COLOR-003  shape/non-text contrast (changing fills alters design)
    PPT-COLOR-004/005  SmartArt / chart colours (theme-driven, not extractable)
    PPT-COLOR-006  theme/auto text colours (unknown actual colour -> can't fix)

Approach (same WCAG maths as the PDF contrast_fixer):
  * A run is fixed only when its foreground is an explicit RGB colour AND a
    background is known (shape solid fill -> slide background -> assumed white,
    env ORION_PPT_ASSUME_BG). Theme/auto colours are counted, not guessed.
  * The colour is moved along a single blend axis toward black (on a light bg)
    or white (on a dark bg) — hue-preserving — using a binary search for the
    SMALLEST change that clears the threshold, so design shifts stay minimal.
"""
from __future__ import annotations

import os
from typing import Any

from pptx.dml.color import RGBColor

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

NORMAL_TARGET = 4.5
LARGE_TARGET = 3.0
LARGE_PT = 18.0
LARGE_BOLD_PT = 14.0
_HEADROOM = 1.05          # clear the threshold with a small margin


# --------------------------------------------------------------- WCAG maths --
def _srgb_channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb) -> float:
    r, g, b = rgb[:3]
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def _contrast(fg, bg) -> float:
    l1, l2 = _luminance(fg), _luminance(bg)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _hex_to_rgb01(value):
    if not isinstance(value, str):
        return None
    x = value.strip().lstrip("#").upper()
    if len(x) == 3:
        x = "".join(c * 2 for c in x)
    if len(x) != 6 or any(c not in "0123456789ABCDEF" for c in x):
        return None
    return (int(x[0:2], 16) / 255.0, int(x[2:4], 16) / 255.0, int(x[4:6], 16) / 255.0)


def _rgb01_to_rgbcolor(rgb) -> RGBColor:
    return RGBColor(*[max(0, min(255, int(round(c * 255)))) for c in rgb[:3]])


def _fix_color(fg, bg, target):
    """Smallest hue-preserving move of `fg` to clear `target` against `bg`.

    Blends toward black (light bg) or white (dark bg). Returns a new rgb01 tuple,
    or None if already passing or if neither extreme can reach the target
    (e.g. mid-grey background — not something to silently 'fix').
    """
    if _contrast(fg, bg) >= target:
        return None
    toward = (0.0, 0.0, 0.0) if _luminance(bg) > 0.5 else (1.0, 1.0, 1.0)
    if _contrast(toward, bg) < target:
        other = (1.0, 1.0, 1.0) if toward == (0.0, 0.0, 0.0) else (0.0, 0.0, 0.0)
        if _contrast(other, bg) < target:
            return None
        toward = other
    lo, hi = 0.0, 1.0                      # smallest t in [0,1] that passes
    for _ in range(30):
        mid = (lo + hi) / 2.0
        cand = tuple(fg[i] * (1 - mid) + toward[i] * mid for i in range(3))
        if _contrast(cand, bg) >= target * _HEADROOM:
            hi = mid
        else:
            lo = mid
    return tuple(round(fg[i] * (1 - hi) + toward[i] * hi, 4) for i in range(3))


class ColorContrastRemediationAgent(BasePPTRemediationAgent):
    """Recolour low-contrast text to meet WCAG AA."""

    agent_name = "PPT Color Contrast Remediation Agent"
    supported_rules = {"PPT-COLOR-001", "PPT-COLOR-002"}

    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-COLOR-001")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "text_contrast", error=str(exc))
        try:
            return self._fix_text_contrast(prs, context, rule_id)
        except Exception as exc:
            return self._result(rule_id, False, "text_contrast", error=str(exc))

    # ------------------------------------------------------------- internals
    @staticmethod
    def _color_hex(color) -> str | None:
        """'RRGGBB' only when the colour is an explicit RGB (not theme/auto)."""
        try:
            if color is None or color.type is None:
                return None
            return str(color.rgb)
        except Exception:
            return None

    @classmethod
    def _shape_fill_rgb(cls, shape):
        try:
            from pptx.enum.dml import MSO_FILL_TYPE
            fill = shape.fill
            if fill.type == MSO_FILL_TYPE.SOLID:
                return _hex_to_rgb01(cls._color_hex(fill.fore_color))
        except Exception:
            pass
        return None

    @classmethod
    def _slide_bg_rgb(cls, slide):
        try:
            return _hex_to_rgb01(cls._color_hex(slide.background.fill.fore_color))
        except Exception:
            return None

    @staticmethod
    def _is_large(run) -> bool:
        try:
            sz = run.font.size
            pt = sz.pt if sz is not None else None
        except Exception:
            pt = None
        if pt is None:
            return False
        if pt >= LARGE_PT:
            return True
        return bool(run.font.bold) and pt >= LARGE_BOLD_PT

    def _fix_text_contrast(self, prs, context, rule_id) -> RemediationResult:
        assume = _hex_to_rgb01(os.environ.get("ORION_PPT_ASSUME_BG", "FFFFFF"))
        changes: list[str] = []
        theme_skipped = 0
        unfixable = 0

        for si, shape in self._iter_shapes(prs):
            try:
                if not shape.has_text_frame:
                    continue
            except Exception:
                continue
            slide = prs.slides[si]
            bg = self._shape_fill_rgb(shape) or self._slide_bg_rgb(slide) or assume
            if bg is None:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    if not (run.text or "").strip():
                        continue
                    fg = _hex_to_rgb01(self._color_hex(run.font.color))
                    if fg is None:
                        theme_skipped += 1            # theme/auto -> COLOR-006
                        continue
                    target = LARGE_TARGET if self._is_large(run) else NORMAL_TARGET
                    if _contrast(fg, bg) >= target:
                        continue
                    new = _fix_color(fg, bg, target)
                    if new is None:
                        unfixable += 1
                        continue
                    try:
                        run.font.color.rgb = _rgb01_to_rgbcolor(new)
                        changes.append(
                            f"slide {si + 1}: {str(_rgb01_to_rgbcolor(fg))} -> "
                            f"{str(_rgb01_to_rgbcolor(new))} "
                            f"(bg {str(_rgb01_to_rgbcolor(bg))}, "
                            f"{_contrast(new, bg):.2f}:1)")
                    except Exception:
                        unfixable += 1

        notes = []
        if theme_skipped:
            notes.append(f"{theme_skipped} run(s) use theme/auto colours "
                         "(unknown value) — left for manual review (PPT-COLOR-006)")
        if unfixable:
            notes.append(f"{unfixable} run(s) could not reach the target "
                         "(e.g. mid-grey background)")
        return self._result(rule_id, True, "recolor_low_contrast_text",
                            changes_made=changes,
                            error="; ".join(notes) if notes else None)
