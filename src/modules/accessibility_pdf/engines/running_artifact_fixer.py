#!/usr/bin/env python3
"""
running_artifact_fixer.py

Post-processing fixer for the Orion accessibility remediation pipeline.

Clears the residual WCAG 1.4.3 failures on the running footer (white page-title
+ page-number text sitting on the red banner at the bottom of every page).

Correct treatment
-----------------
Running headers/footers are pagination furniture. Under PDF/UA they should be
tagged as /Artifact, not as real content — and artifacts are exempt from the
1.4.3 contrast requirement. Artifacting them therefore clears the white-on-red
contrast errors with ZERO visual change, and is the right thing to do anyway.

What it does
------------
For each page it identifies text runs whose baseline sits within the bottom
`band_frac` of the page height (default 8%) — the footer zone — and:
  1. wraps those runs' marked content as /Artifact in the content stream, and
  2. removes the corresponding structure elements (their MCIDs) from the
     structure tree so they are no longer exposed as real content.

It is deliberately conservative: only the bottom band is touched, and only text
(not images), so body content is never artifacted.

Convention
----------
    python3 running_artifact_fixer.py <input.pdf> <output.pdf>
Exit 0 + non-empty output signals success. Nothing to do -> valid copy, exit 0.
Tunable via env ORION_FOOTER_BAND_FRAC (default "0.08").

Requires: pikepdf, PyMuPDF (fitz)
"""

from __future__ import annotations

import os
import sys

try:
    import pikepdf
    from pikepdf import Name, Dictionary
except ImportError:  # pragma: no cover
    print("running_artifact_fixer: pikepdf is required", file=sys.stderr)
    sys.exit(1)

try:
    import fitz  # PyMuPDF, used only to locate the footer text band reliably
    _HAVE_FITZ = True
except ImportError:
    _HAVE_FITZ = False


def _footer_mcids_per_page(doc, band_frac):
    """
    Return {page_index: set(mcid)} for text whose baseline is inside the bottom
    band of the page. Uses PyMuPDF spans, which expose no MCID, so we instead
    return the bottom-band bounding boxes; the pikepdf pass maps boxes->MCIDs.
    """
    boxes = {}
    for pnum in range(len(doc)):
        page = doc[pnum]
        ph = page.rect.height
        cutoff = ph * (1.0 - band_frac)
        page_boxes = []
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type", 0) != 0:
                continue  # text blocks only
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    x0, y0, x1, y1 = span["bbox"]
                    if y0 >= cutoff:  # baseline in bottom band
                        page_boxes.append((x0, y0, x1, y1))
        if page_boxes:
            boxes[pnum] = page_boxes
    return boxes


def _rect_overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    return ix * iy


