#!/usr/bin/env python3
"""
list_label_fixer.py

Pulls the bullet glyph out of whatever marked-content sequence swallowed it and
gives it its own <Lbl> structure element.

The problem
-----------
Word emits a list item as two separate marked-content sequences — the bullet in
its own /Lbl, the text in /LBody:

    /Lbl   <</MCID 5>> BDC  ... Tj <bullet> ...  EMC
    /LBody <</MCID 7>> BDC  ... TJ "expanding automatic ..." EMC

PDFix's AddTags() does not reconstruct that split. It emits ONE sequence
containing both, and whichever element claims that sequence absorbs the bullet.
On a typical report the bullets end up distributed like this:

    40 inside /Link      <- the link's accessible name becomes "<bullet>HB 2107"
    11 inside /LBody     <- bullet is read as the first character of the body
     3 inside /P         <- the item never became a list item at all

None of those are recoverable by editing the structure tree alone: there is no
marked content to point a <Lbl> at, because the bullet has no MCID of its own.

Why the split is safe
---------------------
The bullet is always painted in a SYMBOL font (SymbolMT, Wingdings, ZapfDingbats
…) and the body text in a normal text font, so the boundary is a `Tf` font
switch inside the sequence, not a guess about glyph codes:

    /LBody <</MCID 12>> BDC
       Tf /C2_0  -> SymbolMT      <- bullet run
       Tj  '\\x00x'
       Tf /TT1   -> Calibri       <- SPLIT HERE
       TJ  'HB 2108' ...
    EMC

The sequence is rewritten as two, the bullet run getting a fresh MCID under a
/Lbl tag. BDC/EMC are legal inside a BT/ET text object, so the text object is
never broken. Font state is tracked across the whole stream (and through the
q/Q graphics stack), because the `Tf` that selects the bullet font is very often
set BEFORE the BDC rather than inside it.

What it does NOT do
-------------------
Adjacent <L> containers are not merged. A document whose list items were
fragmented across several <L> elements stays fragmented; this pass only fixes
labels and the list items that were never tagged as such.

Usage
-----
    python3 list_label_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import re
import sys

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator
from pikepdf import ContentStreamInstruction as CSI

try:
    from .struct_utils import fix_struct_parents, rebuild_parent_tree
except ImportError:  # executed as a standalone script
    from struct_utils import fix_struct_parents, rebuild_parent_tree  # type: ignore

# Fonts whose glyphs are list bullets rather than words.
_SYMBOL_FONT = re.compile(r"(symbol|wingding|zapf|dingbat|webding|marlett)", re.I)

# A label run is a couple of glyphs at most ("•", "o", "1.", "a)").  Anything
# longer set in a symbol font is decorative text, not a list label.
_MAX_LABEL_BYTES = 8

# Sequences whose leading symbol run we are willing to lift out.  These are the
# only tags a mis-absorbed bullet has ever been observed under.
_HOST_TAGS = {"/Link", "/LBody", "/P", "/Span"}

_TEXT_OPS = {"Tj", "TJ", "'", '"'}


def _op(ins) -> str:
    try:
        return str(ins.operator)
    except Exception:
        return "?"


def _stype(el) -> str:
    try:
        return str(el.get("/S", "")) if "/S" in el else ""
    except Exception:
        return ""


def _kids(el) -> list:
    k = el.get("/K")
    if k is None:
        return []
    return list(k) if isinstance(k, Array) else [k]


def _shown_bytes(operands, o) -> bytes:
    raw = b""
    try:
        if o == "TJ":
            for e in operands[0]:
                if isinstance(e, pikepdf.String):
                    raw += bytes(e)
        else:
            if isinstance(operands[-1], pikepdf.String):
                raw += bytes(operands[-1])
    except Exception:
        pass
    return raw


def _font_map(page) -> dict:
    res = page.obj.get("/Resources")
    fonts = (res.get("/Font") if res is not None else None) or {}
    out = {}
    for k, v in fonts.items():
        try:
            out[str(k)] = str(v.get("/BaseFont", "?"))
        except Exception:
            out[str(k)] = "?"
    return out


# ---------------------------------------------------------------------------
# structure-tree helpers
# ---------------------------------------------------------------------------

def _iter_mcids(k):
    if k is None:
        return
    for c in (list(k) if isinstance(k, Array) else [k]):
        if isinstance(c, Dictionary):
            if str(c.get("/Type", "")) == "/MCR" and "/MCID" in c:
                try:
                    yield int(c["/MCID"])
                except Exception:
                    continue
        else:
            try:
                yield int(c)
            except Exception:
                continue


def _page_index_map(pdf) -> dict:
    return {p.obj.objgen: i for i, p in enumerate(pdf.pages)}


def _claim_map(pdf) -> dict:
    """(page_index, mcid) -> (element, parent_element)."""
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return {}
    pmap = _page_index_map(pdf)
    out: dict = {}
    seen: set = set()

    def walk(node, parent):
        if isinstance(node, Array):
            for x in node:
                walk(x, parent)
            return
        if not isinstance(node, Dictionary):
            return
        if node.is_indirect:
            if node.objgen in seen:
                return
            seen.add(node.objgen)
        pg = node.get("/Pg")
        pi = pmap.get(pg.objgen) if pg is not None else None
        if pi is not None:
            for m in _iter_mcids(node.get("/K")):
                out.setdefault((pi, m), (node, parent))
        walk(node.get("/K"), node)

    walk(st.get("/K"), st)
    return out


def _ancestor_of_type(el, wanted: set, parent_of: dict, limit: int = 8):
    cur = el
    for _ in range(limit):
        cur = parent_of.get(cur.objgen if cur.is_indirect else id(cur))
        if cur is None:
            return None
        if _stype(cur) in wanted:
            return cur
    return None


def _parent_index_map(pdf) -> dict:
    """objgen/id -> parent element, for walking upward."""
    st = pdf.Root.get("/StructTreeRoot")
    out: dict = {}
    seen: set = set()

    def walk(node):
        if isinstance(node, Array):
            for x in node:
                walk(x)
            return
        if not isinstance(node, Dictionary):
            return
        if node.is_indirect:
            if node.objgen in seen:
                return
            seen.add(node.objgen)
        for c in _kids(node):
            if isinstance(c, Dictionary) and "/S" in c:
                out[c.objgen if c.is_indirect else id(c)] = node
                walk(c)

    walk(st.get("/K") if st is not None else None)
    return out


# ---------------------------------------------------------------------------
# pass 1 — find splittable sequences
# ---------------------------------------------------------------------------

def _find_splits(pdf, pi, claims) -> list:
    """Marked-content sequences on page *pi* whose leading run is a bullet.

    Returns [{mcid, open_i, split_i, label_bytes, tag}] where `split_i` is the
    instruction index at which the /Lbl sequence must be closed.
    """
    page = pdf.pages[pi]
    fmap = _font_map(page)
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return []

    out = []
    curfont = None
    gstack: list = []
    depth = 0
    cur = None           # active candidate sequence

    for i, (operands, op) in enumerate(instrs):
        o = str(op)

        if o == "q":
            gstack.append(curfont)
            continue
        if o == "Q":
            if gstack:
                curfont = gstack.pop()
            continue
        if o == "Tf":
            try:
                curfont = fmap.get(str(operands[0]), "?")
            except Exception:
                pass
            if cur is not None and depth == 0 and cur["label"] and cur["split_i"] is None:
                # first font change after the bullet run -> this is the boundary
                if not _SYMBOL_FONT.search(curfont or ""):
                    cur["split_i"] = i
            continue

        if o in ("BDC", "BMC"):
            if cur is not None:
                depth += 1
                continue
            tag = str(operands[0]) if operands else ""
            mcid = None
            if o == "BDC" and len(operands) > 1:
                try:
                    prop = operands[1]
                    if "/MCID" in prop:
                        mcid = int(prop["/MCID"])
                except Exception:
                    pass
            if tag in _HOST_TAGS and mcid is not None and (pi, mcid) in claims:
                cur = {"mcid": mcid, "tag": tag, "open_i": i,
                       "label": b"", "split_i": None, "body": False,
                       "operands": operands}
                depth = 0
            continue

        if o == "EMC":
            if cur is not None:
                if depth == 0:
                    if (cur["label"].strip()
                            and len(cur["label"]) <= _MAX_LABEL_BYTES
                            and cur["split_i"] is not None
                            and cur["body"]):
                        out.append(cur)
                    cur = None
                else:
                    depth -= 1
            continue

        if o in _TEXT_OPS and cur is not None and depth == 0:
            raw = _shown_bytes(operands, o)
            if cur["split_i"] is None:
                if _SYMBOL_FONT.search(curfont or ""):
                    cur["label"] += raw
                else:
                    # text in a body font before any bullet -> not a label
                    cur["split_i"] = -1
            elif cur["split_i"] >= 0 and raw.strip():
                cur["body"] = True

    return [s for s in out if s["split_i"] and s["split_i"] > 0]


# ---------------------------------------------------------------------------
# pass 2 — rewrite the content stream
# ---------------------------------------------------------------------------

def _rewrite_page(pdf, pi, splits) -> dict:
    """Split each candidate into `/Lbl <</MCID new>>` + the original sequence."""
    page = pdf.pages[pi]
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return {}

    max_mcid = -1
    for _i, (operands, op) in enumerate(instrs):
        if str(op) == "BDC" and len(operands) > 1:
            try:
                if "/MCID" in operands[1]:
                    max_mcid = max(max_mcid, int(operands[1]["/MCID"]))
            except Exception:
                pass
    next_mcid = max_mcid + 1

    by_open = {s["open_i"]: s for s in splits}
    by_split = {s["split_i"]: s for s in splits}
    assigned = {}

    out = []
    for i, (operands, op) in enumerate(instrs):
        if i in by_open:
            s = by_open[i]
            lbl_mcid = next_mcid
            next_mcid += 1
            assigned[s["mcid"]] = lbl_mcid
            out.append(CSI([Name("/Lbl"), Dictionary({"/MCID": lbl_mcid})],
                           Operator("BDC")))
            continue
        if i in by_split:
            s = by_split[i]
            # close the label, reopen the host sequence with its ORIGINAL MCID
            out.append(CSI([], Operator("EMC")))
            out.append(CSI(list(s["operands"]), Operator("BDC")))
        out.append(CSI(operands, op))

    page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
    return assigned


# ---------------------------------------------------------------------------
# pass 3 — wire <Lbl> elements into the structure tree
# ---------------------------------------------------------------------------

def _text_of(pdf, el) -> bytes:
    """Raw glyph bytes painted by el's own marked content (one level deep)."""
    pmap = _page_index_map(pdf)
    pg = el.get("/Pg")
    pi = pmap.get(pg.objgen) if pg is not None else None
    if pi is None:
        return b""
    want = set(_iter_mcids(el.get("/K")))
    if not want:
        return b""
    try:
        instrs = list(pikepdf.parse_content_stream(pdf.pages[pi]))
    except Exception:
        return b""
    out = b""
    depth = 0
    for operands, op in instrs:
        o = str(op)
        if o in ("BDC", "BMC"):
            if depth > 0:
                depth += 1
                continue
            m = None
            if o == "BDC" and len(operands) > 1:
                try:
                    if "/MCID" in operands[1]:
                        m = int(operands[1]["/MCID"])
                except Exception:
                    pass
            if m in want:
                depth = 1
        elif o == "EMC":
            if depth > 0:
                depth -= 1
        elif o in _TEXT_OPS and depth > 0:
            out += _shown_bytes(operands, o)
    return out


