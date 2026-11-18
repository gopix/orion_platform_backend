"""
image_agent.py
==============
ImageAgent — the PPT equivalent of the PDF Figure/Alt agent. Validates every
picture (including pictures nested inside groups) on every slide.

Checks (supported_checks)
    PPT-IMAGE-001  Alt text exists       (informative picture missing alt text)
    PPT-IMAGE-002  Descriptive alt text  (alt is a filename/placeholder/too short)
    PPT-IMAGE-003  Decorative images     (decorative flag vs alt-text consistency)
    PPT-IMAGE-004  Logo alt text         (a logo image with no usable alt)
    PPT-IMAGE-005  Background images     (full-bleed image not decorative & no alt)
    PPT-IMAGE-006  Image contrast        (advisory — needs pixel/vision analysis)

Reads the normalized context produced by ppt_loader (picture shapes carry
"alt_text", "decorative", "image", geometry). "Missing image captions" from the
original spec is folded into 001/002: in PPTX there is no caption element, so an
informative image communicates only through its alt text.

PPT-IMAGE-006 (contrast) cannot be judged from structure alone — it needs the
image pixels. It is returned as an advisory INFO here; a future vision pass (the
PPT analogue of the PDF alt_vision_suggester) is the right place to score it.
"""
from __future__ import annotations

import os
import re
from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)

# Alt text that is not a real description.
_GENERIC_ALT = {
    "image", "picture", "photo", "photograph", "graphic", "img", "pic", "icon",
    "screenshot", "untitled", "figure", "diagram", "shape", "object",
}
_IMG_EXT = re.compile(r"\.(png|jpe?g|gif|bmp|svg|tiff?|webp|emf|wmf|heic)\b", re.I)
_DEFAULT_NAME = re.compile(
    r"^(picture|image|content placeholder|google shape|shape|object|graphic|"
    r"placeholder)\s*[\d;:_-]*$", re.I)
_REDUNDANT_PREFIX = re.compile(r"^(an?\s+)?(image|picture|photo|graphic)\s+of\b", re.I)
_LOGO_HINT = re.compile(r"\blogo\b", re.I)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


