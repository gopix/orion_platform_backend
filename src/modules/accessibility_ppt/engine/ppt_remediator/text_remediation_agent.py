"""
text_remediation_agent.py
=========================
TextRemediationAgent — fixes text legibility/structure issues, mutating
context["presentation"] in place.

Rules handled (supported_rules)
    PPT-TEXT-002  Font too small        -> raise run size to the legible minimum
    PPT-TEXT-003  Manual line breaks    -> split into real paragraphs
    PPT-TEXT-004  Inconsistent fonts    -> normalise to the deck's dominant font
    PPT-TEXT-005  Text overflow         -> enable "shrink text on overflow"
    PPT-TEXT-006  Invisible text        -> recolour to contrast with the background

Plus (spec item, no validator rule): excessive ALL CAPS -> drop the all-caps
formatting effect, and lower long literal all-caps runs to sentence case. This
runs opportunistically on every invocation; disable with ORION_PPT_FIX_ALLCAPS=0.

Design notes
  * Overflow uses PowerPoint's shrink-to-fit (normAutofit fontScale): it scales
    the DISPLAY size only, leaving each run's real point size intact — so it
    never conflicts with the min-font fix or the validator (which reads the run
    size).
  * Font normalisation is design-invasive, so it only collapses to the dominant
    family, and only runs when dispatched for PPT-TEXT-004.
  * ALL-CAPS lowering skips short runs (acronyms) — only long all-caps prose is
    converted.
"""
from __future__ import annotations

import copy
import math
import os
from typing import Any
from collections import Counter

