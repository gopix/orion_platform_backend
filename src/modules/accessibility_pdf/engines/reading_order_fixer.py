#!/usr/bin/env python3
"""
reading_order_fixer.py
======================
Fixes logical reading order in the structure tree.

The defect this solves
----------------------
PAC / veraPDF validate the *syntax* of the tag tree, never the *sequence*.  A
file can be 100% PDF/UA-clean and still have a tag tree whose page sequence is

    22, 11, 10, 8, 7, 3, 1, 2, 3, ... , 23, 2, 3, ... , 23

which is what G6_CB_SCIENCE_Ch02 had.  A screen reader walks the tag tree in
order, so it starts reading on page 22.  Every checker passes it.

Two passes
----------
PASS 1  page-order (always on, zero risk)
        Stable-sort the top-level block children of <Document>/<Sect> by the
        page index of their first marked-content item.  Stable => relative
        order inside a page is untouched.  This alone fixes the catastrophic
        case and the "running header / folio / orphaned table row appended at
        the end of the document" case.

PASS 2  within-page order (--within-page, use with review)
        Re-orders blocks inside each page with a column-aware XY-cut:
          - find vertical gutters (x-ranges no block crosses) -> columns
          - full-width blocks act as horizontal separators between row-groups
          - inside a column: top-to-bottom; between columns: left-to-right
        This is what moves a chapter title that was tagged LAST on page 1 back
        to the top, without interleaving a two-column bullet list.

Reordering a /K array does NOT touch the ParentTree (that maps MCID -> element
object, not position), so StructParents stay valid and PAC stays green.

Usage
-----
    python reading_order_fixer.py in.pdf out.pdf [--within-page] [--report]
"""
from __future__ import annotations

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

CONTAINER_TAGS = {"/Document", "/Sect", "/Part", "/Art", "/Div", "/NonStruct"}


# ---------------------------------------------------------------- tree helpers
def _page_index_map(pdf):
    return {p.obj.objgen: i for i, p in enumerate(pdf.pages)}


def _leaves(node, pidx, cur, out):
    """Collect (page_index, mcid) for every marked-content item under `node`."""
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


def _expand(kids, pidx, depth=0):
    """
    Flatten wrapper containers whose page range overlaps their siblings'.

    G6_CB_SCIENCE had <Document> with 214 children, the first of which was a
    single <Sect> holding 275 blocks spanning pages 1-23 while the remaining
    213 siblings also spanned pages 2-23.  No sort of one level can interleave
    those, so a bucket-Sect like this must be spliced into its parent first.
    A Sect that owns a contiguous page range of its own is left intact.
    """
    if depth > 3:
        return list(kids)
    spans = []
    for k in kids:
        lv = []
        _leaves(k, pidx, None, lv)
        pgs = [p for p, _ in lv]
        spans.append((min(pgs), max(pgs)) if pgs else None)

    out = []
    for k, sp in zip(kids, spans):
        is_container = (isinstance(k, Dictionary)
                        and str(k.get("/S")) in CONTAINER_TAGS
                        and isinstance(k.get("/K"), Array))
        overlaps = sp is not None and any(
            o is not None and o is not sp and not (o[1] < sp[0] or o[0] > sp[1])
            for o in spans)
        if is_container and overlaps:
            out.extend(_expand(list(k["/K"]), pidx, depth + 1))
        else:
            out.append(k)
    return out


def _find_block_parent(pdf):
    """Descend Document/Sect/Part wrappers to the array of real content blocks."""
    node = pdf.Root["/StructTreeRoot"].get("/K")
    if isinstance(node, Array):
        if len(node) != 1:
            return pdf.Root["/StructTreeRoot"], "/K"
        node = node[0]
    parent = node
    while True:
        k = parent.get("/K")
        if not isinstance(k, Array):
            return parent, "/K"
        real = [c for c in k if isinstance(c, Dictionary) and c.get("/S") is not None]
        # keep descending only while there is exactly one container child
        if len(k) == 1 and len(real) == 1 and str(real[0].get("/S")) in CONTAINER_TAGS:
            parent = real[0]
            continue
        return parent, "/K"


