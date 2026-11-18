#!/usr/bin/env python3
"""
heading_eligibility_filter.py
=============================
Post-pass for heading_normalizer.py.  Runs AFTER it, on the tagged PDF.

The defect this solves
----------------------
heading_normalizer assigns levels from TYPOGRAPHY (size rank).  That is fine
for what it does, but it has no notion of *eligibility* - anything visually
distinct becomes a heading.  In G6_CB_SCIENCE_Ch02 that produced:

    H2 "Communication" / H2 "Critical" / H2 "Thinking" / H2 "Logical" ...
        -> decorative competency badges in the page margin (6pt)
    H2 "__________" x8
        -> the blank answer rules in a fill-in-the-blanks table
    H2 "Examples:"  H3 "Objective:"  H5 "Reason (R):"  H5 "Questions"
        -> bold run-in labels that share a baseline with their own body text
    H4 "1." + H5 "Herbs"
        -> one heading split into two (label and title)
    H4 "A habitat provides living organisms with food, water, air, shelter..."
        -> a body paragraph
    H1 "Introduction", chapter title = H2
        -> the real document title is not H1

None of this is a PDF/UA violation, so PAC is green while heading navigation is
unusable.

Eligibility rules (a candidate must survive ALL of them)
-------------------------------------------------------
E1  non-empty, and not only rule characters (_ . - space)
E2  not a bare enumerator ("1.", "(a)", "iv.")
E3  not longer than MAX_HEADING_CHARS (body copy)
E4  not a run-in label: rejected if another element starts on the SAME baseline
    to its right (that is what "Examples: Mint, coriander, tomato." is).  This
    is geometric, not a keyword list, so it generalises.
E5  typographically prominent: effective size > body size, or bold.  Kills the
    6pt margin badges that heading_normalizer promoted.

Then:
  MERGE   a surviving enumerator heading ("1.") is folded into the heading that
          follows it on the same baseline, so "1." + "Herbs" -> one heading.
  RELEVEL levels re-derived from the surviving style ranks: largest style = H1,
          next = H2 ... no skipped levels, exactly one H1 where possible.

Demotion = /S changed to /P.  Nothing is deleted, no MCID is orphaned, the
ParentTree is untouched -> PAC stays green.

Usage
-----
    python heading_eligibility_filter.py in.pdf out.pdf [--report]
"""
from __future__ import annotations

import re
import sys
import collections

import pikepdf
from pikepdf import Dictionary, Name, Array

try:
    from .mcid_geometry import document_mcid_boxes
    from .struct_utils import fix_struct_parents, rebuild_parent_tree
except ImportError:
    from mcid_geometry import document_mcid_boxes
    from struct_utils import fix_struct_parents, rebuild_parent_tree

MAX_HEADING_CHARS = 110
BASELINE_TOL = 4.0          # pt: same-line test
SIZE_TOL = 1.02             # heading must beat body size by 2%
MIN_SIZE_RATIO = 0.92       # below this x body size it is a badge/caption, never a heading
SIZE_CLUSTER = 1.2          # pt: sizes within this are one style

RE_RULE = re.compile(r"^[\s_\.\-–—·•]+$")
RE_ENUM = re.compile(r"^\(?\s*(\d{1,2}|[ivxIVX]{1,4}|[a-zA-Z])\s*[\.\)]?\s*$")


class H:
    __slots__ = ("obj", "parent", "slot", "page", "text", "size", "bold",
                 "top", "left", "right", "level")

    def __init__(self, obj, parent, slot, page, text, size, bold, top, left, right, level):
        self.obj, self.parent, self.slot = obj, parent, slot
        self.page, self.text, self.size, self.bold = page, text, size, bold
        self.top, self.left, self.right, self.level = top, left, right, level


def _pidx(pdf):
    return {p.obj.objgen: i for i, p in enumerate(pdf.pages)}


