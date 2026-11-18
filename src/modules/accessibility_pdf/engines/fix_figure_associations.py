#!/usr/bin/env python3
"""
fix_figure_associations.py

Fixes the Adobe Accessibility Checker error:
    "Associated with content - Failed"  (Element 1, Element 2, ...)

Cause
-----
A PDF/UA structure tree can contain <Figure> tags that already carry alt text
and a layout BBox, but were never linked to the actual image drawn on the page.
Acrobat flags each such tag as "not associated with content".

A valid association needs TWO things:
    1. In the structure tree:   Figure  /K = <MCID>
    2. In the page content stream:  /Figure <</MCID n>> BDC ... (image Do) ... EMC
    3. The page ParentTree entry maps that MCID back to the Figure tag.

This script finds every orphaned <Figure> tag, matches it to its image on the
page (by comparing the tag's stored BBox against where the image is actually
drawn, computed by tracking the content-stream transformation matrix), wraps
that image's draw operation in marked content, and wires up both directions of
the link.

Usage
-----
    python3 fix_figure_associations.py input.pdf output.pdf

Requires: pikepdf  (pip install pikepdf)
"""

import sys
from collections import defaultdict

import pikepdf
from pikepdf import Matrix, Name, Dictionary


def get_page_idx(pdf, pg_ref):
    """Return the 0-based page index for a /Pg reference, or None."""
    if pg_ref is None:
        return None
    for i, p in enumerate(pdf.pages):
        if p.obj.objgen == pg_ref.objgen:
            return i
    return None


def collect_orphan_figures(pdf, st_root):
    """Walk the structure tree; return Figure tags that have no /K content link."""
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
                'pageidx': get_page_idx(pdf, pg),
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


def _apply(m, x, y):
    """Transform point (x, y) by matrix m: x' = a*x + c*y + e ; y' = b*x + d*y + f."""
    a, b, c, d, e, f = m.a, m.b, m.c, m.d, m.e, m.f
    return (a * x + c * y + e, b * x + d * y + f)


def _bbox_dist(b1, b2):
    return sum(abs(b1[i] - b2[i]) for i in range(4))


def find_image_do_ops(pdf, pidx, ops):
    """
    Walk a page's content stream, tracking the CTM (q/Q/cm), and return the
    page-space bounding box of every image draw op (Do on an /Image XObject).
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
            xobj = page['/Resources']['/XObject'][name]
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


def fix_pdf(in_path, out_path):
    pdf = pikepdf.open(in_path)

    if '/StructTreeRoot' not in pdf.Root:
        print("ERROR: PDF has no structure tree (not tagged). Nothing to fix.")
        sys.exit(1)

    st_root = pdf.Root['/StructTreeRoot']
    orphans = collect_orphan_figures(pdf, st_root)
    print(f"Found {len(orphans)} orphan Figure element(s) to fix")

    if not orphans:
        pdf.save(out_path)
        print("Nothing to do; saved a copy.")
        return

    by_page = defaultdict(list)
    for o in orphans:
        by_page[o['pageidx']].append(o)

    # ParentTree /Nums is a flat list: [key0, val0, key1, val1, ...]
    nums = st_root['/ParentTree']['/Nums']

    def nums_value_index_for_key(key):
        for i in range(0, len(nums), 2):
            if int(nums[i]) == key:
                return i + 1
        return None

    total_fixed = 0

    for pidx, orph_list in sorted(by_page.items()):
        page = pdf.pages[pidx]
        ops = pikepdf.parse_content_stream(page)
        do_ops = find_image_do_ops(pdf, pidx, ops)

        # Greedily match each orphan tag to the closest unused image by BBox.
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
                print(f"  WARNING: no free image to match {o['alt']!r} on page {pidx+1}")
                continue
            used.add(best['idx'])
            wrap_idxs[best['idx']] = o

        # New MCIDs are appended after the current ParentTree entry length,
        # which guarantees they are free (we only ever append).
        sp_key = int(page['/StructParents'])
        parray = nums[nums_value_index_for_key(sp_key)]
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

        # Pad the ParentTree entry so index == MCID, then wire both directions.
        while len(parray) < next_mcid:
            parray.append(None)

        for do_idx, orphan in wrap_idxs.items():
            mcid = mcid_map[do_idx]
            elem = orphan['elem']
            elem['/K'] = mcid       # tag  -> content
            parray[mcid] = elem     # content -> tag
            total_fixed += 1

        if mcid_map:
            print(f"Page {pidx+1}: fixed {len(mcid_map)} figure(s), "
                  f"mcids {sorted(mcid_map.values())}")

    print(f"\nTotal figures fixed: {total_fixed}")
    pdf.save(out_path)
    print(f"Saved: {out_path}")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 fix_figure_associations.py input.pdf output.pdf")
        sys.exit(1)
    fix_pdf(sys.argv[1], sys.argv[2])
