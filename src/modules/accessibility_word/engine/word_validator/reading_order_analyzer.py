"""Step 5: reading sequence and layout risks. True visual order needs a rendered page."""
from __future__ import annotations

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer, Item


class ReadingOrderAnalyzer(BaseAnalyzer):
    name = "ReadingOrderAnalyzer"
    category = "READING_ORDER"

    def check_rod_001_text_boxes(self, ctx, rec):
        rec.evaluate("ROD-001", [
            Item(f'Text box content sits outside the main flow: "{box.text[:60]}"', box.location)
            for box in ctx.text_boxes])

    def check_rod_002_floating_objects(self, ctx, rec):
        items = [Item(f"Floating {image.kind} is not inline with text", image.location)
                 for image in ctx.images if image.floating and not image.decorative]
        items += [Item("Floating text box is not inline with text", box.location)
                  for box in ctx.text_boxes if box.floating]
        rec.evaluate("ROD-002", items)

    def check_rod_003_columns(self, ctx, rec):
        columns = [s for s in ctx.sections if s.columns > 1]
        if not columns:
            rec.not_applicable("ROD-003", "The document has no multi-column sections.")
            return
        rec.manual("ROD-003", [
            Item(f"Section {section.index + 1} has {section.columns} columns",
                 f"Section {section.index + 1}") for section in columns])

    def check_rod_004_headers_footers(self, ctx, rec):
        found = [p for p in ctx.paragraphs if p.container in ("header", "footer") and p.text.strip()]
        if not found:
            rec.not_applicable("ROD-004", "The document has no header or footer text.")
            return
        unique = {(p.container, p.text.strip()): p for p in found}
        rec.manual("ROD-004", [
            Item(f'Confirm this is not essential: "{text[:60]}"', paragraph.location)
            for (_, text), paragraph in unique.items()])

    def check_rod_005_tab_tables(self, ctx, rec):
        items, streak = [], []

        def flush():
            if len(streak) >= 2:
                items.append(Item(f"{len(streak)} consecutive lines are aligned into columns with tabs",
                                  streak[0].location))

        for paragraph in ctx.body_paragraphs:
            is_toc = (paragraph.style_name or "").lower().startswith("toc")
            if paragraph.text.strip().count("\t") >= 2 and not is_toc:
                streak.append(paragraph)
            else:
                flush()
                streak = []
        flush()
        rec.evaluate("ROD-005", items)
