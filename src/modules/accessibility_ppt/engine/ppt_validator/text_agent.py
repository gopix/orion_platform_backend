"""
text_agent.py
=============
TextAgent — validates every text-bearing shape on every slide.

Checks (supported_checks)
    PPT-TEXT-001  Empty text box        (a text placeholder/box with no content)
    PPT-TEXT-002  Small font            (runs below the legible minimum)
    PPT-TEXT-003  Hardcoded line breaks (manual <a:br> used instead of structure)
    PPT-TEXT-004  Font consistency      (too many distinct fonts / mixed in a box)
    PPT-TEXT-005  Text overflow         (text likely spills outside its box)
    PPT-TEXT-006  Invisible text        (font colour == background: hidden content)

EXPECTED CONTEXT SCHEMA  (the .pptx loader must populate this)
-------------------------------------------------------------
context["slides"] : list[dict], one per slide in order. Each slide:
    {
      "index": int,                     # 0-based (optional; falls back to order)
      "background": "RRGGBB" | None,    # resolved slide background colour
      "shapes": [ shape, ... ],
    }
Each shape (only text-bearing shapes need the text fields):
    {
      "type": "text"|"placeholder"|"title"|"body"|"picture"|"table"|"group"|...,
      "name": str,
      "has_text_frame": bool,
      "is_title": bool,
      "text": str,                      # concatenated plain text
      "fill_color": "RRGGBB" | None,    # shape fill (background behind its text)
      "autosize": "none"|"shape"|"text"|None,
      "left": float, "top": float,      # points
      "width": float, "height": float,  # points
      "paragraphs": [                   # preferred (richer); optional
        {
          "line_breaks": int,           # count of manual <a:br> in this paragraph
          "runs": [
            {"text": str, "size": float|None, "font": str|None,
             "bold": bool, "italic": bool, "color": "RRGGBB"|None}
          ],
        },
      ],
      "runs": [ {...same run shape...} ],  # flat fallback if no paragraphs
    }

Every field is read defensively: when the data needed for a check is absent, the
check returns PASS/INFO ("insufficient data") rather than a false positive, so
the agent is safe to wire in before the loader emits every field.
"""
from __future__ import annotations

import os
from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


