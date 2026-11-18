#!/usr/bin/env python3
"""
figure_association_fixer.py

Post-processing fixer for the Orion accessibility remediation pipeline.

Clears Adobe Acrobat's Accessibility Checker error:
    "Associated with content - Failed"  (Element 1, Element 2, ...)

Problem
-------
A tagged PDF can carry <Figure> structure elements that already have alt text
and a layout /BBox, but were never linked to the image actually painted on the
page. PDFix AddTags() and downstream alt-text generation can both leave figures
in this state. Acrobat then reports each such tag as "not associated with
content".

A valid figure→content association requires BOTH directions to exist:
    1. Structure element:      <Figure>  /K = <MCID>
    2. Page content stream:    /Figure <</MCID n>> BDC ... (image `Do`) ... EMC
    3. Page ParentTree entry:  maps that MCID back to the <Figure> element

This fixer locates each orphaned <Figure> (a Figure element whose /K is absent),
matches it to its image on the page (by comparing the element's stored /BBox
against where each image is actually painted — computed by tracking the content
stream's transformation matrix), wraps that image's paint operator in marked
content, and wires up both directions of the association.

Convention
----------
Mirrors the other *_fixer.py post-processing scripts:
    python3 figure_association_fixer.py <input.pdf> <output.pdf>
Exit code 0 and a non-empty output file signal success to the pipeline.
If there is nothing to fix, it still writes a valid copy and exits 0.

Requires: pikepdf
"""

from __future__ import annotations

import sys
from collections import defaultdict

try:
    import pikepdf
    from pikepdf import Matrix, Name, Dictionary
except ImportError:  # pragma: no cover
    print("figure_association_fixer: pikepdf is required", file=sys.stderr)
    sys.exit(1)


# ── structure-tree traversal ──────────────────────────────────────────────

def _page_index_for(pdf, pg_ref):
    """Return the 0-based page index for a /Pg reference, or None."""
    if pg_ref is None:
        return None
    for i, p in enumerate(pdf.pages):
        if p.obj.objgen == pg_ref.objgen:
            return i
    return None


def _collect_orphan_figures(pdf, st_root):
    """Return <Figure> elements that have no /K content link (orphans)."""
    orphans = []

    def walk(elem, parent_pg=None):
        if not isinstance(elem, pikepdf.Dictionary):
            return
        s = str(elem.get('/S'))
        kids = elem.get('/K')
        pg = elem.get('/Pg', parent_pg)

        if kids is None and s == '/Figure':
            a = elem.get('/A')
            bbox = a.get('/BBox') if a else None
            orphans.append({
                'elem': elem,
                'pageidx': _page_index_for(pdf, pg),
                'bbox': [float(x) for x in bbox] if bbox else None,
                'alt': str(elem.get('/Alt')),
            })

        if kids is not None:
            if isinstance(kids, pikepdf.Array):
                for k in kids:
                    walk(k, pg)
            elif isinstance(kids, pikepdf.Dictionary):
                walk(kids, pg)

    walk(st_root)
    return orphans


# ── content-stream geometry ───────────────────────────────────────────────

def _apply(m, x, y):
    """Transform (x, y) by matrix m: x' = a*x + c*y + e ; y' = b*x + d*y + f."""
    a, b, c, d, e, f = m.a, m.b, m.c, m.d, m.e, m.f
    return (a * x + c * y + e, b * x + d * y + f)


def _bbox_dist(b1, b2):
    return sum(abs(b1[i] - b2[i]) for i in range(4))


def _find_image_do_ops(pdf, pidx, ops):
    """
    Walk a page's content stream tracking the CTM (q/Q/cm) and return the
    page-space bounding box of every image paint op (Do on an /Image XObject).
    """
    page = pdf.pages[pidx]
    stack = []
    ctm = Matrix(1, 0, 0, 1, 0, 0)
    results = []
    for i, (operands, operator) in enumerate(ops):
        op = str(operator)
        if op == 'q':
            stack.append(ctm)
        elif op == 'Q':
            if stack:
                ctm = stack.pop()
        elif op == 'cm':
            a, b, c, d, e, f = [float(x) for x in operands]
            ctm = Matrix(a, b, c, d, e, f) @ ctm
        elif op == 'Do':
            name = str(operands[0])
            try:
                xobj = page['/Resources']['/XObject'][name]
            except Exception:
                continue
            if xobj.get('/Subtype') != Name('/Image'):
                continue
            pts = [_apply(ctm, x, y) for x, y in [(0, 0), (1, 0), (0, 1), (1, 1)]]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            results.append({
                'idx': i,
                'name': name,
                'bbox': (min(xs), min(ys), max(xs), max(ys)),
            })
    return results


