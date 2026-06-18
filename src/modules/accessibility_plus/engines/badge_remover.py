"""
badge_remover.py
Remove PDFix visual overlay badges (red/orange banners) from PDF content.

PDFix prefixes every badge with a checkmark (U+2715).
We find those, then redact a box covering the full badge.

Requires: pymupdf (pip install pymupdf)
CLI: python badge_remover.py <input.pdf> <output.pdf>
"""

from __future__ import annotations
import json
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_BADGE_MARK = "\u2715"   # checkmark used by PDFix (only in badges)
_RIGHT_EXT = 135.0        # pt to extend right from mark (covers longest badge)
_PAD = 5.0                # pt padding around badge rect


def remove_badges(input_path, output_path):
    """Remove PDFix badge overlays. Returns result dict."""
    try:
        import fitz
    except ImportError:
        print("[BADGE] ERROR: pymupdf not installed")
        return {"error": "pymupdf not installed", "removed": 0, "status": "error"}

    print("[BADGE] input  =", repr(input_path))
    print("[BADGE] output =", repr(output_path))

    doc = fitz.open(str(input_path))
    result = {"status": "ok", "removed": 0, "pages_touched": 0, "details": []}

    for page_num, page in enumerate(doc):
        hits = page.search_for(_BADGE_MARK)
        if not hits:
            continue

        added = 0
        for rect in hits:
            badge_rect = fitz.Rect(
                rect.x0 - _PAD,
                rect.y0 - _PAD,
                rect.x0 + _RIGHT_EXT,
                rect.y1 + _PAD,
            )
            page.add_redact_annot(badge_rect, fill=(1, 1, 1), text="")
            added += 1
            print("[BADGE] page", page_num, ": mark at",
                  "({:.1f},{:.1f})".format(rect.x0, rect.y0),
                  "-> redact ({:.1f},{:.1f},{:.1f},{:.1f})".format(
                      badge_rect.x0, badge_rect.y0, badge_rect.x1, badge_rect.y1))
            result["details"].append({"page": page_num,
                                      "x": round(rect.x0, 1),
                                      "y": round(rect.y0, 1)})

        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        except Exception:
            page.apply_redactions()

        result["removed"] += added
        result["pages_touched"] += 1

    doc.save(str(output_path), garbage=0)
    doc.close()

    print("[BADGE] done: removed={} pages_touched={}".format(
        result["removed"], result["pages_touched"]))
    print("[BADGE] saved ->", output_path)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: badge_remover.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = remove_badges(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
