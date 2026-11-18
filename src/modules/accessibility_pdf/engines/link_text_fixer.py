#!/usr/bin/env python3
"""
link_text_fixer.py

Gives empty <Link> structure elements their visible text, so a screen reader
announces "link, HB 2108" instead of an anonymous, unusable link.

The problem
-----------
PDFix associates a Link annotation with a <Link> structure element (via /OBJR)
but frequently fails to put the LINK TEXT inside that element:

    <Link>
      /OBJR -> annotation (Rect, URI)      <- the clickable box
      (no MCID)                            <- no text!

The text ("HB 2108") is still painted on the page, but it lives inside the
surrounding paragraph's marked-content sequence.  Assistive technology
therefore reads a link with no accessible name.  Automated checkers do NOT
flag this (the /OBJR is present and PDF/UA is satisfied), which is exactly the
class of defect that only a manual/screen-reader review catches.

The fix
-------
For each <Link> that has an annotation but no content:

  1. Take the annotation's /Rect.
  2. Find the text-showing operators on that page whose drawing origin falls
     inside the Rect.  These are the glyphs the user sees as the link.
  3. Split the enclosing marked-content sequence in three:

         /P <</MCID orig>> BDC   [text before the link]   EMC
         /Link <</MCID new_a>> BDC   [the link text]      EMC
         /P <</MCID new_b>> BDC  [text after the link]    EMC

     (leading/trailing parts are omitted when empty).
  4. Point the <Link> element at new_a, give the remainder new_b, and wire both
     into the page's ParentTree.  The <Link> is placed in its parent's /K
     between the two remainders so reading order is preserved.

Only sequences where the link glyphs form a CONTIGUOUS operator run inside a
SINGLE marked-content sequence are touched.  Anything ambiguous (glyphs
spanning two sequences, no glyphs found, rect matching nothing) is skipped and
reported, rather than guessed at — a wrong split would corrupt reading order,
which is worse than the empty link it replaces.

Usage
-----
    python3 link_text_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import math
import sys

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator
from pikepdf import ContentStreamInstruction as CSI

_TEXT_OPS = {"Tj", "TJ", "'", '"'}
_WS = set(b" \t\r\n\x00\x0c")
_PAD = 1.0            # rect tolerance in points
_RIGHT_MARGIN = 3.0   # keep clear of the rect's right edge (see below)


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


def _glyph_bytes(ins) -> bytes:
    o = _op(ins)
    out = b""
    try:
        if o == "TJ":
            for e in ins.operands[0]:
                if isinstance(e, pikepdf.String):
                    out += bytes(e)
        elif o in ("Tj", "'", '"'):
            s = ins.operands[-1]
            if isinstance(s, pikepdf.String):
                out += bytes(s)
    except Exception:
        pass
    return out


def _has_glyph(b: bytes) -> bool:
    return any(c not in _WS for c in b)


def _mcid_of_bdc(ins):
    try:
        ops = ins.operands
        if len(ops) >= 2 and isinstance(ops[1], pikepdf.Dictionary) \
                and "/MCID" in ops[1]:
            return int(ops[1]["/MCID"])
    except Exception:
        pass
    return None


def _scan_page_ops(page):
    """Return (instrs, ops) where ops = list of dicts for each text-showing op:
    {i, x, y, mcid, bdc, emc, text}.  bdc/emc are the indices of the enclosing
    marked-content sequence (or None if not inside one)."""
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return [], []

    # first pass: match BDC/BMC -> EMC
    partner = {}
    stack = []
    for i, ins in enumerate(instrs):
        o = _op(ins)
        if o in ("BDC", "BMC"):
            stack.append(i)
        elif o == "EMC":
            if stack:
                b = stack.pop()
                partner[b] = i

    ops = []
    mc = []            # stack of (bdc_index, mcid)
    tm = None
    tlm = None
    tf = 1.0
    tms = 1.0
    for i, ins in enumerate(instrs):
        o = _op(ins)
        if o in ("BDC", "BMC"):
            mc.append((i, _mcid_of_bdc(ins) if o == "BDC" else None))
        elif o == "EMC":
            if mc:
                mc.pop()
        elif o == "Tf":
            try:
                tf = float(ins.operands[1])
            except Exception:
                pass
        elif o == "Tm":
            try:
                a, b, c, d, e, f = [float(x) for x in ins.operands[:6]]
                tm = (a, b, c, d, e, f)
                tlm = tm
                tms = math.sqrt(abs(a * d - b * c)) or 1.0
            except Exception:
                pass
        elif o == "BT":
            tm = tlm = (1, 0, 0, 1, 0, 0)
        elif o in ("Td", "TD"):
            try:
                tx, ty = float(ins.operands[0]), float(ins.operands[1])
                if tlm:
                    a, b, c, d, e, f = tlm
                    tlm = (a, b, c, d,
                           e + tx * a + ty * c, f + tx * b + ty * d)
                    tm = tlm
            except Exception:
                pass
        elif o == "T*":
            pass
        elif o in _TEXT_OPS:
            if tm is None:
                continue
            cur = None
            bdc = None
            for bi, m in reversed(mc):
                if m is not None:
                    cur, bdc = m, bi
                    break
            raw = _glyph_bytes(ins)
            ops.append({
                "i": i, "x": tm[4], "y": tm[5], "size": tf * tms,
                "mcid": cur, "bdc": bdc,
                "emc": partner.get(bdc) if bdc is not None else None,
                "text": raw,
            })
    return instrs, ops


def fix_link_text(in_path: str, out_path: str) -> dict:
    res = {"links_total": 0, "links_empty": 0, "links_fixed": 0,
           "skipped_no_match": 0, "skipped_ambiguous": 0, "pages_changed": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("link_text_fixer: no StructTreeRoot; copied through")
        return res

    page_index = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}

    # ---- collect empty <Link> elements with their parent -------------------
    empties = []       # (link_elem, parent_elem, annot_obj)
    seen = set()

    def walk(node):
        for c in _kids(node):
            if not isinstance(c, pikepdf.Dictionary) or "/S" not in c:
                continue
            key = c.objgen if c.is_indirect else id(c)
            if key in seen:
                continue
            seen.add(key)
            if _stype(c) == "/Link":
                res["links_total"] += 1
                has_mcid = any(not isinstance(x, pikepdf.Dictionary)
                               for x in _kids(c))
                has_mcr = any(isinstance(x, pikepdf.Dictionary)
                              and str(x.get("/Type", "")) == "/MCR"
                              for x in _kids(c))
                annot = None
                for x in _kids(c):
                    if isinstance(x, pikepdf.Dictionary) \
                            and str(x.get("/Type", "")) == "/OBJR":
                        annot = x.get("/Obj")
                if not has_mcid and not has_mcr:
                    res["links_empty"] += 1
                    if annot is not None:
                        empties.append((c, node, annot))
            walk(c)

    walk(st)

    if not empties:
        pdf.save(out_path)
        print("link_text_fixer: no empty <Link> elements; copied through")
        return res

    # group by page
    by_page = {}
    for link, parent, annot in empties:
        pg = link.get("/Pg") or annot.get("/P")
        if pg is None:
            res["skipped_no_match"] += 1
            continue
        pi = page_index.get(pg.objgen)
        if pi is None:
            res["skipped_no_match"] += 1
            continue
        by_page.setdefault(pi, []).append((link, parent, annot))

    pt = st.get("/ParentTree")

    for pi, items in by_page.items():
        page = pdf.pages[pi]
        instrs, ops = _scan_page_ops(page)
        if not instrs:
            continue

        max_mcid = -1
        for ins in instrs:
            if _op(ins) == "BDC":
                m = _mcid_of_bdc(ins)
                if m is not None:
                    max_mcid = max(max_mcid, m)

        # plan the splits: bdc_index -> list of (first_op_i, last_op_i, link)
        plans = []
        for link, parent, annot in items:
            try:
                r = [float(x) for x in annot.get("/Rect")]
            except Exception:
                res["skipped_no_match"] += 1
                continue
            x0, y0, x1, y1 = min(r[0], r[2]), min(r[1], r[3]), \
                max(r[0], r[2]), max(r[1], r[3])

            hits = [o for o in ops
                    if o["mcid"] is not None
                    and _has_glyph(o["text"])
                    # Require the glyph run to START well inside the rect.
                    # The rect's right edge usually sits a point or two past
                    # the last link glyph, so a loose bound swallows the next
                    # run ("SB 166" + "- Elections omnibus...").
                    and x0 - _PAD <= o["x"] <= x1 - _RIGHT_MARGIN
                    and y0 - _PAD <= o["y"] <= y1 + _PAD]
            if not hits:
                res["skipped_no_match"] += 1
                continue
            bdcs = {o["bdc"] for o in hits}
            if len(bdcs) != 1:
                # glyphs straddle two marked-content sequences: too risky
                res["skipped_ambiguous"] += 1
                continue
            bdc = hits[0]["bdc"]
            emc = hits[0]["emc"]
            if bdc is None or emc is None:
                res["skipped_ambiguous"] += 1
                continue
            first = min(o["i"] for o in hits)
            last = max(o["i"] for o in hits)
            plans.append({"bdc": bdc, "emc": emc, "first": first,
                          "last": last, "link": link, "parent": parent,
                          "mcid": hits[0]["mcid"]})

        if not plans:
            continue

        # one split per marked-content sequence (skip duplicates on same seq)
        used_bdc = set()
        plans2 = []
        for p in sorted(plans, key=lambda z: z["first"]):
            if p["bdc"] in used_bdc:
                res["skipped_ambiguous"] += 1
                continue
            used_bdc.add(p["bdc"])
            plans2.append(p)

        # rebuild the content stream
        new_instrs = []
        plan_by_bdc = {p["bdc"]: p for p in plans2}
        i = 0
        n = len(instrs)
        alloc = max_mcid + 1
        applied = []

        while i < n:
            if i in plan_by_bdc:
                p = plan_by_bdc[i]
                bdc_ins = instrs[i]
                orig_mcid = p["mcid"]
                tag = "/P"
                try:
                    tag = str(bdc_ins.operands[0])
                except Exception:
                    pass

                head = instrs[i + 1:p["first"]]
                body = instrs[p["first"]:p["last"] + 1]
                tail = instrs[p["last"] + 1:p["emc"]]

                head_has_text = any(_op(x) in _TEXT_OPS and _has_glyph(_glyph_bytes(x))
                                    for x in head)
                tail_has_text = any(_op(x) in _TEXT_OPS and _has_glyph(_glyph_bytes(x))
                                    for x in tail)

                link_mcid = alloc
                alloc += 1
                tail_mcid = None

                # head keeps the original MCID (if it still shows text);
                # otherwise the head is emitted without a sequence.
                if head_has_text:
                    new_instrs.append(bdc_ins)
                    new_instrs.extend(head)
                    new_instrs.append(CSI([], Operator("EMC")))
                else:
                    new_instrs.extend(head)

                new_instrs.append(CSI(
                    [Name("/Link"), Dictionary(MCID=link_mcid)],
                    Operator("BDC")))
                new_instrs.extend(body)
                new_instrs.append(CSI([], Operator("EMC")))

                if tail_has_text:
                    tail_mcid = alloc
                    alloc += 1
                    new_instrs.append(CSI(
                        [Name(tag), Dictionary(MCID=tail_mcid)],
                        Operator("BDC")))
                    new_instrs.extend(tail)
                    new_instrs.append(CSI([], Operator("EMC")))
                else:
                    new_instrs.extend(tail)

                applied.append({
                    "link": p["link"], "parent": p["parent"],
                    "orig_mcid": orig_mcid if head_has_text else None,
                    "dead_mcid": None if head_has_text else orig_mcid,
                    "link_mcid": link_mcid, "tail_mcid": tail_mcid,
                })
                i = p["emc"] + 1
                continue

            new_instrs.append(instrs[i])
            i += 1

        if not applied:
            continue

        page.Contents = pdf.make_stream(
            pikepdf.unparse_content_stream(new_instrs))
        res["pages_changed"] += 1

        # ---- structure tree + ParentTree ---------------------------------
        sp = page.obj.get("/StructParents")
        key = int(sp) if sp is not None else pi
        arr = None
        if pt is not None and "/Nums" in pt:
            nums = list(pt["/Nums"])
            for j in range(0, len(nums) - 1, 2):
                if int(nums[j]) == key and isinstance(nums[j + 1], pikepdf.Array):
                    arr = nums[j + 1]
                    break

        for a in applied:
            link, parent = a["link"], a["parent"]
            link["/K"] = Array([x for x in _kids(link)
                                if isinstance(x, pikepdf.Dictionary)]
                               + [a["link_mcid"]])
            # keep OBJR first, then the MCID (order inside <Link> is fine)
            link["/Pg"] = page.obj

            # rebuild parent's /K: place <Link> right after the head MCID,
            # then the tail MCID, preserving everything else in order.
            # `dead_mcid` is the sequence's original MCID when the head half
            # had no text: in that case no BDC was emitted for it, so the MCID
            # no longer exists in the content stream.  It MUST be dropped from
            # the parent's /K, otherwise the element points at a marked-content
            # sequence that isn't there — a dangling reference PAC reports
            # under "Structure Elements".
            dead_mcid = a["dead_mcid"]

            new_k = []
            inserted = False
            for x in _kids(parent):
                is_link = (isinstance(x, pikepdf.Dictionary) and x.is_indirect
                           and link.is_indirect and x.objgen == link.objgen)
                if is_link:
                    continue                    # will be re-inserted in place
                if dead_mcid is not None and not isinstance(x, pikepdf.Dictionary):
                    try:
                        if int(x) == dead_mcid:
                            # drop the phantom, and put the link where it was
                            new_k.append(link)
                            if a["tail_mcid"] is not None:
                                new_k.append(a["tail_mcid"])
                            inserted = True
                            continue
                    except Exception:
                        pass
                new_k.append(x)
                if (not inserted and a["orig_mcid"] is not None
                        and not isinstance(x, pikepdf.Dictionary)):
                    try:
                        if int(x) == a["orig_mcid"]:
                            new_k.append(link)
                            if a["tail_mcid"] is not None:
                                new_k.append(a["tail_mcid"])
                            inserted = True
                    except Exception:
                        pass
            if not inserted:
                new_k.append(link)
                if a["tail_mcid"] is not None:
                    new_k.append(a["tail_mcid"])
            parent["/K"] = Array(new_k)

            if arr is not None:
                need = max(a["link_mcid"],
                           a["tail_mcid"] if a["tail_mcid"] is not None else 0)
                while len(arr) <= need:
                    arr.append(pikepdf.Object.parse(b"null"))
                arr[a["link_mcid"]] = link
                if a["tail_mcid"] is not None:
                    arr[a["tail_mcid"]] = parent

            res["links_fixed"] += 1

    pdf.save(out_path)
    print(f"link_text_fixer: {res['links_total']} <Link>; "
          f"{res['links_empty']} empty; fixed {res['links_fixed']}; "
          f"skipped {res['skipped_no_match']} no-match / "
          f"{res['skipped_ambiguous']} ambiguous; "
          f"{res['pages_changed']} page(s) changed")
    return res


def main(argv):
    if len(argv) < 3:
        print("Usage: link_text_fixer.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        r = fix_link_text(argv[1], argv[2])
        print(json.dumps(r))
        return 0
    except Exception as exc:
        import traceback
        print(f"link_text_fixer: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