def _leaves(node, pidx, cur, out):
    if isinstance(node, Array):
        for k in node:
            _leaves(k, pidx, cur, out)
        return
    if isinstance(node, int):
        if cur is not None:
            out.append((cur, int(node)))
        return
    if not isinstance(node, Dictionary):
        return
    t = node.get("/Type")
    if t == Name("/MCR"):
        pg = node.get("/Pg")
        pi = pidx.get(pg.objgen) if pg is not None else cur
        if pi is not None:
            out.append((pi, int(node.get("/MCID"))))
        return
    if t == Name("/OBJR"):
        return
    pg = node.get("/Pg")
    nxt = pidx.get(pg.objgen) if pg is not None else cur
    _leaves(node.get("/K"), pidx, nxt, out)


def _metrics(node, pidx, boxes):
    lv = []
    _leaves(node, pidx, None, lv)
    bl = [boxes[k] for k in lv if k in boxes and boxes[k].valid]
    if not bl:
        return None
    page = lv[0][0]
    text = "".join(b.text for b in bl).strip()
    sizes = [s for b in bl for s in b.sizes]
    fonts = [f for b in bl for f in b.fonts]
    size = max(sizes) if sizes else 0.0
    bold = any(("bold" in f.lower() or "black" in f.lower() or "heavy" in f.lower()) for f in fonts)
    return H(node, None, None, page, text, size, bold,
             max(b.y1 for b in bl), min(b.x0 for b in bl), max(b.x1 for b in bl), None)


