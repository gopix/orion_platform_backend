"""Step 2: headings, paragraphs, lists and links."""
from __future__ import annotations

import re
from collections import Counter

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer, Item


_TYPED_LIST = re.compile(r"^\s*(?:[•·▪◦‣●○■□\-–—*]\s+|\(?(?:\d{1,3}|[a-zA-Z])[.)]\s+)")
_VAGUE_LINK = {"click here", "here", "link", "this link", "read more", "more", "learn more",
               "click", "this", "go"}
_URL = re.compile(r"^(?:https?://|www\.|mailto:)", re.IGNORECASE)
_NON_HEADING_STYLES = re.compile(r"^(title|subtitle|caption|toc|table of|header|footer)", re.I)


def _snippet(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


class StructureAnalyzer(BaseAnalyzer):
    name = "StructureAnalyzer"
    category = "STRUCTURAL_ACCESSIBILITY"
    required_parts = ("styles",)

    def check_str_001_headings_present(self, ctx, rec):
        minimum = self.catalog.threshold("min_paragraphs_expecting_headings")
        content = [p for p in ctx.body_paragraphs if p.text.strip()]
        if ctx.headings:
            rec.evaluate("STR-001", [])
        elif len(content) < minimum:
            rec.not_applicable("STR-001", "The document is too short to need headings.")
        else:
            rec.evaluate("STR-001", [Item("The document has no heading styles", "Whole document")])

    def check_str_002_heading_hierarchy(self, ctx, rec):
        if not ctx.headings:
            rec.not_applicable("STR-002", "The document has no headings.")
            return
        items, previous = [], None
        for heading in ctx.headings:
            level = heading.heading_level
            if previous is not None and level > previous + 1:
                items.append(Item(
                    f"Incorrect heading hierarchy: Heading {level} follows Heading {previous}",
                    f'Heading "{_snippet(heading.text)}"',
                    f"Use Heading {previous + 1} instead of Heading {level}",
                ))
            previous = level
        rec.evaluate("STR-002", items)

    def check_str_003_first_heading(self, ctx, rec):
        if not ctx.headings:
            rec.not_applicable("STR-003", "The document has no headings.")
            return
        first = ctx.headings[0]
        items = [] if first.heading_level == 1 else [Item(
            f"The first heading is Heading {first.heading_level}",
            f'Heading "{_snippet(first.text)}"', "Use Heading 1 for the first heading")]
        rec.evaluate("STR-003", items)

    def check_str_004_empty_headings(self, ctx, rec):
        if not ctx.headings:
            rec.not_applicable("STR-004", "The document has no headings.")
            return
        rec.evaluate("STR-004", [
            Item(f"Heading {h.heading_level} has no text", h.location)
            for h in ctx.headings if not h.text.strip() and not h.has_drawing])

    def check_str_005_fake_headings(self, ctx, rec):
        limit = self.catalog.threshold("fake_heading_max_chars")
        sizes = Counter()
        for paragraph in ctx.body_paragraphs:
            for run in paragraph.runs:
                sizes[run.size_pt] += len(run.text)
        body_size = sizes.most_common(1)[0][0] if sizes else 0

        items = []
        for paragraph in ctx.body_paragraphs:
            text = paragraph.text.strip()
            if (paragraph.heading_level is not None or paragraph.is_list or not text
                    or len(text) > limit or text[-1] in ".,;:?!"
                    or _NON_HEADING_STYLES.match(paragraph.style_name or "")):
                continue
            runs = [r for r in paragraph.runs if r.text.strip()]
            if runs and (all(r.bold for r in runs) or min(r.size_pt for r in runs) >= body_size + 2):
                items.append(Item(
                    f'Text is formatted like a heading but has no heading style: "{_snippet(text)}"',
                    paragraph.location))
        if items:
            rec.manual("STR-005", items, "Heuristic match; a person must confirm each one.")
        else:
            rec.evaluate("STR-005", [])

    def check_str_006_fake_lists(self, ctx, rec):
        items, streak = [], []

        def flush():
            if len(streak) >= 2:
                items.append(Item(f"{len(streak)} consecutive lines use typed list markers",
                                  streak[0].location))

        for paragraph in ctx.body_paragraphs:
            if not paragraph.is_list and paragraph.heading_level is None \
                    and _TYPED_LIST.match(paragraph.text):
                streak.append(paragraph)
            else:
                flush()
                streak = []
        flush()
        rec.evaluate("STR-006", items)

    def check_str_007_empty_paragraphs(self, ctx, rec):
        items, streak = [], []

        def flush():
            if len(streak) >= 2:
                items.append(Item(f"{len(streak)} consecutive empty paragraphs", streak[0].location))

        for paragraph in ctx.body_paragraphs:
            empty = not paragraph.text.strip() and not (
                paragraph.has_drawing or paragraph.has_page_break or paragraph.has_section_break)
            if empty:
                streak.append(paragraph)
            else:
                flush()
                streak = []
        flush()
        rec.evaluate("STR-007", items)

    def check_str_008_table_of_contents(self, ctx, rec):
        minimum = self.catalog.threshold("min_words_expecting_toc")
        if ctx.word_count < minimum:
            rec.not_applicable("STR-008", f"The document has fewer than {int(minimum)} words.")
            return
        rec.evaluate("STR-008", [] if ctx.has_toc else [
            Item(f"A {ctx.word_count}-word document has no table of contents", "Whole document")])

    def check_str_009_link_text(self, ctx, rec):
        if not ctx.hyperlinks:
            rec.not_applicable("STR-009", "The document has no hyperlinks.")
            return
        items = []
        for link in ctx.hyperlinks:
            text = link.text.strip()
            if not text:
                items.append(Item("Hyperlink has no text", link.location))
            elif _URL.match(text) or text.lower().rstrip(".") in _VAGUE_LINK:
                items.append(Item(f'Link text is not descriptive: "{_snippet(text)}"', link.location))
        rec.evaluate("STR-009", items)

    def check_str_010_layout_spaces(self, ctx, rec):
        pattern = re.compile(r" {%d,}" % int(self.catalog.threshold("layout_spaces_min")))
        rec.evaluate("STR-010", [
            Item("Repeated spaces are used for layout", p.location)
            for p in ctx.body_paragraphs if pattern.search(p.text.strip())])