class ImageAgent(BasePPTAccessibilityValidatorAgent):
    """Validate image alt text and decorative handling across slides."""

    agent_code = "PPT_IMAGE_AGENT"
    agent_name = "PPT Image Agent"
    category = "Images"
    supported_checks = {
        "PPT-IMAGE-001",
        "PPT-IMAGE-002",
        "PPT-IMAGE-003",
        "PPT-IMAGE-004",
        "PPT-IMAGE-005",
        "PPT-IMAGE-006",
    }

    MIN_ALT_CHARS = 5
    # Fraction of the slide area above which an image is treated as a background.
    BACKGROUND_AREA_FRAC = _env_float("ORION_PPT_BG_AREA_FRAC", 0.8)

    # ---------------------------------------------------------------- dispatch
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides")
        slides = slides if isinstance(slides, list) else []
        slide_w = context.get("slide_width")
        slide_h = context.get("slide_height")

        if check_code == "PPT-IMAGE-001":
            return self._check_alt_exists(slides)
        if check_code == "PPT-IMAGE-002":
            return self._check_alt_descriptive(slides)
        if check_code == "PPT-IMAGE-003":
            return self._check_decorative(slides)
        if check_code == "PPT-IMAGE-004":
            return self._check_logo_alt(slides)
        if check_code == "PPT-IMAGE-005":
            return self._check_background(slides, slide_w, slide_h)
        if check_code == "PPT-IMAGE-006":
            return self._check_contrast(slides)
        return self._info(check_code, f"Check {check_code} is not implemented yet",
                          "Implement the requested image check")

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
    def _is_image(shape: dict) -> bool:
        if str(shape.get("type", "")).lower() in ("picture", "media"):
            return True
        return isinstance(shape.get("image"), dict)

    def _iter_images(self, slides):
        """Yield (slide_no, shape) for every picture, recursing into groups."""
        def walk(shapes, sno):
            for sh in shapes:
                if not isinstance(sh, dict):
                    continue
                if self._is_image(sh):
                    yield sno, sh
                children = sh.get("shapes")
                if isinstance(children, list):
                    yield from walk(children, sno)

        for order_idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            sno = self._slide_no(slide, order_idx)
            shapes = slide.get("shapes")
            if isinstance(shapes, list):
                yield from walk(shapes, sno)

    @staticmethod
    def _alt(shape) -> str:
        a = shape.get("alt_text")
        return a.strip() if isinstance(a, str) else ""

    def _alt_is_weak(self, alt: str) -> bool:
        """True if alt text exists but does not actually describe the image."""
        low = alt.strip().casefold()
        if len(alt.strip()) < self.MIN_ALT_CHARS:
            return True
        if low in _GENERIC_ALT:
            return True
        if _IMG_EXT.search(alt):
            return True
        if _DEFAULT_NAME.match(alt.strip()):
            return True
        if _REDUNDANT_PREFIX.match(alt):
            return True
        return False

    # ---------------------------------------------------------------- 001 exists
    def _check_alt_exists(self, slides) -> ValidationIssue:
        total = 0
        missing = []
        for sno, shape in self._iter_images(slides):
            total += 1
            if shape.get("decorative"):
                continue                       # decorative images need no alt
            if not self._alt(shape):
                missing.append((sno, shape.get("name") or "image"))
        if total == 0:
            return self._pass("PPT-IMAGE-001", "No images found.",
                              "Add alt text to any images you insert later.")
        if missing:
            slides_hit = sorted({s for s, _ in missing})
            return self._issue(
                "PPT-IMAGE-001", "HIGH", "FAIL",
                f"{len(missing)} image(s) missing alt text on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Add descriptive alt text to each informative image, or mark it "
                "decorative if it carries no information.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-IMAGE-001",
                          f"All {total} image(s) have alt text or are decorative.",
                          "Keep alt text on every informative image.")

    # ---------------------------------------------------------------- 002 descriptive
    def _check_alt_descriptive(self, slides) -> ValidationIssue:
        weak = []
        checked = 0
        for sno, shape in self._iter_images(slides):
            if shape.get("decorative"):
                continue
            alt = self._alt(shape)
            if not alt:
                continue                       # absence is 001's job
            checked += 1
            if self._alt_is_weak(alt):
                weak.append((sno, alt[:40]))
        if checked == 0:
            return self._pass("PPT-IMAGE-002", "No populated alt text to evaluate.",
                              "Write alt text that conveys the image's meaning.")
        if weak:
            slides_hit = sorted({s for s, _ in weak})
            examples = "; ".join(f"'{a}'" for _, a in weak[:3])
            return self._issue(
                "PPT-IMAGE-002", "MEDIUM", "FAIL",
                f"{len(weak)} image(s) have non-descriptive alt text on slide(s) "
                f"{', '.join(map(str, slides_hit))} (e.g. {examples}).",
                "Replace filenames/placeholder words with a sentence describing "
                "what the image shows and why it matters here.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-IMAGE-002",
                          f"All {checked} alt text(s) look descriptive.",
                          "Keep alt text specific and meaningful.")

    # ---------------------------------------------------------------- 003 decorative
    def _check_decorative(self, slides) -> ValidationIssue:
        contradictory = []
        for sno, shape in self._iter_images(slides):
            if shape.get("decorative") and self._alt(shape):
                contradictory.append((sno, shape.get("name") or "image"))
        if contradictory:
            slides_hit = sorted({s for s, _ in contradictory})
            return self._issue(
                "PPT-IMAGE-003", "LOW", "WARNING",
                f"{len(contradictory)} image(s) are marked decorative yet still "
                f"carry alt text on slide(s) {', '.join(map(str, slides_hit))}.",
                "A decorative image should have no alt text (screen readers skip "
                "it). Either remove the decorative flag or clear the alt text.",
                page_no=slides_hit[0], auto_fixable=True)
        return self._pass("PPT-IMAGE-003",
                          "Decorative flags are consistent with alt text.",
                          "Mark purely decorative images as decorative.")

    # ---------------------------------------------------------------- 004 logo
    def _check_logo_alt(self, slides) -> ValidationIssue:
        logos_bad = []
        logos_total = 0
        for sno, shape in self._iter_images(slides):
            name = shape.get("name") or ""
            alt = self._alt(shape)
            is_logo = bool(_LOGO_HINT.search(name)) or bool(_LOGO_HINT.search(alt))
            if not is_logo:
                continue
            logos_total += 1
            if shape.get("decorative"):
                continue                       # decorative logo is acceptable
            if not alt or self._alt_is_weak(alt):
                logos_bad.append((sno, name or "logo"))
        if logos_total == 0:
            return self._pass("PPT-IMAGE-004", "No logo images detected.",
                              "Give logos alt text with the organisation name.")
        if logos_bad:
            slides_hit = sorted({s for s, _ in logos_bad})
            return self._issue(
                "PPT-IMAGE-004", "MEDIUM", "FAIL",
                f"{len(logos_bad)} logo image(s) lack meaningful alt text on "
                f"slide(s) {', '.join(map(str, slides_hit))}.",
                "Set the logo's alt text to the organisation/brand name (e.g. "
                "'Acme Corp logo'), or mark it decorative if repeated as chrome.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-IMAGE-004",
                          f"All {logos_total} logo image(s) have alt text.",
                          "Use the brand name as logo alt text.")

    # ---------------------------------------------------------------- 005 background
    def _check_background(self, slides, slide_w, slide_h) -> ValidationIssue:
        if not isinstance(slide_w, (int, float)) or not isinstance(slide_h, (int, float)) \
                or slide_w <= 0 or slide_h <= 0:
            return self._info("PPT-IMAGE-005",
                              "Slide dimensions unavailable; cannot assess background images.",
                              "Loader should provide slide_width/slide_height.")
        slide_area = float(slide_w) * float(slide_h)
        offenders = []
        evaluated = False
        for sno, shape in self._iter_images(slides):
            w, h = shape.get("width"), shape.get("height")
            if not isinstance(w, (int, float)) or not isinstance(h, (int, float)) \
                    or w <= 0 or h <= 0:
                continue
            evaluated = True
            if (w * h) >= self.BACKGROUND_AREA_FRAC * slide_area:
                if not shape.get("decorative") and not self._alt(shape):
                    offenders.append((sno, shape.get("name") or "image"))
        if not evaluated:
            return self._info("PPT-IMAGE-005",
                              "No sized images to assess for background coverage.",
                              "Loader should provide image width/height.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-IMAGE-005", "HIGH", "FAIL",
                f"{len(offenders)} full-bleed background image(s) are neither "
                f"decorative nor described on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Mark a purely decorative background as decorative; if it carries "
                "information, add alt text describing it.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-IMAGE-005",
                          "Background-sized images are decorative or described.",
                          "Mark decorative backgrounds so screen readers skip them.")

    # ---------------------------------------------------------------- 006 contrast
    def _check_contrast(self, slides) -> ValidationIssue:
        count = sum(1 for _ in self._iter_images(slides))
        if count == 0:
            return self._pass("PPT-IMAGE-006", "No images to assess for contrast.",
                              "Ensure images with text/icons have sufficient contrast.")
        return self._info(
            "PPT-IMAGE-006",
            f"{count} image(s) present; contrast needs pixel/vision analysis and "
            "is not evaluated from slide structure.",
            "Run a vision-based pass (or manual review) to check contrast of any "
            "text or icons rendered inside images.",
            internal=True)