class TextAgent(BasePPTAccessibilityValidatorAgent):
    """Validate text legibility and structure across slides."""

    agent_code = "PPT_TEXT_AGENT"
    agent_name = "PPT Text Agent"
    category = "Text"
    supported_checks = {
        "PPT-TEXT-001",
        "PPT-TEXT-002",
        "PPT-TEXT-003",
        "PPT-TEXT-004",
        "PPT-TEXT-005",
        "PPT-TEXT-006",
    }

    # Tunable thresholds (env-overridable; sensible presentation defaults).
    MIN_FONT_PT = _env_float("ORION_PPT_MIN_FONT_PT", 18.0)    # legible minimum
    TINY_FONT_PT = _env_float("ORION_PPT_TINY_FONT_PT", 12.0)  # clearly too small
    MAX_FONT_FAMILIES = _env_int("ORION_PPT_MAX_FONTS", 3)     # deck-wide variety
    MAX_BREAKS_PER_PARA = _env_int("ORION_PPT_MAX_BREAKS", 2)  # manual <a:br>

    # ---------------------------------------------------------------- dispatch
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides")
        slides = slides if isinstance(slides, list) else []

        dispatch = {
            "PPT-TEXT-001": self._check_empty_textbox,
            "PPT-TEXT-002": self._check_small_font,
            "PPT-TEXT-003": self._check_hardcoded_breaks,
            "PPT-TEXT-004": self._check_font_consistency,
            "PPT-TEXT-005": self._check_text_overflow,
            "PPT-TEXT-006": self._check_invisible_text,
        }
        handler = dispatch.get(check_code)
        if handler is None:
            return self._info(check_code, f"Check {check_code} is not implemented yet",
                              "Implement the requested text check")
        return handler(slides)

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

    def _info(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "INFO", message, recommendation,
                           internal=True)

    @staticmethod
    def _slide_no(slide: dict, order_idx: int) -> int:
        idx = slide.get("index")
        return (idx + 1) if isinstance(idx, int) else (order_idx + 1)

    @staticmethod
    def _shapes(slide: dict) -> list[dict]:
        sh = slide.get("shapes")
        return [s for s in sh if isinstance(s, dict)] if isinstance(sh, list) else []

    @staticmethod
    def _is_text_shape(shape: dict) -> bool:
        if shape.get("has_text_frame"):
            return True
        if str(shape.get("type", "")).lower() in {"text", "placeholder", "title", "body"}:
            return True
        return isinstance(shape.get("text"), str)

    @staticmethod
    def _runs(shape: dict) -> list[dict]:
        """Flattened runs from paragraphs (preferred) or the flat 'runs' list."""
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

    @staticmethod
    def _shape_text(shape: dict) -> str:
        t = shape.get("text")
        if isinstance(t, str) and t.strip():
            return t
        parts = []
        for r in TextAgent._runs(shape):
            rt = r.get("text")
            if isinstance(rt, str):
                parts.append(rt)
        return "".join(parts)

    def _iter_text_shapes(self, slides):
        for order_idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            sno = self._slide_no(slide, order_idx)
            for shape in self._shapes(slide):
                if self._is_text_shape(shape):
                    yield sno, slide, shape

    # ---------------------------------------------------------------- 001 empty
    def _check_empty_textbox(self, slides) -> ValidationIssue:
        offenders = []
        for sno, _slide, shape in self._iter_text_shapes(slides):
            # A shape that CAN hold text but holds none is dead weight the screen
            # reader still visits. Real pictures/tables are not text shapes here.
            if not self._shape_text(shape).strip():
                if shape.get("has_text_frame") or str(shape.get("type", "")).lower() \
                        in {"text", "placeholder", "title", "body"}:
                    offenders.append((sno, shape.get("name") or "text box"))
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TEXT-001", "MEDIUM", "FAIL",
                f"{len(offenders)} empty text box(es) on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Delete empty text boxes/placeholders so they don't clutter the "
                "reading order announced by screen readers.",
                page_no=slides_hit[0], auto_fixable=True)
        return self._pass("PPT-TEXT-001", "No empty text boxes found.",
                          "Remove empty placeholders as you author slides.")

    # ---------------------------------------------------------------- 002 small
    def _check_small_font(self, slides) -> ValidationIssue:
        tiny, small = [], []
        saw_size = False
        for sno, _slide, shape in self._iter_text_shapes(slides):
            for r in self._runs(shape):
                sz = r.get("size")
                if not isinstance(sz, (int, float)) or sz <= 0:
                    continue
                saw_size = True
                if sz < self.TINY_FONT_PT:
                    tiny.append((sno, sz))
                elif sz < self.MIN_FONT_PT:
                    small.append((sno, sz))
        if not saw_size:
            return self._info("PPT-TEXT-002",
                              "No run font sizes available to evaluate.",
                              "Loader should emit run 'size' (pt) for this check.")
        if tiny or small:
            hits = tiny + small
            slides_hit = sorted({s for s, _ in hits})
            smallest = min(sz for _, sz in hits)
            sev = "HIGH" if tiny else "MEDIUM"
            return self._issue(
                "PPT-TEXT-002", sev, "FAIL",
                f"{len(hits)} text run(s) below {self.MIN_FONT_PT:.0f}pt "
                f"(smallest {smallest:.0f}pt) on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                f"Increase body text to at least {self.MIN_FONT_PT:.0f}pt "
                "(presentation legibility guideline).",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TEXT-002",
                          f"All text is at least {self.MIN_FONT_PT:.0f}pt.",
                          "Keep body text large enough to read from a distance.")

    # ---------------------------------------------------------------- 003 breaks
    def _check_hardcoded_breaks(self, slides) -> ValidationIssue:
        offenders = []
        saw_para = False
        for sno, _slide, shape in self._iter_text_shapes(slides):
            paras = shape.get("paragraphs")
            if not isinstance(paras, list):
                continue
            saw_para = True
            for p in paras:
                if isinstance(p, dict):
                    br = p.get("line_breaks")
                    if isinstance(br, int) and br >= self.MAX_BREAKS_PER_PARA:
                        offenders.append((sno, br))
        if not saw_para:
            return self._info("PPT-TEXT-003",
                              "No paragraph break data available to evaluate.",
                              "Loader should emit paragraph 'line_breaks' counts.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TEXT-003", "LOW", "WARNING",
                f"{len(offenders)} paragraph(s) use >= {self.MAX_BREAKS_PER_PARA} "
                f"manual line breaks on slide(s) {', '.join(map(str, slides_hit))}.",
                "Use separate paragraphs, bullet lists, or spacing settings "
                "instead of manual line breaks so structure is conveyed to AT.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TEXT-003", "No overuse of manual line breaks.",
                          "Prefer real paragraphs/lists over manual line breaks.")

    # ---------------------------------------------------------------- 004 fonts
    def _check_font_consistency(self, slides) -> ValidationIssue:
        families: set[str] = set()
        mixed_shapes = []
        for sno, _slide, shape in self._iter_text_shapes(slides):
            shape_fonts = set()
            for r in self._runs(shape):
                fn = r.get("font")
                if isinstance(fn, str) and fn.strip():
                    families.add(fn.strip())
                    shape_fonts.add(fn.strip())
            if len(shape_fonts) >= 3:      # many fonts inside one box
                mixed_shapes.append((sno, sorted(shape_fonts)))
        if not families:
            return self._info("PPT-TEXT-004",
                              "No font-family data available to evaluate.",
                              "Loader should emit run 'font' names.")
        problems = []
        if len(families) > self.MAX_FONT_FAMILIES:
            problems.append(
                f"{len(families)} distinct fonts across the deck "
                f"({', '.join(sorted(families))})")
        if mixed_shapes:
            slides_hit = sorted({s for s, _ in mixed_shapes})
            problems.append(f"{len(mixed_shapes)} text box(es) mix 3+ fonts "
                            f"(slide(s) {', '.join(map(str, slides_hit))})")
        if problems:
            return self._issue(
                "PPT-TEXT-004", "LOW", "WARNING", "; ".join(problems) + ".",
                f"Limit the deck to <= {self.MAX_FONT_FAMILIES} font families and "
                "avoid mixing fonts within a single text box for consistency.",
                page_no=None, auto_fixable=False)
        return self._pass("PPT-TEXT-004",
                          f"Font usage is consistent ({len(families)} families).",
                          "Keep a small, consistent set of fonts.")

    # ---------------------------------------------------------------- 005 overflow
    def _check_text_overflow(self, slides) -> ValidationIssue:
        offenders = []
        evaluated = False
        for sno, _slide, shape in self._iter_text_shapes(slides):
            text = self._shape_text(shape)
            w, h = shape.get("width"), shape.get("height")
            if not text.strip() or not isinstance(w, (int, float)) \
                    or not isinstance(h, (int, float)) or w <= 0 or h <= 0:
                continue
            # Only shapes that DON'T auto-resize can visually overflow.
            if str(shape.get("autosize", "")).lower() not in ("", "none"):
                continue
            sizes = [r.get("size") for r in self._runs(shape)
                     if isinstance(r.get("size"), (int, float)) and r.get("size") > 0]
            size = (sum(sizes) / len(sizes)) if sizes else self.MIN_FONT_PT
            evaluated = True
            # Conservative capacity estimate: avg glyph ~0.5*size wide, line
            # height ~1.2*size. Flag only when text needs >1.3x the box height,
            # so normal fitting text never trips.
            glyph_w = 0.5 * size
            line_h = 1.2 * size
            chars_per_line = max(1, int(w / glyph_w))
            lines_needed = max(1, -(-len(text) // chars_per_line))  # ceil div
            needed_h = lines_needed * line_h
            if needed_h > h * 1.3:
                offenders.append((sno, shape.get("name") or "text box"))
        if not evaluated:
            return self._info("PPT-TEXT-005",
                              "No sizeable fixed-size text boxes to evaluate.",
                              "Loader should emit width/height (pt) and autosize.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TEXT-005", "MEDIUM", "WARNING",
                f"{len(offenders)} text box(es) likely overflow their frame on "
                f"slide(s) {', '.join(map(str, slides_hit))}.",
                "Shorten the text, enlarge the box, or enable 'Shrink text on "
                "overflow' so no content is visually clipped.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TEXT-005", "No obvious text overflow detected.",
                          "Keep text within its box or enable autosize.")

    # ---------------------------------------------------------------- 006 invisible
    def _check_invisible_text(self, slides) -> ValidationIssue:
        offenders = []
        evaluated = False
        for sno, slide, shape in self._iter_text_shapes(slides):
            bg = shape.get("fill_color") or slide.get("background")
            if not isinstance(bg, str):
                continue
            for r in self._runs(shape):
                col = r.get("color")
                txt = r.get("text")
                if not isinstance(col, str) or not isinstance(txt, str) or not txt.strip():
                    continue
                evaluated = True
                if self._same_color(col, bg):
                    offenders.append((sno, txt.strip()[:30]))
                    break
        if not evaluated:
            return self._info("PPT-TEXT-006",
                              "No run colour + background data to evaluate.",
                              "Loader should emit run 'color' and shape/slide bg.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TEXT-006", "HIGH", "FAIL",
                f"{len(offenders)} text run(s) match their background colour "
                f"(invisible) on slide(s) {', '.join(map(str, slides_hit))}.",
                "Give text a colour that contrasts with its background; remove "
                "any hidden text that isn't meant to be read.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TEXT-006", "No invisible (same-as-background) text.",
                          "Ensure text colour differs from the background.")

    # ---------------------------------------------------------------- color util
    @staticmethod
    def _same_color(a: str, b: str) -> bool:
        def norm(x: str):
            x = x.strip().lstrip("#").upper()
            if len(x) == 3:
                x = "".join(c * 2 for c in x)
            return x if len(x) == 6 and all(c in "0123456789ABCDEF" for c in x) else None
        na, nb = norm(a), norm(b)
        return na is not None and na == nb
