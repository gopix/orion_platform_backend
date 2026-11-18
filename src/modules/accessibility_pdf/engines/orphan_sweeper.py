#!/usr/bin/env python3
"""
orphan_sweeper.py
=================
FINAL pass. Guarantees the invariant PAC cares most about:

    every marked-content block in every content stream has a struct parent.

Anything that removes or re-parents struct elements can leave a BDC/MCID behind
with nobody owning it.  PAC reports those in bulk under "Content", and the file
fails PDF/UA even though the tag tree looks fine in isolation.

Two outcomes, decided by what the content actually is:

  * orphan WITH text   -> attached to a new <P>, inserted at its correct
                          reading position (page, then vertical position).
                          Never artifact real words - that hides them from
                          assistive tech.
  * orphan WITHOUT text -> re-marked /Artifact.  Untagged path art or a stray
                          rule is decorative by definition.

Run this last, after every other fixer.  It is cheap, and it is the difference
between "my audit says clean" and "PAC says clean".

Usage
-----
    python orphan_sweeper.py in.pdf out.pdf [--report]
"""
from __future__ import annotations

import sys

import pikepdf
from pikepdf import Dictionary, Name, Array

try:
    from .mcid_geometry import page_mcid_boxes
    from .struct_utils import (rebuild_parent_tree, artifact_mcids,
                               fix_struct_parents, add_figure_bboxes)
except ImportError:
    from mcid_geometry import page_mcid_boxes
    from struct_utils import (rebuild_parent_tree, artifact_mcids,
                              fix_struct_parents, add_figure_bboxes)


def _content_mcids(page):
    found, seen = set(), set()

    def scan(obj, res, depth=0):
        if depth > 4:
            return
        try:
            instrs = pikepdf.parse_content_stream(obj)
        except Exception:
            return
        stack = []
        for ops, op in instrs:
            o = str(op)
            if o in ("BDC", "BMC"):
                tag = str(ops[0]) if ops else "?"
                mcid = None
                if o == "BDC" and len(ops) > 1:
                    p = ops[1]
                    if isinstance(p, Dictionary) and "/MCID" in p:
                        mcid = int(p["/MCID"])
                    elif isinstance(p, Name):
                        props = res.get("/Properties") if res is not None else None
                        if props is not None:
                            d = props.get(str(p))
                            if d is not None and "/MCID" in d:
                                mcid = int(d["/MCID"])
                if mcid is not None and not any(t == "/Artifact" for t in stack):
                    found.add(mcid)
                stack.append(tag)
            elif o == "EMC":
                if stack:
                    stack.pop()
            elif o == "Do":
                xod = res.get("/XObject")
                if xod is None:
                    continue
                xo = xod.get(str(ops[0]))
                if xo is not None and xo.get("/Subtype") == Name("/Form") \
                        and "/StructParents" not in xo \
                        and xo.objgen not in seen:
                    seen.add(xo.objgen)
                    scan(xo, xo.get("/Resources") or res, depth + 1)

    scan(page.obj, page.get("/Resources") or Dictionary())
    return found


def run(inp, outp, report=False):
    pdf = pikepdf.open(inp)
    pages = list(pdf.pages)
    pidx = {p.obj.objgen: i for i, p in enumerate(pages)}
    st = pdf.Root["/StructTreeRoot"]

    owners = {}

    def walk(node, cur, parent):
        if isinstance(node, Array):
            for k in node:
                walk(k, cur, parent)
            return
        if isinstance(node, int):
            if cur is not None:
                owners[(cur, int(node))] = parent
            return
        if not isinstance(node, Dictionary):
            return
        t = node.get("/Type")
        if t == Name("/MCR"):
            pg = node.get("/Pg")
            pi = pidx.get(pg.objgen) if pg is not None else cur
            if pi is not None:
                owners[(pi, int(node.get("/MCID")))] = parent
            return
        if t == Name("/OBJR"):
            return
        pg = node.get("/Pg")
        nxt = pidx.get(pg.objgen) if pg is not None else cur
        walk(node.get("/K"), nxt, node if node.get("/S") is not None else parent)

    walk(st.get("/K"), None, None)

    # the array of top-level blocks, so a rescued <P> lands in reading order
    root = st.get("/K")
    doc = root[0] if isinstance(root, Array) else root
    blocks = doc["/K"]

    def block_key(el):
        lv = []
        walk_leaves(el, None, lv)
        if not lv:
            return (10 ** 6, 0.0)
        pg = lv[0][0]
        bx = page_mcid_boxes(pages[pg], cache)
        tops = [bx[m].y1 for (p, m) in lv if m in bx and bx[m].valid]
        return (pg, -max(tops) if tops else 0.0)

    def walk_leaves(node, cur, out):
        if isinstance(node, Array):
            for k in node:
                walk_leaves(k, cur, out)
            return
        if isinstance(node, int):
            if cur is not None:
                out.append((cur, int(node)))
            return
        if not isinstance(node, Dictionary):
            return
        if node.get("/Type") == Name("/MCR"):
            pg = node.get("/Pg")
            pi = pidx.get(pg.objgen) if pg is not None else cur
            if pi is not None:
                out.append((pi, int(node.get("/MCID"))))
            return
        if node.get("/Type") == Name("/OBJR"):
            return
        pg = node.get("/Pg")
        nxt = pidx.get(pg.objgen) if pg is not None else cur
        walk_leaves(node.get("/K"), nxt, out)

    cache = {}
    attached, artifacted = [], {}
    for i, page in enumerate(pages):
        boxes = page_mcid_boxes(page, cache)
        cm = _content_mcids(page)
        om = {m for (p, m) in owners if p == i}
        for m in sorted(cm - om):
            b = boxes.get(m)
            if b is not None and b.chars > 0:
                para = pdf.make_indirect(Dictionary(
                    Type=Name("/StructElem"), S=Name("/P"),
                    Pg=page.obj, P=doc, K=Array([m])))
                key = (i, -b.y1)
                kids = list(blocks)
                pos = len(kids)
                for j, el in enumerate(kids):
                    if block_key(el) > key:
                        pos = j
                        break
                kids.insert(pos, para)
                doc["/K"] = Array(kids)
                blocks = doc["/K"]
                attached.append((i + 1, m, b.text.strip()[:30]))
            else:
                artifacted.setdefault(i, set()).add(m)

    n = 0
    for pi, mcids in artifacted.items():
        n += artifact_mcids(pdf, pages[pi], mcids)

    # PDF/UA: every single-page <Figure> needs /A /Layout /BBox
    allboxes = {}
    for i, page in enumerate(pages):
        for m, b in page_mcid_boxes(page, cache).items():
            allboxes[(i, m)] = b
    n_bbox = add_figure_bboxes(pdf, allboxes)

    fix_struct_parents(pdf)
    rebuild_parent_tree(pdf)
    pdf.save(outp)
    pdf.close()   # Windows: os.replace() is denied while the file is still open

    if report:
        print(f"orphans attached to <P> : {len(attached)}")
        for p, m, t in attached:
            print(f"    p{p:<3} mcid={m:<4} {t!r}")
        print(f"orphans artifacted      : {sum(len(v) for v in artifacted.values())} "
              f"({n} MC re-marked)")
        print(f"Figure /BBox added      : {n_bbox}")
    print(f"saved {outp}")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    run(a[0], a[1], report="--report" in sys.argv)