def run(inp, outp, report=False):
    pdf = pikepdf.open(inp)
    pidx = _pidx(pdf)
    boxes = document_mcid_boxes(pdf)

    # ---- inventory every element, remember parent+slot so we can merge/demote
    heads, others = [], []

    def visit(node, parent, slot):
        if isinstance(node, Array):
            for i, k in enumerate(node):
                visit(k, node, i)
            return
        if not isinstance(node, Dictionary):
            return
        if node.get("/Type") in (Name("/MCR"), Name("/OBJR")):
            return
        s = node.get("/S")
        if s is not None:
            tag = str(s)
            m = _metrics(node, pidx, boxes)
            if m is not None:
                m.parent, m.slot = parent, slot
                lm = re.match(r"^/H([1-6])$", tag)
                if lm:
                    m.level = int(lm.group(1))
                    heads.append(m)
                else:
                    others.append(m)
        visit(node.get("/K"), node, None)

    visit(pdf.Root["/StructTreeRoot"].get("/K"), None, None)

    # ---- body size = modal size of non-heading text
    sizes = collections.Counter(round(o.size) for o in others if len(o.text) > 40)
    body = sizes.most_common(1)[0][0] if sizes else 10

    # ---- same-baseline index, used by E4
    line = collections.defaultdict(list)
    for o in others + heads:
        line[(o.page, round(o.top / BASELINE_TOL))].append(o)

    head_ids = {id(x) for x in heads}

    def has_text_to_right(h):
        """Run-in label test: real body text starting to the right, same baseline."""
        for o in line.get((h.page, round(h.top / BASELINE_TOL)), []):
            if o is h or id(o) in head_ids:
                continue
            if o.left > h.left + 3 and len(o.text.strip()) >= 8:
                return True
        return False

    demoted, merged = [], []
    survivors = []
    for h in heads:
        why = None
        if not h.text or RE_RULE.match(h.text):
            why = "E1 empty/rule-only"
        elif RE_ENUM.match(h.text):
            why = "E2 enumerator"          # may be rescued by MERGE below
        elif len(h.text) > MAX_HEADING_CHARS:
            why = "E3 body copy"
        elif has_text_to_right(h):
            why = "E4 run-in label"
        elif h.size < body * MIN_SIZE_RATIO:
            why = "E6 sub-body (badge/caption)"
        elif h.size <= body * SIZE_TOL and not h.bold:
            why = "E5 not prominent"
        if why:
            demoted.append((h, why))
        else:
            survivors.append(h)

    # ---- MERGE: "1." + "Herbs" on the same baseline -> one heading
    surv_by_line = collections.defaultdict(list)
    for h in survivors:
        surv_by_line[(h.page, round(h.top / BASELINE_TOL))].append(h)
    rescued = []
    for h, why in list(demoted):
        if why != "E2 enumerator":
            continue
        mates = [m for m in surv_by_line.get((h.page, round(h.top / BASELINE_TOL)), [])
                 if m.left > h.left]
        if not mates:
            continue
        target = min(mates, key=lambda m: m.left)
        hk = h.obj.get("/K")
        tk = target.obj.get("/K")
        items = list(hk) if isinstance(hk, Array) else [hk]
        titems = list(tk) if isinstance(tk, Array) else [tk]
        target.obj["/K"] = Array(items + titems)
        h.obj["/S"] = Name("/NonStruct")     # emptied shell, keeps ParentTree valid
        h.obj["/K"] = Array([])
        merged.append((h.text, target.text))
        rescued.append(h)
    demoted = [(h, w) for h, w in demoted if h not in rescued]

    # ---- demote
    for h, _ in demoted:
        h.obj["/S"] = Name("/P")

    # ---- RELEVEL by style rank
    uniq = sorted({round(h.size, 1) for h in survivors}, reverse=True)
    clusters = []                       # merge sizes that are within SIZE_CLUSTER pt
    for s in uniq:
        if clusters and clusters[-1][0] - s <= SIZE_CLUSTER:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    level_of = {}
    for i, c in enumerate(clusters):
        for s in c:
            level_of[s] = min(i + 1, 6)
    for h in survivors:
        h.level = level_of[round(h.size, 1)]

    # PDF/UA forbids skipped levels IN SEQUENCE (H1 -> H3).  A style rank can
    # still produce one, so clamp in reading order: level <= previous + 1.
    prev = 0
    for h in sorted(survivors, key=lambda h: (h.page, -h.top, h.left)):
        if prev and h.level > prev + 1:
            h.level = prev + 1
        h.obj["/S"] = Name(f"/H{h.level}")
        prev = h.level

    # ---- drop the emptied shells left behind by MERGE (no empty tags in output)
    def prune(node):
        if not isinstance(node, Dictionary):
            return
        k = node.get("/K")
        if isinstance(k, Array):
            keep = []
            for c in k:
                if (isinstance(c, Dictionary) and c.get("/S") == Name("/NonStruct")
                        and isinstance(c.get("/K"), Array) and len(c["/K"]) == 0):
                    continue
                keep.append(c)
                prune(c)
            node["/K"] = Array(keep)
        elif isinstance(k, Dictionary):
            prune(k)

    root_k = pdf.Root["/StructTreeRoot"].get("/K")
    if isinstance(root_k, Array):
        for c in root_k:
            prune(c)
    else:
        prune(root_k)

    fix_struct_parents(pdf)
    rebuild_parent_tree(pdf)
    pdf.save(outp)
    pdf.close()   # Windows: os.replace() is denied while the file is still open

    if report:
        print(f"body size      : {body}pt")
        print(f"headings in    : {len(heads)}")
        print(f"demoted to <P> : {len(demoted)}")
        for h, w in demoted[:25]:
            print(f"    p{h.page+1:<3} {w:<20} {h.text[:52]!r}")
        print(f"merged Lbl+H   : {len(merged)}")
        for a, b in merged[:10]:
            print(f"    {a!r} + {b!r}")
        out = collections.Counter(h.level for h in survivors)
        print(f"headings out   : {len(survivors)}  levels={dict(sorted(out.items()))}")
        print("outline:")
        for h in sorted(survivors, key=lambda h: (h.page, -h.top))[:30]:
            print(f"    p{h.page+1:<3} {'  ' * (h.level-1)}H{h.level} {h.text[:48]!r}")
    print(f"saved {outp}")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    run(a[0], a[1], report="--report" in sys.argv)
