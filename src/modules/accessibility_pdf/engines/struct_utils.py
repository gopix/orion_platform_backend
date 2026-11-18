#!/usr/bin/env python3
"""
struct_utils.py
---------------
Shared surgery helpers used by alt_text_sanitizer.py and table_builder.py.

Any fixer that RE-PARENTS marked content (moves an MCID from one struct element
to another) must rebuild the ParentTree, or PAC fails immediately with
"structure parent mismatch".  Reordering /K does not need this; re-parenting
always does.
"""
from __future__ import annotations

import pikepdf
from pikepdf import Dictionary, Name, Array


# --------------------------------------------------------------- /P pointers
def fix_struct_parents(pdf):
    """
    Rewrite every struct element's /P to its ACTUAL parent in the tree.

    Any fixer that moves an element between parents (reordering across a
    flattened Sect, merging a Lbl into a heading, lifting text out of a Figure)
    leaves /P pointing at the old parent.  PAC reports this as
    "Structure element refers to a different parent than the actual parent"
    and the file fails PDF/UA even though the tree itself is fine.

    Must be called by every fixer that touches /K.
    """
    st = pdf.Root["/StructTreeRoot"]
    fixed = [0]

    def walk(node, parent):
        if isinstance(node, Array):
            for k in node:
                walk(k, parent)
            return
        if not isinstance(node, Dictionary):
            return
        if node.get("/Type") in (Name("/MCR"), Name("/OBJR")):
            return
        if node.get("/S") is not None:
            cur = node.get("/P")
            if cur is None or cur.objgen != parent.objgen:
                node["/P"] = parent
                fixed[0] += 1
        walk(node.get("/K"), node)

    walk(st.get("/K"), st)
    return fixed[0]


# --------------------------------------------------------------- ParentTree
def _own_structparents_streams(pdf):
    """Form XObjects that carry their own /StructParents -> their own MCID namespace."""
    out = {}
    for page in pdf.pages:
        res = page.get("/Resources") or Dictionary()
        xod = res.get("/XObject")
        if xod is None:
            continue
        for _k, xo in xod.items():
            try:
                if xo.get("/Subtype") == Name("/Form") and "/StructParents" in xo:
                    out[xo.objgen] = int(xo["/StructParents"])
            except Exception:
                pass
    return out


def rebuild_parent_tree(pdf):
    """
    Re-derive /StructTreeRoot/ParentTree from the current tree.

    Marked content lives in THREE possible namespaces and all three need a key:
      * page content streams        -> the page's /StructParents
      * Form XObjects that carry
        their own /StructParents    -> that XObject's key. The struct tree
                                       reaches these via an MCR with /Stm.
                                       Dropping these keys makes PAC report
                                       "Structural parent tree: Inconsistent
                                       entry found".
      * annotations                 -> the annot's /StructParent, via OBJR
    """
    st = pdf.Root["/StructTreeRoot"]
    pidx = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    stream_keys = _own_structparents_streams(pdf)

    page_owners = {}      # (page_index, mcid) -> element
    stm_owners = {}       # (stream_objgen, mcid) -> element
    annots = {}           # StructParent int -> element

    def walk(node, cur, parent_elem):
        if isinstance(node, Array):
            for k in node:
                walk(k, cur, parent_elem)
            return
        if isinstance(node, int):
            if cur is not None and parent_elem is not None:
                page_owners[(cur, int(node))] = parent_elem
            return
        if not isinstance(node, Dictionary):
            return
        t = node.get("/Type")
        if t == Name("/MCR"):
            if parent_elem is None:
                return
            stream = node.get("/Stm")
            if stream is not None and stream.objgen in stream_keys:
                stm_owners[(stream.objgen, int(node.get("/MCID")))] = parent_elem
                return
            pg = node.get("/Pg")
            pi = pidx.get(pg.objgen) if pg is not None else cur
            if pi is not None:
                page_owners[(pi, int(node.get("/MCID")))] = parent_elem
            return
        if t == Name("/OBJR"):
            obj = node.get("/Obj")
            if obj is not None and "/StructParent" in obj and parent_elem is not None:
                annots[int(obj["/StructParent"])] = parent_elem
            return
        pg = node.get("/Pg")
        nxt = pidx.get(pg.objgen) if pg is not None else cur
        walk(node.get("/K"), nxt, node)

    walk(st.get("/K"), None, None)

    entries = []
    next_key = 0
    for i, page in enumerate(pdf.pages):
        mcids = [m for (p, m) in page_owners if p == i]
        key = int(page.obj["/StructParents"]) if "/StructParents" in page.obj else next_key
        page.obj["/StructParents"] = key
        next_key = max(next_key, key + 1)
        n = (max(mcids) + 1) if mcids else 0
        arr = Array([page_owners.get((i, m), None) for m in range(n)])
        entries.append((key, pdf.make_indirect(arr)))

    for objgen, key in stream_keys.items():
        mcids = [m for (s, m) in stm_owners if s == objgen]
        n = (max(mcids) + 1) if mcids else 0
        arr = Array([stm_owners.get((objgen, m), None) for m in range(n)])
        entries.append((key, pdf.make_indirect(arr)))
        next_key = max(next_key, key + 1)

    for k, elem in annots.items():
        entries.append((k, elem))
        next_key = max(next_key, k + 1)

    # /Nums in a number tree must be sorted by key, ascending. Not optional.
    entries.sort(key=lambda e: e[0])
    nums = []
    for k, v in entries:
        nums.append(k)
        nums.append(v)

    st["/ParentTree"] = pdf.make_indirect(Dictionary(Nums=Array(nums)))
    st["/ParentTreeNextKey"] = next_key


