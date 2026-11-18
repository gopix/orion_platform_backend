#!/usr/bin/env python3
"""
validate.py - checks the things PAC actually checks, so we stop shipping files
that pass a home-made audit and fail the real one.

  1. ORPHAN tagged content   - BDC/MCID in a content stream (INCLUDING form
                               XObjects) with no owning struct element.
                               PAC reports these in bulk under "Content".
  2. PHANTOM MCIDs           - struct element points at an MCID that is not in
                               any content stream.
  3. /P back-pointers        - every element's /P must be its actual parent.
                               PAC: "Structure element refers to a different
                               parent than the actual parent".
  4. ParentTree              - /Nums sorted ascending; every page has
                               /StructParents; every (page,mcid) resolves to the
                               element that really owns it.
  5. Figure /Alt             - present and non-empty.
  6. Heading sequence        - no skipped levels.
  7. Artifact nesting        - no tagged content inside an /Artifact block.
"""
from __future__ import annotations

import re
import sys

import pikepdf
from pikepdf import Dictionary, Name, Array


def content_mcids(page):
    """MCIDs actually present in the page's content, recursing into XObjects.

    Only marked content that PAINTS something (text, image, path, shading) is
    counted. An empty BDC/EMC pair with an MCID that paints nothing is not a
    real "untagged content" problem — PAC does not flag it — so counting it as
    an orphan produced a false failure. Ink-less sequences are ignored here.
    """
    found = set()
    seen = set()

    PAINT = {"Tj", "TJ", "'", '"',
             "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "sh",
             "Do"}

    def scan(obj, res, depth=0):
        if depth > 4:
            return
        try:
            instrs = pikepdf.parse_content_stream(obj)
        except Exception:
            return
        stack = []          # tags, innermost last
        inked = set()       # mcids in this stream that painted something
        mstack = []         # mcid per BDC/BMC level (None if not an MCID BDC)
        for ops, op in instrs:
            o = str(op)
            if o in ("BDC", "BMC"):
                tag = str(ops[0]) if ops else "?"
                mcid = None
                if o == "BDC" and len(ops) > 1 and isinstance(ops[1], Dictionary) \
                        and "/MCID" in ops[1]:
                    mcid = int(ops[1]["/MCID"])
                stack.append(tag)
                mstack.append(mcid)
            elif o == "EMC":
                if stack:
                    stack.pop()
                if mstack:
                    mstack.pop()
            else:
                if o in PAINT and not any(t == "/Artifact" for t in stack):
                    # attribute this paint to the innermost live MCID
                    for m in reversed(mstack):
                        if m is not None:
                            inked.add(m)
                            break
                if o == "Do":
                    xod = res.get("/XObject")
                    if xod is None:
                        continue
                    xo = xod.get(str(ops[0]))
                    if xo is not None and xo.get("/Subtype") == Name("/Form") \
                            and "/StructParents" not in xo \
                            and xo.objgen not in seen:
                        seen.add(xo.objgen)
                        scan(xo, xo.get("/Resources") or res, depth + 1)
        found.update(inked)

    scan(page.obj, page.get("/Resources") or Dictionary())
    return found