# ── main fix ──────────────────────────────────────────────────────────────

def fix_pdf(in_path, out_path):
    """Return the number of figures fixed (>= 0). Always writes out_path."""
    pdf = pikepdf.open(in_path)

    if '/StructTreeRoot' not in pdf.Root:
        # Untagged PDF: nothing this fixer can do. Emit a valid copy.
        pdf.save(out_path)
        print("figure_association_fixer: no structure tree; copied through")
        return 0

    st_root = pdf.Root['/StructTreeRoot']

    if '/ParentTree' not in st_root:
        pdf.save(out_path)
        print("figure_association_fixer: no ParentTree; copied through")
        return 0

    orphans = _collect_orphan_figures(pdf, st_root)
    print(f"figure_association_fixer: found {len(orphans)} orphan Figure element(s)")

    if not orphans:
        pdf.save(out_path)
        return 0

    by_page = defaultdict(list)
    for o in orphans:
        # Skip orphans we can't place (no page or no bbox) — safer than guessing.
        if o['pageidx'] is None or o['bbox'] is None:
            continue
        by_page[o['pageidx']].append(o)

    nums = st_root['/ParentTree']['/Nums']

    def nums_value_index_for_key(key):
        for i in range(0, len(nums), 2):
            if int(nums[i]) == key:
                return i + 1
        return None

    total_fixed = 0

    for pidx, orph_list in sorted(by_page.items()):
        page = pdf.pages[pidx]

        if '/StructParents' not in page:
            print(f"figure_association_fixer: page {pidx+1} has no /StructParents; skipping")
            continue

        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception as exc:
            print(f"figure_association_fixer: page {pidx+1} parse failed: {exc}; skipping")
            continue

        do_ops = _find_image_do_ops(pdf, pidx, ops)
        if not do_ops:
            continue

        # Greedily match each orphan tag to the nearest unused image by BBox.
        used = set()
        wrap_idxs = {}  # content-stream op index -> orphan
        for o in orph_list:
            best, best_score = None, None
            for d in do_ops:
                if d['idx'] in used:
                    continue
                score = _bbox_dist(o['bbox'], d['bbox'])
                if best_score is None or score < best_score:
                    best_score, best = score, d
            if best is None:
                print(f"figure_association_fixer: no free image for {o['alt']!r} "
                      f"on page {pidx+1}")
                continue
            used.add(best['idx'])
            wrap_idxs[best['idx']] = o

        if not wrap_idxs:
            continue

        # New MCIDs are appended after the current ParentTree entry length,
        # which guarantees they don't collide with existing MCIDs.
        sp_key = int(page['/StructParents'])
        val_idx = nums_value_index_for_key(sp_key)
        if val_idx is None:
            print(f"figure_association_fixer: page {pidx+1} StructParents={sp_key} "
                  f"missing from ParentTree; skipping")
            continue
        parray = nums[val_idx]
        next_mcid = len(parray)

        # Rewrite the content stream, wrapping each matched image in BDC/EMC.
        new_ops = []
        mcid_map = {}
        for i, (operands, operator) in enumerate(ops):
            if i in wrap_idxs:
                mcid = next_mcid
                next_mcid += 1
                mcid_map[i] = mcid
                new_ops.append(([Name('/Figure'), Dictionary(MCID=mcid)],
                                pikepdf.Operator('BDC')))
                new_ops.append((operands, operator))
                new_ops.append(([], pikepdf.Operator('EMC')))
            else:
                new_ops.append((operands, operator))

        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_ops))

        # Pad ParentTree entry so index == MCID, then wire both directions.
        while len(parray) < next_mcid:
            parray.append(None)

        for do_idx, orphan in wrap_idxs.items():
            mcid = mcid_map[do_idx]
            elem = orphan['elem']
            elem['/K'] = mcid       # tag  -> content (MCID)
            parray[mcid] = elem     # content (MCID) -> tag
            total_fixed += 1

        print(f"figure_association_fixer: page {pidx+1} fixed {len(mcid_map)} "
              f"figure(s), mcids {sorted(mcid_map.values())}")

    pdf.save(out_path)
    print(f"figure_association_fixer: total figures fixed = {total_fixed}")
    return total_fixed


def main(argv):
    if len(argv) != 3:
        print("Usage: python3 figure_association_fixer.py <input.pdf> <output.pdf>",
              file=sys.stderr)
        return 2
    in_path, out_path = argv[1], argv[2]
    try:
        fix_pdf(in_path, out_path)
        return 0
    except Exception as exc:  # pragma: no cover
        import traceback
        print(f"figure_association_fixer: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