from pptx.util import Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.ns import qn

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _envf(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _envi(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _srgb(c):
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb):
    r, g, b = rgb[:3]
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def _hex_rgb01(v):
    if not isinstance(v, str):
        return None
    x = v.strip().lstrip("#").upper()
    if len(x) == 3:
        x = "".join(c * 2 for c in x)
    if len(x) != 6 or any(c not in "0123456789ABCDEF" for c in x):
        return None
    return (int(x[0:2], 16) / 255, int(x[2:4], 16) / 255, int(x[4:6], 16) / 255)


def _color_hex(color):
    try:
        if color is None or color.type is None:
            return None
        return str(color.rgb)
    except Exception:
        return None


class TextRemediationAgent(BasePPTRemediationAgent):
    """Fix small fonts, line breaks, font consistency, overflow, invisible text."""

    agent_name = "PPT Text Remediation Agent"
    supported_rules = {"PPT-TEXT-002", "PPT-TEXT-003", "PPT-TEXT-004",
                       "PPT-TEXT-005", "PPT-TEXT-006"}

    MIN_FONT_PT = _envf("ORION_PPT_MIN_FONT_PT", 18.0)
    MAX_FONTS = _envi("ORION_PPT_MAX_FONTS", 3)

    def remediate(self, issue, context) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-TEXT-002")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "text", error=str(exc))
        try:
            handler = {
                "PPT-TEXT-002": self._fix_small_font,
                "PPT-TEXT-003": self._fix_line_breaks,
                "PPT-TEXT-004": self._fix_font_consistency,
                "PPT-TEXT-005": self._fix_overflow,
                "PPT-TEXT-006": self._fix_invisible_text,
            }.get(rule_id, self._fix_small_font)
            changes = handler(prs)
            if os.environ.get("ORION_PPT_FIX_ALLCAPS", "1").strip().lower() \
                    not in ("0", "false", "no", "off"):
                changes += self._fix_all_caps(prs)
            action = {"PPT-TEXT-002": "raise_font_size",
                      "PPT-TEXT-003": "split_line_breaks",
                      "PPT-TEXT-004": "normalize_fonts",
                      "PPT-TEXT-005": "enable_shrink_to_fit",
                      "PPT-TEXT-006": "recolor_invisible_text"}.get(rule_id, "text")
            return self._result(rule_id, True, action, changes_made=changes)
        except Exception as exc:
            return self._result(rule_id, False, "text", error=str(exc))

    # --------------------------------------------------------------- iterators
    def _text_shapes(self, prs):
        for si, shape in self._iter_shapes(prs):
            try:
                if shape.has_text_frame:
                    yield si, shape
            except Exception:
                continue

    @staticmethod
    def _runs(tf):
        for para in tf.paragraphs:
            for run in para.runs:
                yield run

    # --------------------------------------------------------------- 002 size
    def _fix_small_font(self, prs):
        changes, bumped = [], 0
        for si, shape in self._text_shapes(prs):
            for run in self._runs(shape.text_frame):
                try:
                    sz = run.font.size
                    if sz is not None and sz.pt < self.MIN_FONT_PT:
                        run.font.size = Pt(self.MIN_FONT_PT)
                        bumped += 1
                except Exception:
                    continue
        if bumped:
            changes.append(f"raised {bumped} run(s) to {self.MIN_FONT_PT:.0f}pt minimum")
        return changes

    # --------------------------------------------------------------- 003 breaks
    def _fix_line_breaks(self, prs):
        changes, split = [], 0
        for si, shape in self._text_shapes(prs):
            txBody = shape.text_frame._txBody
            for p in list(txBody.findall(qn("a:p"))):
                if p.find(qn("a:br")) is None:
                    continue
                if self._split_paragraph_on_breaks(txBody, p):
                    split += 1
        if split:
            changes.append(f"split {split} paragraph(s) with manual line breaks "
                           "into separate paragraphs")
        return changes

    @staticmethod
    def _split_paragraph_on_breaks(txBody, p) -> bool:
        pPr = p.find(qn("a:pPr"))
        groups = [[]]
        for child in list(p):
            if child.tag == qn("a:br"):
                groups.append([])
            elif child.tag == qn("a:pPr"):
                continue
            else:
                groups[-1].append(child)
        groups = [g for g in groups if g]
        if len(groups) < 2:
            return False
        new_ps = []
        for g in groups:
            np = p.makeelement(qn("a:p"), {})
            if pPr is not None:
                np.append(copy.deepcopy(pPr))
            for child in g:
                np.append(child)              # moves the element
            new_ps.append(np)
        for np in new_ps:
            p.addprevious(np)
        txBody.remove(p)
        return True

    # --------------------------------------------------------------- 004 fonts
    def _fix_font_consistency(self, prs):
        counts = Counter()
        for si, shape in self._text_shapes(prs):
            for run in self._runs(shape.text_frame):
                fn = run.font.name
                if fn:
                    counts[fn] += 1
        if not counts:
            return []
        dominant = counts.most_common(1)[0][0]
        distinct = len(counts)
        changes, changed = [], 0
        for si, shape in self._text_shapes(prs):
            for run in self._runs(shape.text_frame):
                try:
                    if run.font.name and run.font.name != dominant:
                        run.font.name = dominant
                        changed += 1
                except Exception:
                    continue
        if changed:
            changes.append(f"normalised {changed} run(s) from {distinct} fonts to "
                           f"'{dominant}'")
        return changes

    # --------------------------------------------------------------- 005 overflow
    def _fix_overflow(self, prs):
        changes, fixed = [], 0
        for si, shape in self._text_shapes(prs):
            tf = shape.text_frame
            try:
                if tf.auto_size == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE:
                    continue
                w, h = shape.width, shape.height
                if None in (w, h):
                    continue
                w_pt, h_pt = w / 12700.0, h / 12700.0
                text = tf.text or ""
                if not text.strip() or w_pt <= 0 or h_pt <= 0:
                    continue
                sizes = [r.font.size.pt for r in self._runs(tf)
                         if r.font.size is not None]
                size = (sum(sizes) / len(sizes)) if sizes else self.MIN_FONT_PT
                cpl = max(1, int(w_pt / (0.5 * size)))
                lines = max(1, math.ceil(len(text) / cpl))
                if lines * 1.2 * size > h_pt * 1.3:
                    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
                    tf.word_wrap = True
                    fixed += 1
            except Exception:
                continue
        if fixed:
            changes.append(f"enabled shrink-to-fit on {fixed} overflowing text box(es)")
        return changes

    # --------------------------------------------------------------- 006 invisible
    def _fix_invisible_text(self, prs):
        assume = _hex_rgb01(os.environ.get("ORION_PPT_ASSUME_BG", "FFFFFF"))
        changes, fixed = [], 0
        for si, shape in self._text_shapes(prs):
            slide = prs.slides[si]
            bg = self._shape_fill_rgb(shape) or self._slide_bg_rgb(slide) or assume
            if bg is None:
                continue
            new_col = RGBColor(0, 0, 0) if _lum(bg) > 0.5 else RGBColor(0xFF, 0xFF, 0xFF)
            for run in self._runs(shape.text_frame):
                fg = _hex_rgb01(_color_hex(run.font.color))
                if fg is None or not (run.text or "").strip():
                    continue
                if abs(_lum(fg) - _lum(bg)) < 0.02:       # ~identical -> invisible
                    try:
                        run.font.color.rgb = new_col
                        fixed += 1
                    except Exception:
                        continue
        if fixed:
            changes.append(f"recoloured {fixed} invisible (same-as-background) run(s)")
        return changes

    @staticmethod
    def _shape_fill_rgb(shape):
        try:
            from pptx.enum.dml import MSO_FILL_TYPE
            if shape.fill.type == MSO_FILL_TYPE.SOLID:
                return _hex_rgb01(_color_hex(shape.fill.fore_color))
        except Exception:
            pass
        return None

    @staticmethod
    def _slide_bg_rgb(slide):
        try:
            return _hex_rgb01(_color_hex(slide.background.fill.fore_color))
        except Exception:
            return None

    # --------------------------------------------------------------- all caps
    def _fix_all_caps(self, prs):
        changes, effect, lowered = [], 0, 0
        for si, shape in self._text_shapes(prs):
            for run in self._runs(shape.text_frame):
                try:
                    rPr = run._r.find(qn("a:rPr"))
                    if rPr is not None and rPr.get("cap") in ("all", "small"):
                        del rPr.attrib["cap"]           # reveal real casing
                        effect += 1
                        continue
                    txt = run.text or ""
                    letters = [c for c in txt if c.isalpha()]
                    if (letters and all(c.isupper() for c in letters)
                            and len(letters) > 10 and len(txt.split()) >= 2):
                        run.text = txt.capitalize()
                        lowered += 1
                except Exception:
                    continue
        if effect:
            changes.append(f"removed ALL-CAPS formatting from {effect} run(s)")
        if lowered:
            changes.append(f"lowered {lowered} long ALL-CAPS run(s) to sentence case")
        return changes