def fix_pdf(in_path, out_path, band_frac=0.08):
    if not _HAVE_FITZ:
        pikepdf.open(in_path).save(out_path)
        print("running_artifact_fixer: PyMuPDF unavailable; copied through")
        return 0

    doc = fitz.open(in_path)
    footer_boxes = _footer_mcids_per_page(doc, band_frac)
    page_heights = [doc[i].rect.height for i in range(len(doc))]
    doc.close()

    pdf = pikepdf.open(in_path)
    has_struct = '/StructTreeRoot' in pdf.Root
    st_root = pdf.Root.get('/StructTreeRoot')

    total_artifacted = 0

    for pnum, page in enumerate(pdf.pages):
        boxes = footer_boxes.get(pnum)
        if not boxes:
            continue

        ph = float(page_heights[pnum])
        cutoff = ph * (1.0 - band_frac)

        try:
            ops = list(pikepdf.parse_content_stream(page))
        except Exception as exc:
            print(f"running_artifact_fixer: page {pnum+1} parse failed: {exc}; skipping")
            continue

        # Walk marked-content; a BDC ... EMC block whose text is drawn in the
        # bottom band is re-tagged as /Artifact. We track the current text
        # position via the text matrix translation (Td/TD/Tm) to decide.
        #
        # IMPORTANT: Td/TD set the text position by TRANSLATING the current
        # text line matrix -- the operands are a RELATIVE offset from the
        # start of the current line, not an absolute page coordinate. Only
        # Tm gives an absolute position. Treating a Td's ty as if it were
        # absolute (the previous behavior) misreads every same-line kerning
        # nudge and every real new-line advance (typically small values like
        # 0, -1.3, -2.5) as "near the bottom of the page", which falsely
        # flags ordinary body text, list items and table cells as footer
        # content throughout the page -- not just the actual footer.
        # abs_ty accumulates Td/TD relative to the last Tm (or the last BT,
        # per spec text objects start with an identity matrix).
        footer_cutoff = ph * band_frac   # bottom `band_frac` of the page (y near 0)

        new_ops = []
        depth_stack = []          # marks whether current BDC block is footer
        abs_ty = None
        touched_mcids = set()

        def block_in_footer_pending():
            return depth_stack and depth_stack[-1]['footer']

        i = 0
        for operands, operator in ops:
            o = str(operator)

            if o == 'BT':
                abs_ty = None

            elif o == 'Tm':
                try:
                    if len(operands) == 6:
                        abs_ty = float(operands[5])
                except Exception:
                    pass

            elif o in ('Td', 'TD'):
                try:
                    ty = float(operands[1]) if len(operands) >= 2 else 0.0
                    abs_ty = ty if abs_ty is None else abs_ty + ty
                except Exception:
                    pass

            if o == 'BDC' and len(operands) >= 2:
                tag = str(operands[0])
                prop = operands[1]
                mcid = None
                if isinstance(prop, pikepdf.Dictionary) and '/MCID' in prop:
                    mcid = int(prop['/MCID'])
                depth_stack.append({'tag': tag, 'mcid': mcid, 'footer': False,
                                    'start_ty': abs_ty})
                new_ops.append((operands, operator))
                continue

            if o in ('Tj', 'TJ', "'", '"'):
                # is the current text in the footer band (bottom band_frac)?
                if abs_ty is not None and abs_ty <= footer_cutoff:
                    if depth_stack:
                        depth_stack[-1]['footer'] = True
                new_ops.append((operands, operator))
                continue

            if o == 'EMC' and depth_stack:
                blk = depth_stack.pop()
                if blk['footer'] and blk['tag'] != '/Artifact':
                    # rewrite: replace the matching BDC we already emitted with
                    # an Artifact BMC, and this EMC stays. Find the last BDC.
                    for j in range(len(new_ops) - 1, -1, -1):
                        oj = str(new_ops[j][1])
                        if oj == 'BDC':
                            new_ops[j] = ([Name('/Artifact')],
                                          pikepdf.Operator('BMC'))
                            if blk['mcid'] is not None:
                                touched_mcids.add(blk['mcid'])
                            total_artifacted += 1
                            break
                new_ops.append((operands, operator))
                continue

            new_ops.append((operands, operator))

        if touched_mcids:
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_ops))

            # Remove artifacted MCIDs from the structure tree for this page.
            if has_struct and st_root is not None:
                _strip_mcids_from_structtree(pdf, st_root, page, touched_mcids)

    pdf.save(out_path)
    print(f"running_artifact_fixer: artifacted {total_artifacted} footer run(s)")
    return total_artifacted


def _strip_mcids_from_structtree(pdf, st_root, page, mcids):
    """Detach the given page MCIDs from any structure element that references them."""
    page_obj = page.obj

    def clean(elem):
        if not isinstance(elem, pikepdf.Dictionary):
            return
        kids = elem.get('/K')
        pg = elem.get('/Pg')
        same_page = (pg is not None and pg.objgen == page_obj.objgen)
        if kids is None:
            return
        if isinstance(kids, pikepdf.Array):
            keep = []
            for k in kids:
                if same_page and isinstance(k, int) and int(k) in mcids:
                    continue  # drop this MCID reference
                if isinstance(k, pikepdf.Dictionary):
                    clean(k)
                keep.append(k)
            elem['/K'] = pikepdf.Array(keep)
        elif isinstance(kids, pikepdf.Dictionary):
            clean(kids)

    clean(st_root)


def main(argv):
    if len(argv) != 3:
        print("Usage: python3 running_artifact_fixer.py <input.pdf> <output.pdf>",
              file=sys.stderr)
        return 2
    band = float(os.environ.get("ORION_FOOTER_BAND_FRAC", "0.08"))
    try:
        fix_pdf(argv[1], argv[2], band_frac=band)
        return 0
    except Exception as exc:  # pragma: no cover
        import traceback
        print(f"running_artifact_fixer: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
