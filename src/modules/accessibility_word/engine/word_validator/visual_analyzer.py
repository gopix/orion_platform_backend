"""Step 7: fonts and contrast, using color and size resolved through the style chain."""
from __future__ import annotations

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer, Item
from src.modules.accessibility_word.models.finding_models import CheckStatus


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        scaled = value / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _is_chromatic(color: str) -> bool:
    values = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
    return max(values) - min(values) > 40


def _visible_runs(paragraph):
    return [r for r in paragraph.runs if r.text.strip() and not r.hidden]


class VisualAnalyzer(BaseAnalyzer):
    name = "VisualAnalyzer"
    category = "VISUAL_ACCESSIBILITY"
    required_parts = ("styles",)

    def check_vis_001_contrast(self, ctx, rec):
        normal = self.catalog.threshold("min_contrast_normal")
        large = self.catalog.threshold("min_contrast_large")
        failures, unknown, measured = [], [], 0
        for paragraph in ctx.paragraphs:
            worst, uncertain = None, False
            for run in _visible_runs(paragraph):
                if run.color is None:       # automatic color adapts to its background
                    continue
                if not run.background_known:
                    uncertain = True
                    continue
                measured += 1
                is_large = run.size_pt >= 18 or (run.bold and run.size_pt >= 14)
                required = large if is_large else normal
                ratio = contrast_ratio(run.color, run.background)
                if ratio < required and (worst is None or ratio < worst[0]):
                    worst = (ratio, required, run)
            if worst:
                ratio, required, run = worst
                failures.append(Item(
                    f"Contrast is {ratio:.2f}:1, below {required}:1 "
                    f"(#{run.color} on #{run.background})", paragraph.location))
            elif uncertain:
                unknown.append(Item("The background comes from a table style or shape; check contrast by eye",
                                    paragraph.location))
        if failures:
            rec.record("VIS-001", CheckStatus.FAIL, failures)
        elif unknown:
            rec.manual("VIS-001", unknown)
        else:
            rec.evaluate("VIS-001", [], f"{measured} explicitly colored runs measured.")

    def check_vis_002_font_size(self, ctx, rec):
        minimum = self.catalog.threshold("min_font_size_pt")
        items = []
        for paragraph in ctx.paragraphs:
            small = [r.size_pt for r in _visible_runs(paragraph)
                     if r.size_pt < minimum and r.vert_align is None]
            if small:
                items.append(Item(f"Text is {min(small):g}pt, below {minimum:g}pt", paragraph.location))
        rec.evaluate("VIS-002", items)

    def check_vis_003_color_meaning(self, ctx, rec):
        items = []
        for paragraph in ctx.paragraphs:
            if (paragraph.style_name or "").lower() in ("hyperlink",):
                continue
            colored = [r for r in _visible_runs(paragraph)
                       if r.color and _is_chromatic(r.color) and not r.bold and not r.italic
                       and not r.underline]
            if colored:
                items.append(Item(f'Confirm color is not the only signal: "{colored[0].text.strip()[:50]}"',
                                  paragraph.location))
        if not items:
            rec.not_applicable("VIS-003", "No color-only text emphasis was found.")
        else:
            rec.manual("VIS-003", items)

    def check_vis_004_justified(self, ctx, rec):
        rec.evaluate("VIS-004", [
            Item("Paragraph text is justified", p.location) for p in ctx.body_paragraphs
            if p.justification in ("both", "distribute") and p.text.strip()])

    def check_vis_005_all_caps(self, ctx, rec):
        minimum = self.catalog.threshold("all_caps_min_words")
        items = []
        for paragraph in ctx.paragraphs:
            runs = _visible_runs(paragraph)
            caps_words = sum(len(r.text.split()) for r in runs if r.caps or
                             (r.text.isupper() and len(r.text.split()) > 1))
            if caps_words >= minimum:
                items.append(Item(f"{caps_words} words are in all caps", paragraph.location))
        rec.evaluate("VIS-005", items)