# ---------------------------------------------------------------- block model
class Block:
    __slots__ = ("obj", "page", "top", "bottom", "left", "right", "chars", "text", "idx", "anchor")

    def __init__(self, obj, idx, leaves, boxes):
        self.obj, self.idx = obj, idx
        self.page = min((p for p, _ in leaves), default=None)
        pl = [boxes[(p, m)] for p, m in leaves
              if (p, m) in boxes and boxes[(p, m)].valid and p == self.page]
        if pl:
            self.top = max(b.y1 for b in pl)
            self.bottom = min(b.y0 for b in pl)
            self.left = min(b.x0 for b in pl)
            self.right = max(b.x1 for b in pl)
            self.chars = sum(b.chars for b in pl)
            self.text = "".join(b.text for b in pl)[:60]
            # anchor = char-weighted vertical centre over TEXT-bearing leaves.
            # A block's reading-order slot must follow where its actual text is,
            # not a stray empty spacer glyph that a fused element dragged in from
            # a neighbouring row (which would hijack a max-y `top` sort).
            inked = [b for b in pl if b.chars > 0]
            if inked:
                wsum = sum(b.chars for b in inked)
                self.anchor = sum(((b.y0 + b.y1) / 2.0) * b.chars for b in inked) / wsum
                self.left = min(b.x0 for b in inked)
            else:
                self.anchor = (self.top + self.bottom) / 2.0
        else:
            self.top = self.bottom = self.left = self.right = None
            self.anchor = None
            self.chars, self.text = 0, ""

    @property
    def positioned(self):
        return self.top is not None


# ---------------------------------------------------------------- pass 2 logic
def _columns(blocks, gutter=18.0):
    """Split blocks into columns by finding vertical gutters they never cross."""
    spans = sorted((b.left, b.right) for b in blocks if b.positioned)
    if not spans:
        return [blocks]
    cuts, cur_end = [], spans[0][1]
    for l, r in spans[1:]:
        if l - cur_end > gutter:
            cuts.append((cur_end + l) / 2.0)
        cur_end = max(cur_end, r)
    if not cuts:
        return [blocks]
    cols = [[] for _ in range(len(cuts) + 1)]
    for b in blocks:
        i = 0
        while i < len(cuts) and b.positioned and b.left > cuts[i]:
            i += 1
        cols[i].append(b)
    return [c for c in cols if c]


def _order_page(blocks, page_width, band=6.0):
    """Column-aware XY-cut for one page's blocks."""
    positioned = [b for b in blocks if b.positioned]
    floating = [b for b in blocks if not b.positioned]
    if not positioned:
        return blocks

    full_w = 0.55 * page_width
    positioned.sort(key=lambda b: (-b.anchor, b.left))

    # split into row-groups separated by full-width blocks
    groups, cur = [], []
    for b in positioned:
        if (b.right - b.left) >= full_w:
            if cur:
                groups.append(cur)
                cur = []
            groups.append([b])
        else:
            cur.append(b)
    if cur:
        groups.append(cur)

    out = []
    for g in groups:
        if len(g) == 1:
            out.extend(g)
            continue
        cols = _columns(g)
        if len(cols) == 1:
            out.extend(sorted(g, key=lambda b: (-b.anchor, b.left)))
        else:
            for c in sorted(cols, key=lambda c: min(b.left for b in c)):
                out.extend(sorted(c, key=lambda b: (-b.anchor, b.left)))
    # blocks with no geometry (image-only figures) keep their original slot order
    out.extend(floating)
    return out




def _mcid_first_glyphs(pdf, pidx):
    """(page_idx, mcid) -> (x, y) of that run's FIRST painted non-space glyph.

    A glyph run's reading position is where its first character sits, not its
    bounding-box corner. For a run that wraps two lines (e.g. one MCID holding
    "...then x = 3 or x = 2.  Solution x") the bbox x0 comes from the SECOND
    line's left margin, which sorts it ahead of a run that actually precedes it
    on line one. Keying on the first glyph fixes that.
    """
    from pikepdf import parse_content_stream, Dictionary as _D, Array as _A, String as _S
    out = {}
    def _mul(a, b):
        return [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
                a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3],
                a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5]]
    for pi, page in enumerate(pdf.pages):
        try:
            toks = parse_content_stream(page)
        except Exception:
            continue
        cur = None; stack = []; tm = [1,0,0,1,0,0]; tlm = tm[:]
        for ins in toks:
            op = str(ins.operator); a = ins.operands
            if op == "BDC" and len(a) >= 2:
                mc = None; p = a[1]
                try:
                    if isinstance(p, _D) and "/MCID" in p: mc = int(p["/MCID"])
                except Exception: mc = None
                stack.append(cur)
                if mc is not None: cur = mc
            elif op == "BMC":
                stack.append(cur)
            elif op == "EMC":
                if stack: cur = stack.pop()
            elif op == "BT":
                tm = [1,0,0,1,0,0]; tlm = tm[:]
            elif op in ("Td", "TD") and len(a) >= 2:
                tlm = _mul([1,0,0,1,float(a[0]),float(a[1])], tlm); tm = tlm[:]
            elif op == "Tm" and len(a) >= 6:
                tm = [float(x) for x in a]; tlm = tm[:]
            elif op == "T*":
                tlm = _mul([1,0,0,1,0,0], tlm); tm = tlm[:]
            elif op in ("Tj", "'", "\"", "TJ") and cur is not None:
                if (pi, cur) in out:
                    continue
                s = ""
                if op == "TJ":
                    for el in a[0]:
                        if isinstance(el, _S): s += bytes(el).decode("latin-1", "replace")
                else:
                    s = bytes(a[0]).decode("latin-1", "replace")
                if s.strip("\x00 \u2000"):
                    out[(pi, cur)] = (tm[4], tm[5])
    return out