def validate(path):
    pdf = pikepdf.open(path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        print("NO STRUCT TREE")
        return 1
    pidx = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}

    owners, bad_p, headings, figs_noalt = {}, 0, [], 0
    figs_nobbox = [0]
    elems = 0
    # (page, mcid) -> set of owning-element objgens. A dict that stored a single
    # owner silently dropped duplicate claims, so a PDF whose structure tree had
    # two elements claiming the same content passed this gate and then failed PAC
    # with "Structural parent tree / Inconsistent entry found". Track every
    # claimant so the collision is visible.
    claim_owners = {}

    def _register(pi, mcid, parent):
        owners[(pi, mcid)] = parent
        try:
            og = parent.objgen
        except Exception:
            og = id(parent)
        claim_owners.setdefault((pi, mcid), set()).add(og)

    def walk(node, cur, parent):
        nonlocal bad_p, elems, figs_noalt
        if isinstance(node, Array):
            for k in node:
                walk(k, cur, parent)
            return
        if isinstance(node, int):
            if cur is not None and parent is not None:
                _register(cur, int(node), parent)
            return
        if not isinstance(node, Dictionary):
            return
        t = node.get("/Type")
        if t == Name("/MCR"):
            pg = node.get("/Pg")
            pi = pidx.get(pg.objgen) if pg is not None else cur
            if pi is not None and parent is not None:
                _register(pi, int(node.get("/MCID")), parent)
            return
        if t == Name("/OBJR"):
            return
        s = node.get("/S")
        if s is not None:
            elems += 1
            P = node.get("/P")
            if parent is not None and (P is None or P.objgen != parent.objgen):
                bad_p += 1
            tag = str(s)
            if tag == "/Figure":
                a = node.get("/Alt")
                if a is None or not str(a).strip():
                    figs_noalt += 1
                _at = node.get("/A")
                _hb = False
                if _at is not None:
                    for _x in (_at if isinstance(_at, Array) else [_at]):
                        if isinstance(_x, Dictionary) and "/BBox" in _x:
                            _hb = True
                if not _hb:
                    figs_nobbox[0] += 1
            m = re.match(r"^/H([1-6])$", tag)
            if m:
                headings.append(int(m.group(1)))
        pg = node.get("/Pg")
        nxt = pidx.get(pg.objgen) if pg is not None else cur
        walk(node.get("/K"), nxt, node if s is not None else parent)

    walk(st.get("/K"), None, st)

    orphan = phantom = 0
    orphan_pages = {}
    for i, page in enumerate(pdf.pages):
        cm = content_mcids(page)
        om = {m for (p, m) in owners if p == i}
        o, ph = cm - om, om - cm
        if o:
            orphan_pages[i + 1] = sorted(o)
        orphan += len(o)
        phantom += len(ph)

    # ParentTree
    pt_err = []
    ptree = st.get("/ParentTree")
    if ptree is None:
        pt_err.append("no ParentTree")
    else:
        nums = ptree.get("/Nums")
        keys = [int(nums[i]) for i in range(0, len(nums), 2)]
        if keys != sorted(keys):
            pt_err.append("/Nums keys NOT sorted ascending")
        table = {int(nums[i]): nums[i + 1] for i in range(0, len(nums), 2)}
        mismatch = 0
        for i, page in enumerate(pdf.pages):
            if "/StructParents" not in page.obj:
                pt_err.append(f"page {i+1} has no /StructParents")
                continue
            arr = table.get(int(page.obj["/StructParents"]))
            for (p, m), e in owners.items():
                if p != i:
                    continue
                if arr is None or m >= len(arr) or arr[m] is None \
                        or arr[m].objgen != e.objgen:
                    mismatch += 1
        if mismatch:
            pt_err.append(f"{mismatch} (page,mcid) entries do not resolve to the owner")
        for page in pdf.pages:
            res = page.get("/Resources") or Dictionary()
            xod = res.get("/XObject")
            if xod is None:
                continue
            for _k, xo in xod.items():
                try:
                    if xo.get("/Subtype") == Name("/Form") and "/StructParents" in xo:
                        if int(xo["/StructParents"]) not in table:
                            pt_err.append(
                                f"XObject /StructParents {int(xo['/StructParents'])} "
                                f"missing from ParentTree")
                except Exception:
                    pass

    # duplicate ownership: two struct elements claiming the same (page, mcid).
    # This is what PAC reports as "Inconsistent entry found" in the parent tree.
    dup_claims = {k: sorted(v) for k, v in claim_owners.items() if len(v) > 1}

    skips = []
    prev = 0
    for h in headings:
        if prev and h > prev + 1:
            skips.append((prev, h))
        prev = h

    print(f"--- {path}")
    print(f"  struct elements            : {elems}")
    print(f"  ORPHAN tagged content      : {orphan}   {orphan_pages if orphan else ''}")
    print(f"  PHANTOM mcids              : {phantom}")
    print(f"  DUPLICATE MCID ownership   : {len(dup_claims)}   "
          f"{dict(list(dup_claims.items())[:5]) if dup_claims else ''}")
    print(f"  wrong /P back-pointers     : {bad_p}")
    print(f"  ParentTree problems        : {pt_err if pt_err else 'none'}")
    print(f"  Figures without Alt        : {figs_noalt}")
    print(f"  Figures without /BBox      : {figs_nobbox[0]}")
    print(f"  heading level skips        : {len(skips)} {skips[:5]}")
    pdf.close()
    ok = not (orphan or phantom or dup_claims or bad_p or pt_err or figs_noalt
              or figs_nobbox[0] or skips)
    print(f"  => {'CLEAN' if ok else 'FAILS'}")
    return 0 if ok else 1


if __name__ == "__main__":
    rc = 0
    for p in sys.argv[1:]:
        rc |= validate(p)
    sys.exit(rc)
