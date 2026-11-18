"""Fixes document title, author and default language."""
from __future__ import annotations

import re
from pathlib import Path

from docx.oxml.ns import qn

from src.modules.accessibility_word.engine.word_remediator.base_remediator import BaseRemediator
from src.modules.accessibility_word.engine.word_remediator.ooxml_utils import (
    RPR_LANG_SUCCESSORS,
    get_or_insert,
    get_or_insert_first,
    paragraph_text,
    story_paragraphs,
)
from src.modules.accessibility_word.engine.word_validator.metadata_analyzer import (
    _LANGUAGE_TAG,
    _PLACEHOLDER_TITLES,
)

_HEADING_1 = re.compile(r"^heading\s*1$", re.IGNORECASE)
_MAX_TITLE = 255


class MetadataRemediator(BaseRemediator):
    name = "MetadataRemediator"
    fixes = {
        "MET-001": "fix_title",
        "MET-002": "fix_author",
        "MET-003": "fix_language",
        "MET-004": "fix_language",
    }

    # ---- MET-001 -------------------------------------------------------
    def fix_title(self, ctx, rec):
        props = ctx.document.core_properties
        current = (props.title or "").strip()
        if current and current.lower() not in _PLACEHOLDER_TITLES:
            return
        title, source = self._derive_title(ctx)
        props.title = title
        rec.applied("Document properties", f'Set the title to "{title}"',
                    review=source == "file name", detail=f"Taken from the {source}.")

    def _derive_title(self, ctx) -> tuple[str, str]:
        styles = ctx.document.styles.element
        names = {s.get(qn("w:styleId")): (s.find(qn("w:name")).get(qn("w:val"), "")
                                          if s.find(qn("w:name")) is not None else "")
                 for s in styles.iter(qn("w:style"))}
        first_heading = None
        for p in story_paragraphs(ctx.body):
            ppr = p.find(qn("w:pPr"))
            style = ppr.find(qn("w:pStyle")) if ppr is not None else None
            name = names.get(style.get(qn("w:val")), "") if style is not None else ""
            text = paragraph_text(p).strip()
            if not text:
                continue
            if name.lower() == "title":
                return text[:_MAX_TITLE], "Title-style paragraph"
            if first_heading is None and _HEADING_1.match(name):
                first_heading = text
        if first_heading:
            return first_heading[:_MAX_TITLE], "first Heading 1"
        stem = re.sub(r"[_\-]+", " ", Path(ctx.file_name).stem).strip()
        return (stem or "Untitled document")[:_MAX_TITLE], "file name"

    # ---- MET-002 -------------------------------------------------------
    def fix_author(self, ctx, rec):
        author = (ctx.options.default_author or "").strip()
        if not author:
            rec.skip("No default author is configured.")
            return
        ctx.document.core_properties.author = author
        rec.applied("Document properties", f'Set the author to "{author}"')

    # ---- MET-003 / MET-004 ---------------------------------------------
    def fix_language(self, ctx, rec):
        language = ctx.options.default_language
        styles = ctx.document.styles.element
        defaults = get_or_insert_first(styles, "w:docDefaults")
        rpr_default = get_or_insert_first(defaults, "w:rPrDefault")
        rpr = get_or_insert_first(rpr_default, "w:rPr")
        targets = [("Document defaults (styles.xml)", rpr)]

        # A language on the Normal style overrides the defaults, so an invalid one is fixed too.
        for style in styles.iter(qn("w:style")):
            if style.get(qn("w:type")) == "paragraph" and style.get(qn("w:default")) in ("1", "true", "on"):
                style_rpr = style.find(qn("w:rPr"))
                lang = style_rpr.find(qn("w:lang")) if style_rpr is not None else None
                if lang is not None and lang.get(qn("w:val")):
                    targets.append(("Default paragraph style", style_rpr))

        for location, parent in targets:
            lang = get_or_insert(parent, "w:lang", RPR_LANG_SUCCESSORS)
            old = lang.get(qn("w:val"))
            if old and _LANGUAGE_TAG.match(old):
                continue
            lang.set(qn("w:val"), language)
            rec.applied(location, f'Set the default language to "{language}"'
                        + (f' (was "{old}")' if old else ""),
                        review=True, detail="The configured default; confirm it is the document's language.")
        if rec.actions:
            ctx.document.core_properties.language = language