def add_figure_bboxes(pdf, boxes):
    """
    PDF/UA: a <Figure> confined to one page must declare a bounding box via
    /A << /O /Layout /BBox [x0 y0 x1 y1] >>.  PAC: "Figure element on a single
    page with no bounding box".  Figures we create ourselves have to carry it.

    `boxes` is {(page_index, mcid): BBox} from mcid_geometry.
    """
    pidx = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    added = [0]

    def leaves(node, cur, out):
        if isinstance(node, Array):
            for k in node:
                leaves(k, cur, out)
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
        leaves(node.get("/K"), nxt, out)

    def has_bbox(node):
        a = node.get("/A")
        if a is None:
            return False
        for x in (a if isinstance(a, Array) else [a]):
            if isinstance(x, Dictionary) and "/BBox" in x:
                return True
        return False

    def walk(node, cur):
        if isinstance(node, Array):
            for k in node:
                walk(k, cur)
            return
        if not isinstance(node, Dictionary):
            return
        if node.get("/Type") in (Name("/MCR"), Name("/OBJR")):
            return
        pg = node.get("/Pg")
        c = pidx.get(pg.objgen) if pg is not None else cur
        if node.get("/S") == Name("/Figure") and not has_bbox(node):
            lv = []
            leaves(node, c, lv)
            bl = [boxes[k] for k in lv if k in boxes and boxes[k].valid]
            pages = {k[0] for k in lv if k[0] is not None}
            if bl and len(pages) == 1:
                x0 = min(b.x0 for b in bl); y0 = min(b.y0 for b in bl)
                x1 = max(b.x1 for b in bl); y1 = max(b.y1 for b in bl)
                node["/A"] = pdf.make_indirect(Dictionary(
                    O=Name("/Layout"),
                    BBox=Array([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)])))
                added[0] += 1
        walk(node.get("/K"), c)

    walk(pdf.Root["/StructTreeRoot"].get("/K"), None)
    return added[0]


# --------------------------------------------------------------- artifacting
def artifact_mcids(pdf, page, mcids):
    """
    Rewrite content so the given MCIDs become /Artifact BMC.  The content stays
    visible; it just stops being tagged content.

    MUST recurse into Form XObjects.  Marked content very often lives inside a
    form, and rewriting only the page stream leaves the BDC in place while the
    struct element is removed -> orphaned tagged content, which PAC reports in
    bulk under "Content".

    Caller removes the struct elements, then calls rebuild_parent_tree().
    """
    if not mcids:
        return 0
    hits = [0]
    seen = set()

    def rewrite(obj, res, depth=0, is_page=False):
        if depth > 4:
            return
        try:
            instrs = list(pikepdf.parse_content_stream(obj))
        except Exception:
            return
        out, changed = [], False
        for ops, op in instrs:
            o = str(op)
            if o == "BDC" and len(ops) > 1:
                p = ops[1]
                mcid = None
                if isinstance(p, Dictionary) and "/MCID" in p:
                    mcid = int(p["/MCID"])
                elif isinstance(p, Name):
                    # BDC can name an entry in /Resources /Properties instead of
                    # carrying an inline dict. Missing this leaves the content
                    # tagged while its struct element is gone -> orphan.
                    props = res.get("/Properties") if res is not None else None
                    if props is not None:
                        try:
                            d = props.get(str(p))
                            if d is not None and "/MCID" in d:
                                mcid = int(d["/MCID"])
                        except Exception:
                            pass
                if mcid in mcids:
                    out.append(([Name("/Artifact")], pikepdf.Operator("BMC")))
                    hits[0] += 1
                    changed = True
                    continue
            elif o == "Do":
                xod = res.get("/XObject")
                if xod is not None:
                    xo = xod.get(str(ops[0]))
                    if (xo is not None and xo.get("/Subtype") == Name("/Form")
                            and "/StructParents" not in xo
                            and xo.objgen not in seen):
                        seen.add(xo.objgen)
                        rewrite(xo, xo.get("/Resources") or res, depth + 1, False)
            out.append((ops, op))
        if changed:
            data = pikepdf.unparse_content_stream(out)
            if is_page:                      # pikepdf objects are not `is`-comparable
                page.obj.Contents = pdf.make_stream(data)
            else:
                obj.write(data)

    rewrite(page.obj, page.get("/Resources") or Dictionary(), 0, True)
    return hits[0]


