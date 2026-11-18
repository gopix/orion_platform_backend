"""Adds alt text through a pluggable provider (for example an AI vision service).

Without a provider nothing is changed: alt text cannot be invented by static analysis,
so those images stay with a person.
"""
from __future__ import annotations

import logging
from pathlib import PurePosixPath

from docx.oxml.ns import qn
from lxml import etree

from src.modules.accessibility_word.engine.word_remediator.base_remediator import BaseRemediator
from src.modules.accessibility_word.engine.word_remediator.ooxml_utils import is_alternate_fallback
from src.modules.accessibility_word.engine.word_validator.image_analyzer import (
    _DEFAULT_NAME,
    _FILE_NAME,
)

logger = logging.getLogger(__name__)
_WP_DOCPR = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"


class ImageRemediator(BaseRemediator):
    name = "ImageRemediator"
    fixes = {
        "IMG-001": "fix_missing_alt",
        "IMG-002": "fix_placeholder_alt",
    }

    def fix_missing_alt(self, ctx, rec):
        self._describe(ctx, rec, lambda alt, name, target: not alt)

    def fix_placeholder_alt(self, ctx, rec):
        self._describe(ctx, rec, lambda alt, name, target: bool(alt) and (
            _FILE_NAME.search(alt) or _DEFAULT_NAME.match(alt) or alt == name
            or alt.lower() == target.lower()))

    def _describe(self, ctx, rec, needs_text):
        provider = ctx.options.alt_text_provider
        if provider is None:
            rec.skip("No alt-text provider is configured; a person must write the alt text.")
            return
        failures = 0
        for index, doc_pr in enumerate(self._pictures(ctx)):
            alt = (doc_pr.get("descr") or "").strip()
            name = doc_pr.get("name", "")
            blob, target, content_type = self._image(ctx, doc_pr)
            if blob is None or not needs_text(alt, name, target):
                continue
            try:
                text = (provider(blob, {"name": name, "existing_alt": alt,
                                        "content_type": content_type}) or "").strip()
            except Exception:
                logger.exception("Alt-text provider failed for %s", name)
                failures += 1
                continue
            if text:
                doc_pr.set("descr", text)
                rec.applied(f'Image "{name or index + 1}"', f'Set alt text to "{text[:80]}"',
                            review=True, detail="Generated automatically; confirm it is accurate.")
        if failures and not rec.actions:
            rec.skip(f"The alt-text provider failed for {failures} images.")

    @staticmethod
    def _pictures(ctx):
        for doc_pr in ctx.body.iter(_WP_DOCPR):
            if is_alternate_fallback(doc_pr):
                continue
            decorative = any(isinstance(el.tag, str) and etree.QName(el).localname == "decorative"
                             and el.get("val") in ("1", "true") for el in doc_pr.iter())
            if not decorative:
                yield doc_pr

    @staticmethod
    def _image(ctx, doc_pr):
        blip = doc_pr.getparent().find(".//" + _A_BLIP)
        rel_id = blip.get(qn("r:embed")) if blip is not None else None
        part = ctx.document.part.related_parts.get(rel_id) if rel_id else None
        if part is None:
            return None, "", None
        return part.blob, PurePosixPath(str(part.partname)).name, part.content_type
