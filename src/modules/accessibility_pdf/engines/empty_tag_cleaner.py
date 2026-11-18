#!/usr/bin/env python3
"""
empty_tag_cleaner.py

Removes structure elements that contain nothing — empty <P>, empty <Span>,
empty <H*>, and similar shells left behind by tagging and by earlier
remediation passes.

Why
---
An empty tag is not a hard PDF/UA failure, but QA flags it ("Empty P tags —
found throughout the document") and it degrades the experience: a screen
reader may announce a paragraph that has no content, and the tag tree is
harder for a human reviewer to audit.  These shells accumulate when content is
re-parented, artifacted, or merged by earlier fixers.

An element is EMPTY when, after resolving its subtree, it has:
  * no MCID / MCR that paints any non-whitespace glyph, and
  * no OBJR (annotation reference), and
  * no non-empty descendant element.

Never removed
-------------
  * <Figure>, <Formula> — legitimately have no text; they carry /Alt.
  * Any element with /Alt or /ActualText — it supplies its own accessible text.
  * <Link> with an /OBJR — the annotation is real content even with no text
    (link_text_fixer is what gives those their text; deleting them would
    destroy working links).
  * <TD> / <TH> — an empty cell is a structurally required placeholder in a
    table grid; removing it corrupts the row/column geometry.
  * <Document>, <Part>, <Sect> and other roots — containers may legitimately
    be empty at the moment of a pass.

Removal is iterated to a fixed point, so a parent that becomes empty once its
only (empty) child is deleted is itself removed.

Usage
-----
    python3 empty_tag_cleaner.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

import pikepdf
from pikepdf import Array

_WS = set(b" \t\r\n\x00\x0c")

# never delete these, even when they hold no glyphs
_PROTECTED = {
    "/Figure", "/Formula",          # carry /Alt instead of text
    "/TD", "/TH",                   # table grid placeholders
    "/Document", "/Part", "/Art", "/Sect", "/Div",
    "/Table", "/TR", "/L", "/LI", "/LBody",
}


def _op(i) -> str:
    try:
        return str(i.operator)
    except Exception:
        return "?"


def _klist(k):
    if k is None:
        return []
    return list(k) if isinstance(k, pikepdf.Array) else [k]


def _kids(e):
    return _klist(e.get("/K"))


def _stype(e) -> str:
    s = e.get("/S")
    return str(s) if s is not None else ""


def _mcid_text_map(pdf):
    """(page_index, mcid) -> bytes painted."""
    out = {}
    for pi, page in enumerate(pdf.pages):
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue
        stack = []
        for ins in instrs:
            o = _op(ins)
            if o == "BDC":
                m = None
                try:
                    ops = ins.operands
                    if len(ops) >= 2 and isinstance(ops[1], pikepdf.Dictionary) \
                            and "/MCID" in ops[1]:
                        m = int(ops[1]["/MCID"])
                except Exception:
                    m = None
                stack.append(m)
            elif o == "BMC":
                stack.append(None)
            elif o == "EMC":
                if stack:
                    stack.pop()
            elif o in ("Tj", "TJ", "'", '"'):
                cur = next((x for x in reversed(stack) if x is not None), None)
                if cur is None:
                    continue
                raw = b""
                try:
                    if o == "TJ":
                        for e in ins.operands[0]:
                            if isinstance(e, pikepdf.String):
                                raw += bytes(e)
                    else:
                        s = ins.operands[-1]
                        if isinstance(s, pikepdf.String):
                            raw += bytes(s)
                except Exception:
                    pass
                out[(pi, cur)] = out.get((pi, cur), b"") + raw
    return out


def clean_empty_tags(in_path: str, out_path: str) -> dict:
    res = {"removed": 0, "by_type": {}, "passes": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("empty_tag_cleaner: no StructTreeRoot; copied through")
        return res

    page_index = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    mt = _mcid_text_map(pdf)
    removed = Counter()

    # Whitespace-only sequences (a <P> whose MCID paints just a space) LOOK
    # empty, and QA flags them.  But simply deleting the element leaves its
    # marked-content unclaimed by the structure tree, which a checker then
    # reports as untagged content — trading one defect for another.  Removing
    # them correctly requires also artifacting the sequence, so by default we
    # only delete elements that reference NO content at all (structurally
    # empty shells), which is always safe.  Set ORION_EMPTY_TAG_AGGRESSIVE=1
    # to also drop whitespace-only elements.
    aggressive = os.environ.get("ORION_EMPTY_TAG_AGGRESSIVE", "") == "1"

    def has_content(elem, pi_inherited):
        """True if elem references any content, holds an annotation, or has a
        non-empty descendant."""
        pg = elem.get("/Pg")
        pi = page_index.get(pg.objgen) if pg is not None else pi_inherited

        if elem.get("/Alt") is not None or elem.get("/ActualText") is not None:
            return True

        for c in _kids(elem):
            if isinstance(c, pikepdf.Dictionary):
                t = str(c.get("/Type", ""))
                if t == "/OBJR":
                    return True            # a real annotation
                if t == "/MCR":
                    try:
                        m = int(c["/MCID"])
                    except Exception:
                        continue
                    cpg = c.get("/Pg")
                    cpi = page_index.get(cpg.objgen) if cpg is not None else pi
                    raw = mt.get((cpi, m), b"")
                    if any(ch not in _WS for ch in raw):
                        return True
                    if not aggressive and (cpi, m) in mt:
                        return True      # whitespace-only, but real content
                elif "/S" in c:
                    if has_content(c, pi):
                        return True
            else:
                try:
                    m = int(c)
                except Exception:
                    continue
                raw = mt.get((pi, m), b"")
                if any(ch not in _WS for ch in raw):
                    return True
                if not aggressive and (pi, m) in mt:
                    return True          # whitespace-only, but real content
        return False

    changed = True
    while changed and res["passes"] < 5:
        changed = False
        res["passes"] += 1

        def prune(node, pi_inherited):
            nonlocal changed
            pg = node.get("/Pg")
            pi = page_index.get(pg.objgen) if pg is not None else pi_inherited

            k = node.get("/K")
            if k is None:
                return
            kids = _klist(k)
            keep = []
            for c in kids:
                if isinstance(c, pikepdf.Dictionary) and "/S" in c:
                    s = _stype(c)
                    if s not in _PROTECTED and not has_content(c, pi):
                        removed[s] += 1
                        res["removed"] += 1
                        changed = True
                        continue          # drop it
                    prune(c, pi)
                keep.append(c)
            if len(keep) != len(kids):
                node["/K"] = Array(keep)

        prune(st, None)

    res["by_type"] = dict(removed)
    res["mode"] = "aggressive" if aggressive else "conservative"
    pdf.save(out_path)
    print(f"empty_tag_cleaner: [{res['mode']}] removed {res['removed']} empty "
          f"element(s) in {res['passes']} pass(es); "
          f"by type: {res['by_type'] or 'none'}")
    return res


def main(argv):
    if len(argv) < 3:
        print("Usage: empty_tag_cleaner.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        r = clean_empty_tags(argv[1], argv[2])
        print(json.dumps(r))
        return 0
    except Exception as exc:
        import traceback
        print(f"empty_tag_cleaner: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