# --------------------------------------------------------------- ghost refs
def strip_ghost_refs(pdf):
    """
    Drop /K entries pointing at MCIDs that are not reachable tagged content -
    either absent from the page, or sitting inside an /Artifact block.

    PAC reports these under PDF Syntax.  They exist in PDFix output straight out
    of the box (G6_CB_SCIENCE had a dangling MCID 0 on 9 pages before any fixer
    ran), and any fixer that artifacts content can create more.

    Note the subtlety: an MCID inside an /Artifact IS in the content stream, so
    a naive "does this MCID exist?" check passes it.  It must be resolved with
    the artifact nesting taken into account.
    """
    import collections
    pidx = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    live = collections.defaultdict(set)
    for i, page in enumerate(pdf.pages):
        stack = []
        try:
            instrs = pikepdf.parse_content_stream(page.obj)
        except Exception:
            continue
        for ops, op in instrs:
            o = str(op)
            if o in ("BDC", "BMC"):
                tag = str(ops[0]) if ops else "?"
                mcid = None
                if o == "BDC" and len(ops) > 1 and isinstance(ops[1], Dictionary) \
                        and "/MCID" in ops[1]:
                    mcid = int(ops[1]["/MCID"])
                stack.append((tag, mcid))
                if mcid is not None and not any(t == "/Artifact" for t, _ in stack):
                    live[i].add(mcid)
            elif o == "EMC":
                if stack:
                    stack.pop()

    removed = [0]

    def walk(node, cur):
        if not isinstance(node, Dictionary):
            return
        pg = node.get("/Pg")
        c = pidx.get(pg.objgen) if pg is not None else cur
        k = node.get("/K")
        if isinstance(k, Array):
            keep = []
            for it in k:
                if isinstance(it, int):
                    if c is None or int(it) not in live[c]:
                        removed[0] += 1
                        continue
                elif isinstance(it, Dictionary) and it.get("/Type") == Name("/MCR"):
                    ipg = it.get("/Pg")
                    pi = pidx.get(ipg.objgen) if ipg is not None else c
                    if pi is None or int(it["/MCID"]) not in live[pi]:
                        removed[0] += 1
                        continue
                keep.append(it)
                walk(it, c)
            node["/K"] = Array(keep)
        elif isinstance(k, Dictionary):
            walk(k, c)

    root = pdf.Root["/StructTreeRoot"].get("/K")
    if isinstance(root, Array):
        for c in root:
            walk(c, None)
    else:
        walk(root, None)
    return removed[0]


# --------------------------------------------------------------- tree helpers
def detach(node, parent):
    """Remove `node` from parent's /K array."""
    k = parent.get("/K")
    if isinstance(k, Array):
        parent["/K"] = Array([c for c in k if not (isinstance(c, Dictionary)
                                                   and c.objgen == node.objgen)])


def prune_empty(pdf, tags=("/P", "/Span", "/NonStruct", "/Div")):
    """Drop elements of the given tags whose /K array is empty."""
    removed = [0]

    def walk(node):
        if not isinstance(node, Dictionary):
            return
        k = node.get("/K")
        if isinstance(k, Array):
            keep = []
            for c in k:
                if (isinstance(c, Dictionary) and c.get("/S") is not None
                        and str(c.get("/S")) in tags
                        and isinstance(c.get("/K"), Array) and len(c["/K"]) == 0):
                    removed[0] += 1
                    continue
                keep.append(c)
                walk(c)
            node["/K"] = Array(keep)

    root = pdf.Root["/StructTreeRoot"].get("/K")
    if isinstance(root, Array):
        for c in root:
            walk(c)
    else:
        walk(root)
    return removed[0]