def _lists_with_labels(pdf) -> list:
    """Every <L> that has at least one <LI> carrying an <Lbl>."""
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return []
    found, seen = [], set()

    def walk(node):
        if isinstance(node, Array):
            for x in node:
                walk(x)
            return
        if not isinstance(node, Dictionary):
            return
        if node.is_indirect:
            if node.objgen in seen:
                return
            seen.add(node.objgen)
        if _stype(node) == "/L":
            for li in _kids(node):
                if isinstance(li, Dictionary) and any(
                    isinstance(c, Dictionary) and _stype(c) == "/Lbl"
                    for c in _kids(li)
                ):
                    found.append(node)
                    break
        walk(node.get("/K"))

    walk(st.get("/K"))
    return found


def _new_lbl(pdf, parent, page_obj, mcid):
    return pdf.make_indirect(Dictionary(
        Type=Name("/StructElem"),
        S=Name("/Lbl"),
        P=parent,
        Pg=page_obj,
        K=Array([mcid]),
    ))


def _insert_before(parent, child, new_el) -> bool:
    """Insert new_el immediately before child in parent's /K."""
    kids = _kids(parent)
    for idx, c in enumerate(kids):
        if isinstance(c, Dictionary) and c.is_indirect and child.is_indirect \
                and c.objgen == child.objgen:
            kids.insert(idx, new_el)
            parent["/K"] = Array(kids)
            return True
    return False


