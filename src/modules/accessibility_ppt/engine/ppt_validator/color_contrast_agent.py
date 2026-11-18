"""
color_contrast_agent.py
=======================
ColorContrastAgent — WCAG 1.4.3 (AA) colour contrast for slides.

The luminance / contrast maths is the SAME formula the PDF engine uses
(contrast_fixer._srgb_channel / _luminance / _contrast), reimplemented here so
the PPT validator stays dependency-light (no pikepdf pull) while never
disagreeing with the PDF side on the numbers.

Thresholds (WCAG 2.1 AA)
    normal text : 4.5:1
    large text  : 3:1        (>= 18 pt, or >= 14 pt bold)

Checks (supported_checks)
    PPT-COLOR-001  Text contrast        (normal text below 4.5:1)
    PPT-COLOR-002  Large text contrast  (large text below 3:1)
    PPT-COLOR-003  Shape contrast       (solid shape fill vs slide bg below 3:1)
    PPT-COLOR-004  SmartArt contrast    (advisory — colours not extractable)
    PPT-COLOR-005  Chart label contrast (advisory — colours not extractable)
    PPT-COLOR-006  Theme colours        (colours unresolved -> contrast unverifiable)

Colour data comes from ppt_loader: run["color"], shape["fill_color"] and
slide["background"] are explicit "RRGGBB" hex, or None for theme/inherited
colours that cannot be resolved without the theme. When a text run's foreground
is a theme colour it is counted by PPT-COLOR-006 (unverifiable) rather than
guessed. When only the background is unknown, an assumed background (default
white, env ORION_PPT_ASSUME_BG) is used so light-on-light text is still caught;
the message notes when a background was assumed.
"""
from __future__ import annotations

import os
from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


# --------------------------------------------------------------- WCAG maths --
# Mirrors src/modules/accessibility_pdf/engines/contrast_fixer.py.
def _srgb_channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(r: float, g: float, b: float) -> float:
    """WCAG relative luminance, 0.0 (black) .. 1.0 (white). Inputs 0..1."""
    return (0.2126 * _srgb_channel(r)
            + 0.7152 * _srgb_channel(g)
            + 0.0722 * _srgb_channel(b))


def _contrast(fg: tuple, bg: tuple) -> float:
    """WCAG contrast ratio, 1.0 .. 21.0."""
    l1 = _luminance(*fg[:3])
    l2 = _luminance(*bg[:3])
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _hex_to_rgb01(value) -> tuple[float, float, float] | None:
    if not isinstance(value, str):
        return None
    x = value.strip().lstrip("#").upper()
    if len(x) == 3:
        x = "".join(c * 2 for c in x)
    if len(x) != 6 or any(c not in "0123456789ABCDEF" for c in x):
        return None
    return (int(x[0:2], 16) / 255.0, int(x[2:4], 16) / 255.0, int(x[4:6], 16) / 255.0)