def _sort_leaf_content(pdf, boxes, pidx, firsts=None):
    """
    Reorder the MCID/MCR children of every LEAF element (one with no child
    struct elements) into geometric reading order: top-to-bottom, then
    left-to-right within a ~6pt band. Fixes fused elements whose /K lists
    marked content from several Y-bands in scrambled order (e.g. a heading
    that swallowed the title + spacer glyphs + a stray body glyph), which
    block-level reordering cannot touch. Reordering /K entries does NOT alter
    the ParentTree (MCID->element), so this is PAC-safe.
    """
    from pikepdf import Dictionary as _D, Array as _A
    touched = 0

    def page_of(node, inherited):
        pg = node.get("/Pg")
        if pg is not None:
            try:
                return pidx.get(pg.objgen, inherited)
            except Exception:
                return inherited
        return inherited

    def ref_of(kid, pi):
        k = kid.get_object() if hasattr(kid, "get_object") else kid
        if isinstance(kid, int):
            return (pi, int(kid))
        if isinstance(k, _D) and str(k.get("/Type", "")) == "/MCR" and "/MCID" in k:
            try:
                m = int(k["/MCID"])
            except Exception:
                return None
            pg = k.get("/Pg")
            tgt = pidx.get(pg.objgen) if pg is not None else pi
            return (tgt, m)
        return None

    if firsts is None:
        firsts = _mcid_first_glyphs(pdf, pidx)

    def key(kid, pi):
        r = ref_of(kid, pi)
        fg = firsts.get(r) if r else None
        if fg is not None:                          # order by first painted glyph
            return (0, round(-fg[1] / 6.0), fg[0])
        b = boxes.get(r) if r else None
        if b is not None and b.valid:               # empties/no-glyph: fall back to bbox
            return (0, round(-b.y1 / 6.0), b.x0)
        return (1, 0, 0)                            # unpositioned: keep at end, stable

    def walk(node, inherited):
        pi = page_of(node, inherited)
        ks = node.get("/K")
        if ks is None:
            return
        kids = list(ks) if isinstance(ks, _A) else [ks]
        child_elems = [c for c in kids
                       if isinstance((c.get_object() if hasattr(c, "get_object") else c), _D)
                       and "/S" in (c.get_object() if hasattr(c, "get_object") else c)]
        if child_elems:
            for c in child_elems:
                walk(c.get_object() if hasattr(c, "get_object") else c, pi)
            return
        # pure leaf: only re-sort if its content spans MULTIPLE Y-bands, i.e.
        # it is a FUSED element (a heading that swallowed the title + spacers +
        # a body glyph). Single-line labels/headings, where every glyph shares
        # one baseline, are left exactly as tagged so a decorative badge like
        # "Chapter" is never reshuffled by a noisy left-right sort.
        if len(kids) > 1:
            tops = []
            for c in kids:
                r = ref_of(c, pi); b = boxes.get(r) if r else None
                if b is not None and b.valid:
                    tops.append(b.y1)
            if tops and (max(tops) - min(tops)) > 24.0:
                ordered = sorted(kids, key=lambda c: key(c, pi))
                if [id(x) for x in ordered] != [id(x) for x in kids]:
                    node["/K"] = _A(ordered)
                    nonlocal_touched[0] += 1

    nonlocal_touched = [0]
    root = pdf.Root["/StructTreeRoot"]
    for c in (list(root["/K"]) if isinstance(root.get("/K"), _A) else [root.get("/K")]):
        if c is None:
            continue
        cc = c.get_object() if hasattr(c, "get_object") else c
        if isinstance(cc, _D) and "/S" in cc:
            walk(cc, None)
    return nonlocal_touched[0]