def fix_list_labels(in_path: str, out_path: str) -> dict:
    res = {"labels_created": 0, "items_created": 0, "lists_created": 0,
           "pages_touched": 0, "skipped": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("list_label_fixer: no StructTreeRoot; copied through")
        return res

    claims = _claim_map(pdf)
    parent_of = _parent_index_map(pdf)
    pmap = _page_index_map(pdf)

    # page -> [(host_element, lbl_mcid)]
    pending: list = []

    for pi in range(len(pdf.pages)):
        splits = _find_splits(pdf, pi, claims)
        if not splits:
            continue
        assigned = _rewrite_page(pdf, pi, splits)
        if not assigned:
            continue
        res["pages_touched"] += 1
        for s in splits:
            lbl_mcid = assigned.get(s["mcid"])
            if lbl_mcid is None:
                continue
            host, _hparent = claims[(pi, s["mcid"])]
            pending.append((pi, host, lbl_mcid))

    for pi, host, lbl_mcid in pending:
        page_obj = pdf.pages[pi].obj
        htype = _stype(host)

        # Where does the <Lbl> belong?  Always as the first child of the <LI>
        # that owns this content — that is what "label of this list item" means.
        li = _ancestor_of_type(host, {"/LI"}, parent_of)

        if li is not None:
            # Anchor before the LBody (or before whatever the first kid is).
            lbody = None
            for c in _kids(li):
                if isinstance(c, Dictionary) and _stype(c) == "/LBody":
                    lbody = c
                    break
            lbl = _new_lbl(pdf, li, page_obj, lbl_mcid)
            placed = _insert_before(li, lbody, lbl) if lbody is not None else False
            if not placed:
                li["/K"] = Array([lbl] + _kids(li))
            res["labels_created"] += 1
            continue

        # No <LI> ancestor: this item never became a list item at all.  Build
        # L > LI > (Lbl, LBody > host) around it, joining an adjacent sibling
        # <L> when there is one so we do not add gratuitous single-item lists.
        parent = parent_of.get(host.objgen if host.is_indirect else id(host))
        if parent is None:
            res["skipped"] += 1
            continue

        target = host if htype in ("/P", "/Span") else \
            _ancestor_of_type(host, {"/P", "/Span"}, parent_of)
        if target is None:
            res["skipped"] += 1
            continue
        tparent = parent_of.get(target.objgen if target.is_indirect else id(target))
        if tparent is None:
            res["skipped"] += 1
            continue

        kids = _kids(tparent)
        idx = None
        for j, c in enumerate(kids):
            if isinstance(c, Dictionary) and c.is_indirect and target.is_indirect \
                    and c.objgen == target.objgen:
                idx = j
                break
        if idx is None:
            res["skipped"] += 1
            continue

        new_li = pdf.make_indirect(Dictionary(
            Type=Name("/StructElem"), S=Name("/LI"), P=tparent, K=Array([]),
        ))
        lbl = _new_lbl(pdf, new_li, page_obj, lbl_mcid)
        lbody = pdf.make_indirect(Dictionary(
            Type=Name("/StructElem"), S=Name("/LBody"), P=new_li,
            K=Array([target]),
        ))
        target["/P"] = lbody
        new_li["/K"] = Array([lbl, lbody])

        # Prefer an adjacent <L> sibling over creating a new one.
        host_list = None
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(kids):
                c = kids[j]
                if isinstance(c, Dictionary) and _stype(c) == "/L":
                    host_list = c
                    break

        if host_list is not None:
            new_li["/P"] = host_list
            lk = _kids(host_list)
            if j < idx:
                lk.append(new_li)
            else:
                lk.insert(0, new_li)
            host_list["/K"] = Array(lk)
            del kids[idx]
            tparent["/K"] = Array(kids)
        else:
            new_l = pdf.make_indirect(Dictionary(
                Type=Name("/StructElem"), S=Name("/L"), P=tparent,
                K=Array([new_li]),
            ))
            new_li["/P"] = new_l
            kids[idx] = new_l
            tparent["/K"] = Array(kids)
            res["lists_created"] += 1

        res["labels_created"] += 1
        res["items_created"] += 1

    # /ListNumbering must reflect reality.  This pass runs AFTER
    # final_structure_repair.normalise_lists (which is where the L/LI/LBody
    # tree is settled — running before it is why an earlier version of this
    # stage recovered 2 labels instead of 51), so that step has already written
    # "/None" on the assumption that no labels exist.  Adding labels without
    # correcting the attribute would leave the list claiming it is unlabelled.
    # Rule kept deliberately identical to normalise_lists().
    for L in _lists_with_labels(pdf):
        lbl_text = b""
        for li in _kids(L):
            if not isinstance(li, Dictionary):
                continue
            for c in _kids(li):
                if isinstance(c, Dictionary) and _stype(c) == "/Lbl":
                    lbl_text += _text_of(pdf, c)
        txt = lbl_text.decode("latin-1", "ignore").strip()
        if txt and txt[0].isdigit():
            numbering = Name("/Decimal")
        elif txt and txt[0].isalpha():
            numbering = Name("/LowerAlpha") if txt[0].islower() else Name("/UpperAlpha")
        else:
            numbering = Name("/Disc")
        L["/A"] = pdf.make_indirect(Dictionary(O=Name("/List"),
                                               ListNumbering=numbering))
        res["numbering_set"] = res.get("numbering_set", 0) + 1

    # Any fixer that touches /K owes the tree a /P and ParentTree rebuild.
    try:
        fix_struct_parents(pdf)
        rebuild_parent_tree(pdf)
    except Exception as exc:
        print(f"list_label_fixer: parent rebuild failed: {exc}", file=sys.stderr)

    pdf.save(out_path)
    print("list_label_fixer: "
          f"created {res['labels_created']} <Lbl>, "
          f"{res['items_created']} <LI>, {res['lists_created']} <L>; "
          f"pages_touched={res['pages_touched']} skipped={res['skipped']}")
    return res


def main(argv) -> int:
    if len(argv) < 3:
        print("Usage: list_label_fixer.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        res = fix_list_labels(argv[1], argv[2])
        print(json.dumps(res))
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
