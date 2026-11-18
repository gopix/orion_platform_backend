"""
title_remediation_agent.py
==========================
TitleRemediationAgent — ensures every slide has a real, unique title, mutating
context["presentation"] in place.

Rules handled (supported_rules)
    PPT-STRUCTURE-001  Slide missing a title
    PPT-STRUCTURE-002  Placeholder / fake title
    PPT-HEADING-002    Placeholder title
    PPT-HEADING-003    Duplicate titles

Per slide, in order:
    1. If a title placeholder exists but is empty or a fake default
       ("Click to add title", "Title", ...)  -> fill it with a derived title.
    2. If there is NO title placeholder but a prominent text box exists
       -> promote that text box to the title placeholder (inject <p:ph type=title>).
    3. If the slide has no usable text at all
       -> add a title box with an AI-generated title (context["title_fn"] or
          Claude), else "Slide N".
Then a final pass renames any DUPLICATE titles ("Overview" -> "Overview (2)").

Title source for (1): the most prominent text on the slide (largest font,
top-most) — its first line. This is deterministic; AI is only used for slides
with no text to derive from.
"""
from __future__ import annotations

import os
from typing import Any

from pptx.util import Inches, Pt
from pptx.oxml.ns import qn

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_FAKE_TITLES = {
    "", "click to add title", "title", "untitled", "untitled presentation",
    "add a title", "add title", "slide title", "click to edit master title style",
}
_MAX_TITLE = 120
_DEFAULT_MODEL = os.environ.get("orion-claude-model", "claude-haiku-4-5-20251001")


class TitleRemediationAgent(BasePPTRemediationAgent):
    """Give every slide a real, unique title."""

    agent_name = "PPT Title Remediation Agent"
    supported_rules = {"PPT-STRUCTURE-001", "PPT-STRUCTURE-002",
                       "PPT-HEADING-002", "PPT-HEADING-003"}

    def remediate(self, issue, context) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-STRUCTURE-001")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "title", error=str(exc))
        try:
            changes = []
            for si, slide in enumerate(prs.slides):
                res = self._ensure_title(slide, si, context)
                if res:
                    changes.append(f"slide {si + 1}: {res}")
            changes += self._dedupe_titles(prs)
            return self._result(rule_id, True, "fix_titles", changes_made=changes)
        except Exception as exc:
            return self._result(rule_id, False, "title", error=str(exc))

    # --------------------------------------------------------------- per slide
    def _ensure_title(self, slide, si, context) -> str | None:
        title_shape = self._title_shape(slide)
        if title_shape is not None:
            cur = (title_shape.text or "").strip()
            if cur and cur.casefold() not in _FAKE_TITLES:
                return None                       # already a real title
            new = self._derive_title(slide, si, context, exclude=title_shape)
            title_shape.text = new
            return f"set title to '{new}'" + (f" (was '{cur}')" if cur else "")

        # no title placeholder -> promote a prominent text box, else add one
        cand = self._best_text_candidate(slide)
        if cand is not None:
            if self._promote_to_title(cand):
                t = self._first_line(cand.text)
                return f"promoted text box to title ('{t}')"
        new = self._derive_title(slide, si, context, exclude=None)
        self._add_title_box(slide, new)
        return f"added title box '{new}'"

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _title_shape(slide):
        try:
            return slide.shapes.title
        except Exception:
            return None

    @staticmethod
    def _first_line(text: str) -> str:
        line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
        return line[:_MAX_TITLE]

    def _best_text_candidate(self, slide):
        """Most prominent non-title text box (largest font, then top-most)."""
        best, best_key = None, None
        title_el = getattr(self._title_shape(slide), "_element", None)
        for shape in slide.shapes:
            try:
                if shape._element is title_el:
                    continue
                if not shape.has_text_frame or not (shape.text_frame.text or "").strip():
                    continue
                sizes = [r.font.size.pt for p in shape.text_frame.paragraphs
                         for r in p.runs if r.font.size is not None]
                size = max(sizes) if sizes else 0.0
                top = shape.top if shape.top is not None else 10 ** 9
                key = (size, -top)               # bigger font, then higher up
                if best_key is None or key > best_key:
                    best, best_key = shape, key
            except Exception:
                continue
        return best

    def _derive_title(self, slide, si, context, exclude) -> str:
        cand = self._best_text_candidate(slide)
        if cand is not None and getattr(cand, "_element", None) is not getattr(exclude, "_element", None):
            t = self._first_line(cand.text)
            if t:
                return t
        # nothing to derive from -> AI (optional), else Slide N
        ai = self._ai_title(slide, context)
        return ai or f"Slide {si + 1}"

    # --------------------------------------------------------------- promote
    @staticmethod
    def _promote_to_title(shape) -> bool:
        try:
            sp = shape._element
            nvSpPr = sp.find(qn("p:nvSpPr"))
            if nvSpPr is None:
                return False
            nvPr = nvSpPr.find(qn("p:nvPr"))
            if nvPr is None:
                nvPr = nvSpPr.makeelement(qn("p:nvPr"), {})
                nvSpPr.append(nvPr)
            if nvPr.find(qn("p:ph")) is None:
                ph = nvPr.makeelement(qn("p:ph"), {})
                ph.set("type", "title")
                nvPr.insert(0, ph)               # <p:ph> is first child of nvPr
            return True
        except Exception:
            return False

    def _add_title_box(self, slide, text):
        tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
        self._promote_to_title(tb)
        tf = tb.text_frame
        tf.text = text
        try:
            tf.paragraphs[0].runs[0].font.size = Pt(28)
        except Exception:
            pass
        return tb

    # --------------------------------------------------------------- dedupe
    def _dedupe_titles(self, prs) -> list[str]:
        seen: dict[str, int] = {}
        changes = []
        for si, slide in enumerate(prs.slides):
            ts = self._title_shape(slide)
            if ts is None:
                continue
            t = (ts.text or "").strip()
            if not t:
                continue
            key = t.casefold()
            if key in seen:
                seen[key] += 1
                new = f"{t} ({seen[key]})"
                ts.text = new
                changes.append(f"slide {si + 1}: renamed duplicate title -> '{new}'")
            else:
                seen[key] = 1
        return changes

    # --------------------------------------------------------------- AI (opt)
    def _ai_title(self, slide, context) -> str:
        title_fn = context.get("title_fn")
        text = self._slide_text(slide)
        if not text.strip():
            return ""
        if title_fn is not None:
            try:
                return self._clean(title_fn(text))
            except Exception:
                return ""
        api_key = context.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return ""
        try:
            import anthropic
            model = context.get("model") or _DEFAULT_MODEL
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=model, max_tokens=40,
                messages=[{"role": "user", "content":
                           "Write a concise (max 8 words) slide title for this "
                           "content. Return only the title.\n\n" + text[:1500]}])
            return self._clean("".join(
                b.text for b in msg.content if getattr(b, "type", "") == "text"))
        except Exception:
            return ""

    @staticmethod
    def _slide_text(slide) -> str:
        parts = []
        for shape in slide.shapes:
            try:
                if shape.has_text_frame and (shape.text_frame.text or "").strip():
                    parts.append(shape.text_frame.text.strip())
            except Exception:
                continue
        return "\n".join(parts)

    @staticmethod
    def _clean(s: str) -> str:
        s = " ".join((s or "").split()).strip().strip('"').strip("'")
        return s[:_MAX_TITLE]