# ---------------------------------------------------------------- inline fragments
def _merge_inline_fragments(pdf, boxes, pidx):
    """Reunite orphan super/subscript & single-glyph math fragments into the host
    text element they visually belong to.

    PDFix (esp. the trial build) tags every superscript/subscript and stray math
    glyph as its OWN sibling <P>/<H2>. Because a superscript sits ABOVE its base
    line, no sibling-block reorder can place it inline -- it always sorts into the
    line above or ahead of a heading (e.g. the 2 of x^2 reading before <H6>).
    The only correct fix is to move the fragment's marked content INTO the host
    and drop the now-empty fragment element.

    Placement preserves the host's own PDFix reading order (which is correct); the
    fragment is inserted right AFTER its base run on the same baseline. Runs LAST,
    so no later leaf-sort re-scatters it. ParentTree/ /P are rebuilt by the caller,
    so this stays PAC-safe.
    """
    from pikepdf import Dictionary as _D, Array as _A, Name as _N
    # "/Title" holds the document title's marked content and must be treated as
    # a text container like any heading, or its content is left behind when
    # split fragments are re-joined (see title_tag.py).
    TEXT_CONT = {"/P","/Title","/H1","/H2","/H3","/H4","/H5","/H6","/LBody","/Span","/Note","/Lbl"}

    parent, key = _find_block_parent(pdf)
    kids = list(parent[key]) if isinstance(parent[key], _A) else [parent[key]]

    def _cref(node, c):
        if isinstance(c, int):
            pg = node.get("/Pg")
            return (pidx.get(pg.objgen) if pg is not None else None, int(c))
        if isinstance(c, _D) and str(c.get("/Type")) == "/MCR":
            pg = c.get("/Pg")
            return (pidx.get(pg.objgen) if pg is not None else None, int(c.get("/MCID")))
        return None

    def _leaf_refs(node):
        """Direct content refs of a pure-leaf element, or None if it holds child elems."""
        k = node.get("/K")
        if k is None:
            return []
        cs = list(k) if isinstance(k, _A) else [k]
        out = []
        for c in cs:
            if isinstance(c, _D) and "/S" in c:
                return None
            r = _cref(node, c)
            if r is not None:
                out.append(r)
        return out

    def _box(refs):
        bs = [boxes.get(r) for r in refs]
        bs = [b for b in bs if b and getattr(b, "valid", False) and b.chars > 0]
        if not bs:
            return None
        return dict(y0=min(b.y0 for b in bs), y1=max(b.y1 for b in bs),
                    x0=min(b.x0 for b in bs), x1=max(b.x1 for b in bs),
                    chars=sum(b.chars for b in bs), page=refs[0][0])

    def _vov(a, b):
        return max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))

    meta = []  # (index, node, refs, box, S)
    for i, c in enumerate(kids):
        if not isinstance(c, _D) or "/S" not in c:
            meta.append((i, c, None, None, None)); continue
        refs = _leaf_refs(c)
        g = _box(refs) if refs else None
        meta.append((i, c, refs, g, str(c.get("/S"))))

    # choose host per fragment (chars <= 2): text container, same page, vertical
    # overlap, horizontal containment preferred over a heading merely on the line.
    plan = {}  # host_idx -> [frag_idx,...]
    for i, node, refs, g, S in meta:
        if g is None or refs is None or g["chars"] > 2:
            continue
        fh = g["y1"] - g["y0"]
        cands = []
        for j, jn, jrefs, jg, jS in meta:
            if j == i or jg is None or jrefs is None:
                continue
            if jg["page"] != g["page"] or jg["chars"] < 5 or jS not in TEXT_CONT:
                continue
            if _vov(g, jg) < 0.3 * fh:
                continue
            fx = g["x0"]
            contains = jg["x0"] - 2 <= fx <= jg["x1"] + 2
            hdist = 0.0 if contains else (fx - jg["x1"] if fx > jg["x1"] else jg["x0"] - fx)
            cands.append((0 if contains else 1, hdist, -_vov(g, jg), j))
        if cands:
            cands.sort()
            plan.setdefault(cands[0][3], []).append(i)

    if not plan:
        return 0

    def _mcr(ref):
        return pdf.make_indirect(_D(Type=_N("/MCR"), Pg=pdf.pages[ref[0]].obj, MCID=ref[1]))

    drained = set()
    for hj, fis in plan.items():
        hn = meta[hj][1]
        hk = list(hn.get("/K")) if isinstance(hn.get("/K"), _A) else [hn.get("/K")]

        def cbox(c):
            r = _cref(hn, c); b = boxes.get(r) if r else None
            if b and getattr(b, "valid", False) and b.chars > 0:
                return dict(y0=b.y0, y1=b.y1, x0=b.x0, x1=b.x1)
            return None

        for fi in fis:
            frefs = meta[fi][2]; fg = meta[fi][3]
            new = [_mcr(r) for r in frefs]
            # 1) single-line left neighbour on the fragment's baseline
            best_idx, best_x1 = None, -1e9
            for idx, c in enumerate(hk):
                bb = cbox(c)
                if bb is None or _vov(bb, fg) <= 0:
                    continue
                if (bb["y1"] - bb["y0"]) < 15.0 and bb["x1"] <= fg["x1"] + 2 and bb["x1"] > best_x1:
                    best_x1, best_idx = bb["x1"], idx
            if best_idx is not None:
                hk = hk[:best_idx + 1] + new + hk[best_idx + 1:]
            else:
                # 2) anchor to the overlapping (often fused multi-line) run
                cand, gap = None, 1e9
                for idx, c in enumerate(hk):
                    bb = cbox(c)
                    if bb is None or _vov(bb, fg) <= 0:
                        continue
                    d = abs(bb["y0"] - fg["y0"])
                    if d < gap:
                        gap, cand = d, idx
                if cand is None:
                    hk = hk + new
                else:
                    bb = cbox(hk[cand])
                    if fg["x0"] >= bb["x0"] - 2:
                        hk = hk[:cand + 1] + new + hk[cand + 1:]
                    else:
                        hk = hk[:cand] + new + hk[cand:]
        hn["/K"] = _A(hk)
        drained.update(fis)

    parent[key] = _A([c for i, c in enumerate(kids) if i not in drained])
    return len(drained)


