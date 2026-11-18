"""Step 4: document properties, language and document state."""
from __future__ import annotations

import re

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer, Item


_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_PLACEHOLDER_TITLES = {"word document", "document", "untitled", "title", "document1", "new document"}


class MetadataAnalyzer(BaseAnalyzer):
    name = "MetadataAnalyzer"
    category = "METADATA_ACCESSIBILITY"
    required_parts = ("styles", "core")

    def check_met_001_title(self, ctx, rec):
        title = ctx.metadata.title.strip()
        if not title:
            items = [Item("The document title is missing", "Document properties")]
        elif title.lower() in _PLACEHOLDER_TITLES:
            items = [Item(f'The document title is a placeholder: "{title}"', "Document properties")]
        else:
            items = []
        rec.evaluate("MET-001", items)

    def check_met_002_author(self, ctx, rec):
        rec.evaluate("MET-002", [] if ctx.metadata.author.strip() else [
            Item("The document author is missing", "Document properties")])

    def check_met_003_language_set(self, ctx, rec):
        rec.evaluate("MET-003", [] if ctx.metadata.default_language.strip() else [
            Item("No default document language is set", "Document defaults (styles.xml)")])

    def check_met_004_language_valid(self, ctx, rec):
        language = ctx.metadata.default_language.strip()
        if not language:
            rec.not_applicable("MET-004", "No language tag to validate.")
            return
        rec.evaluate("MET-004", [] if _LANGUAGE_TAG.match(language) else [
            Item(f'Invalid language tag: "{language}"', "Document defaults (styles.xml)")])

    def check_met_005_language_changes(self, ctx, rec):
        default = ctx.metadata.default_language.strip().lower()
        tagged = sorted({
            run.lang for paragraph in ctx.paragraphs for run in paragraph.runs
            if run.lang and run.lang.lower() != default})
        detail = f"Other languages tagged: {', '.join(tagged)}" if tagged else             "No other languages are tagged; untagged foreign text cannot be detected statically."
        rec.manual("MET-005", [Item("Confirm foreign-language passages are tagged", "Whole document")],
                   detail)

    def check_met_006_document_state(self, ctx, rec):
        items = []
        if ctx.tracked_changes:
            items.append(Item(f"{ctx.tracked_changes} tracked changes remain", "Whole document"))
        if ctx.comments:
            items.append(Item(f"{ctx.comments} comments remain", "Whole document"))
        rec.evaluate("MET-006", items)