class ColorContrastAgent(BasePPTAccessibilityValidatorAgent):
    """Validate colour contrast across slides (WCAG 1.4.3 AA)."""

    agent_code = "PPT_COLOR_CONTRAST_AGENT"
    agent_name = "PPT Color Contrast Agent"
    category = "Contrast"
    supported_checks = {
        "PPT-COLOR-001",
        "PPT-COLOR-002",
        "PPT-COLOR-003",
        "PPT-COLOR-004",
        "PPT-COLOR-005",
        "PPT-COLOR-006",
    }

    NORMAL_TARGET = 4.5
    LARGE_TARGET = 3.0
    LARGE_PT = 18.0
    LARGE_BOLD_PT = 14.0

    def __init__(self):
        # "" disables the assumption (then unknown-bg text is skipped).
        self._assume_bg = os.environ.get("ORION_PPT_ASSUME_BG", "FFFFFF").strip() or None

    # ---------------------------------------------------------------- dispatch
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides")
        slides = slides if isinstance(slides, list) else []
        dispatch = {
            "PPT-COLOR-001": lambda: self._check_text(slides, large=False),
            "PPT-COLOR-002": lambda: self._check_text(slides, large=True),
            "PPT-COLOR-003": lambda: self._check_shape(slides),
            "PPT-COLOR-004": lambda: self._advisory_kind(slides, "smartart"),
            "PPT-COLOR-005": lambda: self._advisory_kind(slides, "chart"),
            "PPT-COLOR-006": lambda: self._check_theme(slides),
        }
        handler = dispatch.get(check_code)
        if handler is None:
            return self._info(check_code, f"Check {check_code} is not implemented yet",
                              "Implement the requested contrast check")
        return handler()

    # ---------------------------------------------------------------- helpers
    def _issue(self, rule_id, severity, status, message, recommendation,
               page_no=None, auto_fixable=False, internal=False) -> ValidationIssue:
        return ValidationIssue(
            agent_name=self.agent_name, rule_id=rule_id, category=self.category,
            severity=severity, page_no=page_no, message=message,
            recommendation=recommendation, auto_fixable=auto_fixable,
            status=status, internal_check=internal,
        )

    def _pass(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "PASS", message, recommendation)

    def _info(self, rule_id, message, recommendation, internal=True) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "INFO", message, recommendation,
                           internal=internal)

    @staticmethod
    def _slide_no(slide: dict, order_idx: int) -> int:
        idx = slide.get("index")
        return (idx + 1) if isinstance(idx, int) else (order_idx + 1)

    @staticmethod
    def _runs(shape: dict) -> list[dict]:
        paras = shape.get("paragraphs")
        if isinstance(paras, list):
            out = []
            for p in paras:
                if isinstance(p, dict):
                    for r in (p.get("runs") or []):
                        if isinstance(r, dict):
                            out.append(r)
            if out:
                return out
        runs = shape.get("runs")
        return [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []

    def _iter_shapes(self, slides):
        """Yield (slide_no, slide, shape) for all shapes, recursing into groups."""
        def walk(shapes, sno, slide):
            for sh in shapes:
                if not isinstance(sh, dict):
                    continue
                yield sno, slide, sh
                kids = sh.get("shapes")
                if isinstance(kids, list):
                    yield from walk(kids, sno, slide)

        for order_idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            sno = self._slide_no(slide, order_idx)
            shapes = slide.get("shapes")
            if isinstance(shapes, list):
                yield from walk(shapes, sno, slide)

    def _eff_bg_hex(self, shape, slide) -> str | None:
        """Resolved background behind a shape's text: shape fill, else slide bg."""
        fc = shape.get("fill_color")
        if isinstance(fc, str) and _hex_to_rgb01(fc):
            return fc
        bg = slide.get("background")
        if isinstance(bg, str) and _hex_to_rgb01(bg):
            return bg
        return None

    @staticmethod
    def _is_large(run: dict) -> bool:
        sz = run.get("size")
        if not isinstance(sz, (int, float)):
            return False
        if sz >= ColorContrastAgent.LARGE_PT:
            return True
        return bool(run.get("bold")) and sz >= ColorContrastAgent.LARGE_BOLD_PT

    # ---------------------------------------------------------- 001/002 text --
    def _check_text(self, slides, large: bool) -> ValidationIssue:
        rule = "PPT-COLOR-002" if large else "PPT-COLOR-001"
        target = self.LARGE_TARGET if large else self.NORMAL_TARGET
        label = "large" if large else "normal"
        violations = []
        worst = None
        assumed_used = False
        evaluated = 0

        for sno, slide, shape in self._iter_shapes(slides):
            for r in self._runs(shape):
                txt = r.get("text")
                if not isinstance(txt, str) or not txt.strip():
                    continue
                if self._is_large(r) != large:
                    continue
                fg = _hex_to_rgb01(r.get("color"))
                if fg is None:
                    continue                       # theme colour -> COLOR-006
                bg_hex = self._eff_bg_hex(shape, slide)
                if bg_hex is None:
                    if not self._assume_bg:
                        continue
                    bg_hex = self._assume_bg
                    assumed_used = True
                bg = _hex_to_rgb01(bg_hex)
                if bg is None:
                    continue
                evaluated += 1
                ratio = _contrast(fg, bg)
                if ratio < target:
                    violations.append(sno)
                    if worst is None or ratio < worst:
                        worst = ratio

        if evaluated == 0:
            return self._info(rule, f"No {label}-text runs with resolvable colours.",
                              "Set explicit text/background colours to verify contrast.")
        if violations:
            slides_hit = sorted(set(violations))
            note = " (some backgrounds assumed white)" if assumed_used else ""
            return self._issue(
                rule, "HIGH", "FAIL",
                f"{len(violations)} {label}-text run(s) below {target:.1f}:1 "
                f"(worst {worst:.2f}:1) on slide(s) "
                f"{', '.join(map(str, slides_hit))}{note}.",
                f"Darken/lighten text or its background to reach at least "
                f"{target:.1f}:1 for {label} text (WCAG 1.4.3 AA).",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass(rule,
                          f"All {evaluated} {label}-text run(s) meet {target:.1f}:1.",
                          f"Keep {label} text at or above {target:.1f}:1.")

    # ------------------------------------------------------------- 003 shape --
    def _check_shape(self, slides) -> ValidationIssue:
        offenders = []
        evaluated = 0
        for sno, slide, shape in self._iter_shapes(slides):
            if shape.get("decorative"):
                continue
            fill = _hex_to_rgb01(shape.get("fill_color"))
            bg = _hex_to_rgb01(slide.get("background"))
            if fill is None or bg is None:
                continue                           # need both explicit to judge
            evaluated += 1
            if _contrast(fill, bg) < self.LARGE_TARGET:   # non-text: 3:1
                offenders.append((sno, _contrast(fill, bg)))
        if evaluated == 0:
            return self._info("PPT-COLOR-003",
                              "No solid-filled shapes with a resolvable slide background.",
                              "Set explicit fill/background colours to verify shape contrast.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            worst = min(r for _, r in offenders)
            return self._issue(
                "PPT-COLOR-003", "MEDIUM", "WARNING",
                f"{len(offenders)} filled shape(s) contrast < 3:1 with the slide "
                f"background (worst {worst:.2f}:1) on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Give meaningful shapes at least 3:1 against the background "
                "(WCAG 1.4.11 non-text contrast) so they're distinguishable.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-COLOR-003",
                          f"All {evaluated} filled shape(s) meet 3:1 vs background.",
                          "Keep shapes distinguishable from the background.")

    # -------------------------------------------------- 004/005 advisory ----
    def _advisory_kind(self, slides, kind: str) -> ValidationIssue:
        rule = "PPT-COLOR-004" if kind == "smartart" else "PPT-COLOR-005"
        name = "SmartArt" if kind == "smartart" else "chart"
        # Charts are detectable (loader type == "chart"); SmartArt is not
        # reliably distinguishable, so its advisory is generic.
        count = 0
        if kind == "chart":
            for _sno, _slide, shape in self._iter_shapes(slides):
                if str(shape.get("type", "")).lower() == "chart":
                    count += 1
            if count == 0:
                return self._pass(rule, "No charts found.",
                                  "Ensure chart labels/series meet contrast when added.")
        return self._info(
            rule,
            f"{name} colour contrast is theme-driven and not extractable from "
            f"slide structure"
            + (f" ({count} chart(s) present)" if kind == "chart" else "")
            + "; verify manually or via a vision pass.",
            f"Review {name} label/series colours for WCAG AA contrast.",
            internal=True)

    # ------------------------------------------------------------- 006 theme --
    def _check_theme(self, slides) -> ValidationIssue:
        unresolved = []
        total = 0
        for sno, _slide, shape in self._iter_shapes(slides):
            for r in self._runs(shape):
                txt = r.get("text")
                if not isinstance(txt, str) or not txt.strip():
                    continue
                total += 1
                if _hex_to_rgb01(r.get("color")) is None:
                    unresolved.append(sno)
        if total == 0:
            return self._pass("PPT-COLOR-006", "No text runs to evaluate.",
                              "Use explicit colours where contrast matters.")
        if unresolved:
            slides_hit = sorted(set(unresolved))
            return self._issue(
                "PPT-COLOR-006", "LOW", "WARNING",
                f"{len(unresolved)} of {total} text run(s) use theme/auto colours "
                f"whose contrast can't be verified (slide(s) "
                f"{', '.join(map(str, slides_hit))}).",
                "These rely on theme colours; confirm the theme provides >= 4.5:1 "
                "(3:1 for large text), or set explicit colours to make it verifiable.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-COLOR-006",
                          f"All {total} text run(s) use resolvable explicit colours.",
                          "Explicit colours keep contrast verifiable.")