# ---------------------------------------------------------------- main
def fix(inp, outp, within_page=False, report=False):
    pdf = pikepdf.open(inp)
    if "/StructTreeRoot" not in pdf.Root:
        print("no structure tree, nothing to do")
        return
    pidx = _page_index_map(pdf)
    boxes = document_mcid_boxes(pdf)

    parent, key = _find_block_parent(pdf)
    kids = list(parent[key]) if isinstance(parent[key], Array) else [parent[key]]
    kids = _expand(kids, pidx)

    blocks = []
    for i, k in enumerate(kids):
        lv = []
        _leaves(k, pidx, None, lv)
        blocks.append(Block(k, i, lv, boxes))

    before = [b.page for b in blocks if b.page is not None]

    # PASS 1 - stable sort by page (unplaced blocks keep their neighbour's page)
    last = 0
    for b in blocks:
        if b.page is None:
            b.page = last
        else:
            last = b.page
    ordered = sorted(blocks, key=lambda b: (b.page, b.idx))

    # PASS 2 - within-page column-aware order
    if within_page:
        by_page = collections.OrderedDict()
        for b in ordered:
            by_page.setdefault(b.page, []).append(b)
        ordered = []
        for pg, bl in by_page.items():
            w = float(pdf.pages[pg].mediabox[2]) - float(pdf.pages[pg].mediabox[0])
            ordered.extend(_order_page(bl, w))

    parent[key] = Array([b.obj for b in ordered])

    # within-element pass: order each leaf's MCIDs top-to-bottom
    leaf_sorted = _sort_leaf_content(pdf, boxes, pidx)

    # LAST tree mutation: reunite orphan super/subscript glyph elements into
    # their host paragraph (PDFix tags each as a stray sibling <P>). Must follow
    # the leaf sort so nothing re-scatters the inserted glyphs.
    merged = _merge_inline_fragments(pdf, boxes, pidx)

    # flattening re-parents elements: /P and the ParentTree must both be redone
    nfix = fix_struct_parents(pdf)
    rebuild_parent_tree(pdf)

    after = [b.page for b in ordered]
    if report:
        def jumps(seq):
            c = [seq[0]]
            for s in seq[1:]:
                if s != c[-1]:
                    c.append(s)
            return sum(1 for a, b in zip(c, c[1:]) if b < a), [x + 1 for x in c]
        jb, sb = jumps(before)
        ja, sa = jumps(after)
        print(f"blocks reordered : {sum(1 for i, b in enumerate(ordered) if b.idx != i)}/{len(blocks)}")
        print(f"backward page jumps : {jb} -> {ja}")
        print(f"page sequence before: {sb}")
        print(f"page sequence after : {sa}")
        print(f"/P pointers repaired: {nfix}")

    pdf.save(outp)
    pdf.close()   # Windows: os.replace() is denied while the file is still open
    print(f"saved {outp}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fix(args[0], args[1],
        within_page="--within-page" in sys.argv,
        report="--report" in sys.argv)
