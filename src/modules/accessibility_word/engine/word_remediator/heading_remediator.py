"""Fixes heading levels, empty headings and stacks of empty paragraphs."""
from __future__ import annotations

import re

from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

from src.modules.accessibility_word.engine.word_remediator.base_remediator import BaseRemediator
from src.modules.accessibility_word.engine.word_remediator.ooxml_utils import (
    PPR_OUTLINE_SUCCESSORS,
    get_or_insert,
    has_page_break,
    has_section_break,
    has_visual_content,
    in_table_cell,
    paragraph_text,
    snippet,
    story_paragraphs,
)

_HEADING_NAME = re.compile(r"^heading\s+([1-9])$", re.IGNORECASE)
_HEADING_SIZES = {1: 16, 2: 13, 3: 12}


def _outline(ppr):
    if ppr is None:
        return None
    element = ppr.find(qn("w:outlineLvl"))
    if element is None:
        return None
    try:
        return int(element.get(qn("w:val")))
    except (TypeError, ValueError):
        return None


class HeadingRemediator(BaseRemediator):
    name = "HeadingRemediator"
    # Empty headings go first so they no longer count in the hierarchy.
    fixes = {
        "STR-004": "fix_empty_headings",
        "STR-002": "fix_hierarchy",
        "STR-003": "fix_hierarchy",
        "STR-007": "fix_empty_paragraphs",
    }

    # ---- heading detection, matching the validator ---------------------
    def _level(self, ctx, p) -> tuple[int | None, str | None]:
        direct = _outline(p.find(qn("w:pPr")))
        if direct is not None:
            return (direct + 1, "direct") if direct < 9 else (None, None)
        style = Paragraph(p, ctx.document._body).style
        if style is None:
            return None, None
        match = _HEADING_NAME.match((style.name or "").strip())
        if match:
            return int(match.group(1)), "builtin"
        seen, current = set(), style
        while current is not None and current.style_id not in seen:
            seen.add(current.style_id)
            outline = _outline(current.element.find(qn("w:pPr")))
            if outline is not None:
                return (outline + 1, "custom") if outline < 9 else (None, None)
            current = current.base_style
        return None, None

    def _headings(self, ctx):
        for p in story_paragraphs(ctx.body):
            level, source = self._level(ctx, p)
            if level is not None:
                yield p, level, source

    def _heading_style(self, ctx, level: int):
        styles = ctx.document.styles
        try:
            return styles[f"Heading {level}"]
        except KeyError:
            pass
        # The style is only latent in this document, so it is created.
        style = styles.add_style(f"Heading {level}", WD_STYLE_TYPE.PARAGRAPH)
        try:
            style.base_style = styles["Normal"]
            style.next_paragraph_style = styles["Normal"]
        except KeyError:
            pass
        style.quick_style = True
        style.font.bold = True
        style.font.size = Pt(_HEADING_SIZES.get(level, 11))
        ppr = style.element.get_or_add_pPr()
        get_or_insert(ppr, "w:outlineLvl", PPR_OUTLINE_SUCCESSORS).set(qn("w:val"), str(level - 1))
        return style

    def _set_level(self, ctx, p, level: int, source: str) -> None:
        if source == "builtin":
            Paragraph(p, ctx.document._body).style = self._heading_style(ctx, level)
        else:
            # Custom heading styles keep their formatting; only the outline level changes.
            ppr = p.get_or_add_pPr()
            get_or_insert(ppr, "w:outlineLvl", PPR_OUTLINE_SUCCESSORS).set(qn("w:val"), str(level - 1))

    # ---- STR-002 / STR-003 ---------------------------------------------
    def fix_hierarchy(self, ctx, rec):
        """Relevels headings without flattening their structure.

        Each heading becomes one level below its nearest preceding heading of a higher
        original level, so H1, H3, H4, H3 becomes H1, H2, H3, H2. Levels only go down.
        """
        stack: list[tuple[int, int]] = []       # (original level, new level)
        for p, level, source in list(self._headings(ctx)):
            while stack and stack[-1][0] >= level:
                stack.pop()
            new_level = stack[-1][1] + 1 if stack else 1
            stack.append((level, new_level))
            if new_level != level:
                self._set_level(ctx, p, new_level, source)
                rec.applied(f'Heading "{snippet(paragraph_text(p))}"',
                            f"Changed Heading {level} to Heading {new_level}")

    # ---- STR-004 -------------------------------------------------------
    def fix_empty_headings(self, ctx, rec):
        for p, level, _ in list(self._headings(ctx)):
            if paragraph_text(p).strip() or has_visual_content(p):
                continue
            location = f"Empty Heading {level}"
            if self._removable(ctx, p):
                p.getparent().remove(p)
                rec.applied(location, "Removed the empty heading")
                continue
            # Kept because it holds a bookmark or a break; it just stops being a heading.
            ppr = p.find(qn("w:pPr"))
            if ppr is not None:
                for tag in ("w:outlineLvl", "w:pStyle"):
                    element = ppr.find(qn(tag))
                    if element is not None:
                        ppr.remove(element)
            rec.applied(location, "Changed the empty heading to normal text")

    # ---- STR-007 -------------------------------------------------------
    def fix_empty_paragraphs(self, ctx, rec):
        body_paragraphs = [p for p in story_paragraphs(ctx.body) if not in_table_cell(p)]
        streaks, streak = [], []
        for p in body_paragraphs:
            empty = not paragraph_text(p).strip() and not (
                has_visual_content(p) or has_page_break(p) or has_section_break(p))
            if empty:
                streak.append(p)
            else:
                if len(streak) >= 2:
                    streaks.append(streak)
                streak = []
        if len(streak) >= 2:
            streaks.append(streak)

        for streak in streaks:
            removed = 0
            for p in streak[1:]:          # one empty paragraph is kept for spacing
                if self._removable(ctx, p):
                    p.getparent().remove(p)
                    removed += 1
            if removed:
                rec.applied(f"{len(streak)} consecutive empty paragraphs",
                            f"Removed {removed} empty paragraphs")

    @staticmethod
    def _removable(ctx, p) -> bool:
        if paragraph_text(p).strip() or has_visual_content(p) or has_page_break(p) \
                or has_section_break(p):
            return False
        # Bookmarks may be targets of the table of contents or cross-references.
        if next(p.iter(qn("w:bookmarkStart"), qn("w:fldChar"), qn("w:fldSimple")), None) is not None:
            return False
        parent = p.getparent()
        if parent.tag not in (qn("w:body"), qn("w:sdtContent")):
            return False
        return len(ctx.body.findall(qn("w:p"))) > 1
