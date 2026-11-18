#!/usr/bin/env python3
"""
paragraph_merge_fixer.py

Post-processing fixer for the Orion accessibility remediation pipeline.

Problem
-------
PDFix ``AddTags()`` performs paragraph recognition per *visual line*: a single
logical paragraph that wraps across several lines is emitted as several sibling
``<P>`` structure elements. A screen reader then announces each fragment as its
own paragraph (extra pauses) and orphaned tails such as "est laborum." are read
in isolation. This is the "unnecessary paragraph breaks" defect flagged in QA.

Nothing downstream in the pipeline consolidates these, so whatever PDFix emits
ships as-is.

Fix
---
Walk the structure tree and, for every run of consecutive sibling ``<P>``
elements under the same parent, merge fragments that belong to one logical
paragraph into a single ``<P>``:

  * The merge is driven by the *text* of each fragment, not by geometry, so it
    is robust across producers. Text is recovered by parsing each page content
    stream and attributing drawn text to the enclosing ``/MCID``.
  * Two adjacent ``<P>`` fragments are joined when the earlier fragment does
    **not** end at a sentence/paragraph boundary (no terminal punctuation
    ``. ! ? : ; ...``) and the next fragment does not begin a new block-level
    unit (e.g. a bullet / numbered list marker).
  * Merging only moves the child marked-content references (``/K``) of the
    absorbed fragment into the surviving element; **no content is deleted** and
    reading order is preserved. The absorbed empty ``<P>`` elements are removed
    from the parent's ``/K``.

The pass is deliberately conservative: it never merges across a non-``<P>``
sibling (heading, list, table, figure...), never merges into or out of a
heading, and leaves the document untouched if the structure tree is missing.

Convention
----------
    python3 paragraph_merge_fixer.py <input.pdf> <output.pdf>
Exit 0 + non-empty output signals success. Nothing to do -> valid copy, exit 0.

Tunable via env:
    ORION_PARA_MERGE_DISABLE = "1" -> copy through, do nothing.

Requires: pikepdf.
"""

from __future__ import annotations

import os
import re
import sys

try:
    import pikepdf
except ImportError:  # pragma: no cover
    print("paragraph_merge_fixer: pikepdf is required", file=sys.stderr)
    sys.exit(1)


# A fragment is treated as ending a paragraph when its last non-space char is
# terminal punctuation, optionally followed by a closing quote/paren/bracket.
_TERMINAL_RE = re.compile(r'[.!?:;…]["\'’”\)\]\}]?\s*$')

# The next fragment starts a unit we must NOT fold into the previous paragraph.
_LIST_MARKER_RE = re.compile(
    r'^\s*('
    r'[•‣◦⁃∙\-\*·]'      # bullet glyphs / dashes
    r'|\(?[0-9]{1,3}[.\)]'                              # 1.  2)  (3)
    r'|\(?[a-zA-Z][.\)]'                                # a.  b)  (c)
    r')\s+'
)


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()


def _ends_paragraph(text: str) -> bool:
    """True if `text` looks like the end of a logical paragraph."""
    t = _norm(text)
    if not t:
        # An empty fragment is not a boundary; let it fold so it is cleaned up.
        return False
    return bool(_TERMINAL_RE.search(t))


def _starts_new_block(text: str) -> bool:
    """True if `text` should start its own paragraph (list item, etc.)."""
    return bool(_LIST_MARKER_RE.match(text or ''))


# -- MCID -> text, by parsing the page content streams ------------------------

def _decode_text_operand(op) -> str:
    """Decode a Tj/'/" string operand to text for boundary testing.

    We only rely on ASCII punctuation, digits and spacing for the merge
    heuristic, so a latin-1 decode of the raw bytes is sufficient and works
    regardless of the font's real encoding (custom CMaps included).
    """
    try:
        return bytes(op).decode("latin-1", "replace")
    except Exception:
        try:
            return str(op)
        except Exception:
            return ""


def _decode_tj_array(arr) -> str:
    """Decode a TJ array, treating large negative kerns as word spaces."""
    parts = []
    for el in arr:
        if isinstance(el, pikepdf.String):
            parts.append(_decode_text_operand(el))
        else:
            try:
                if float(el) <= -100:  # wide negative adjustment ~ a space
                    parts.append(" ")
            except Exception:
                pass
    return "".join(parts)


def _mcid_text_map(pdf):
    """Return {page_index: {mcid: text}} by parsing page content streams.

    Producer-independent: walks marked-content operators and accumulates the
    text drawn inside each ``/MCID`` sequence. Text is attributed to the
    innermost open MCID.
    """
    out = {}
    for pidx, page in enumerate(pdf.pages):
        try:
            instrs = pikepdf.parse_content_stream(page)
        except Exception:
            continue
        mp = {}
        mcid_stack = []
        for instr in instrs:
            try:
                op = str(instr.operator)
            except Exception:
                continue
            if op == "BDC":
                ops = instr.operands
                mcid = None
                if len(ops) >= 2 and isinstance(ops[1], pikepdf.Dictionary) \
                        and "/MCID" in ops[1]:
                    try:
                        mcid = int(ops[1]["/MCID"])
                    except Exception:
                        mcid = None
                mcid_stack.append(mcid)
            elif op == "BMC":
                mcid_stack.append(None)
            elif op == "EMC":
                if mcid_stack:
                    mcid_stack.pop()
            elif op in ("Tj", "'", '"'):
                cur = next((m for m in reversed(mcid_stack) if m is not None), None)
                if cur is None:
                    continue
                strop = instr.operands[-1] if instr.operands else None
                if isinstance(strop, pikepdf.String):
                    mp.setdefault(cur, []).append(_decode_text_operand(strop))
            elif op == "TJ":
                cur = next((m for m in reversed(mcid_stack) if m is not None), None)
                if cur is None:
                    continue
                if instr.operands and isinstance(instr.operands[0], pikepdf.Array):
                    mp.setdefault(cur, []).append(
                        _decode_tj_array(instr.operands[0]))
        if mp:
            out[pidx] = {k: _norm(" ".join(v)) for k, v in mp.items()}
    return out


# -- structure-tree helpers ---------------------------------------------------

def _mcid_style_map(pdf):
    """(page_index, mcid) -> (dominant_font_basename, rounded_effective_size).

    Used to STOP the merger fusing a heading into the body paragraph that
    follows it.  A heading such as "Executive Summary" carries no terminal
    punctuation, so the "does the previous fragment end a sentence?" test
    alone concludes the next paragraph is a continuation of it and merges the
    two — destroying the heading.  Font/size is the reliable discriminator:
    headings are set in a different face (e.g. Meiryo-Bold) and/or size from
    body text, so fragments whose style differs are never joined.

    Effective size = Tf size * text-matrix scale, because many producers set
    "/F1 1 Tf" and carry the real size in the Tm.  The graphics-state stack
    (q/Q) is tracked, since it saves and restores the current font — without
    that, a font leaks past its Q and body text is misread as bold.
    """
    import math
    from collections import Counter

    styles = {}
    for pindex, page in enumerate(pdf.pages):
        res = page.get("/Resources")
        fonts = (res.get("/Font") if res is not None else None) or {}
        fmap = {}
        for k, v in fonts.items():
            try:
                fmap[str(k)] = str(v.get("/BaseFont", "?"))
            except Exception:
                fmap[str(k)] = "?"
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue

        acc = {}
        mc_stack = []
        gs = {"font": None, "tf": 1.0}
        gstack = []
        tm_scale = 1.0

        for ins in instrs:
            try:
                op = str(ins.operator)
            except Exception:
                continue
            if op == "q":
                gstack.append(dict(gs))
            elif op == "Q":
                if gstack:
                    gs = gstack.pop()
            elif op in ("BDC", "BMC"):
                m = None
                if op == "BDC":
                    try:
                        ops = ins.operands
                        if len(ops) >= 2 and isinstance(ops[1], pikepdf.Dictionary) \
                                and "/MCID" in ops[1]:
                            m = int(ops[1]["/MCID"])
                    except Exception:
                        m = None
                mc_stack.append(m)
            elif op == "EMC":
                if mc_stack:
                    mc_stack.pop()
            elif op == "Tf":
                try:
                    gs["font"] = fmap.get(str(ins.operands[0]), str(ins.operands[0]))
                    gs["tf"] = float(ins.operands[1])
                except Exception:
                    pass
            elif op == "Tm":
                try:
                    a, b, c, d = [float(x) for x in ins.operands[:4]]
                    tm_scale = math.sqrt(abs(a * d - b * c)) or 1.0
                except Exception:
                    pass
            elif op in ("Tj", "TJ", "'", '"'):
                cur = next((x for x in reversed(mc_stack) if x is not None), None)
                if cur is None:
                    continue
                # only count runs that actually paint a glyph
                painted = False
                try:
                    if op == "TJ":
                        for e in ins.operands[0]:
                            if isinstance(e, pikepdf.String) and bytes(e).strip():
                                painted = True
                    else:
                        s = ins.operands[-1]
                        if isinstance(s, pikepdf.String) and bytes(s).strip():
                            painted = True
                except Exception:
                    pass
                if not painted:
                    continue
                d2 = acc.setdefault(cur, {"font": Counter(), "size": 0.0})
                if gs["font"]:
                    d2["font"][gs["font"]] += 1
                d2["size"] = max(d2["size"], gs["tf"] * tm_scale)

        for m, v in acc.items():
            font = v["font"].most_common(1)[0][0] if v["font"] else ""
            styles[(pindex, m)] = (font, round(v["size"], 1))
    return styles


def _elem_style(pdf, elem, style_by_page):
    """Dominant (font, size) of an element's own MCIDs, or None if unknown."""
    from collections import Counter
    pg = elem.get("/Pg")
    pindex = _page_index_of(pdf, pg) if pg is not None else None
    if pindex is None:
        return None
    seen = Counter()
    for m in _iter_mcids(elem.get("/K")):
        st = style_by_page.get((pindex, m))
        if st is not None:
            seen[st] += 1
    if not seen:
        return None
    return seen.most_common(1)[0][0]


def _styles_compatible(a, b) -> bool:
    """True if two fragments may belong to the same paragraph.

    Unknown style on either side -> fall back to permissive (True), so this
    guard can only PREVENT bad merges, never block ones the old logic made
    for reasons we cannot evaluate.
    """
    if a is None or b is None:
        return True
    font_a, size_a = a
    font_b, size_b = b
    if abs(size_a - size_b) > 0.6:
        return False
    if font_a != font_b:
        return False
    return True


def _page_index_of(pdf, page_obj):
    if page_obj is None:
        return None
    for idx, p in enumerate(pdf.pages):
        try:
            if p.obj.objgen == page_obj.objgen:
                return idx
        except Exception:
            continue
    return None


def _struct_type(elem) -> str:
    try:
        s = elem.get("/S")
        return str(s) if s is not None else ""
    except Exception:
        return ""


def _iter_mcids(k):
    """Yield MCIDs referenced directly by a /K value (ints or MCR dicts)."""
    items = list(k) if isinstance(k, pikepdf.Array) else [k]
    for it in items:
        try:
            if isinstance(it, pikepdf.Dictionary):
                if str(it.get("/Type", "")) == "/MCR" and it.get("/MCID") is not None:
                    yield int(it["/MCID"])
            else:
                yield int(it)
        except Exception:
            continue


def _as_klist(k):
    if k is None:
        return []
    return list(k) if isinstance(k, pikepdf.Array) else [k]


def _elem_text(pdf, elem, mcid_by_page) -> str:
    """Best-effort concatenated text of a <P> element from its MCID kids."""
    pg = elem.get("/Pg")
    pidx = _page_index_of(pdf, pg)
    if pidx is None or pidx not in mcid_by_page:
        return ""
    k = elem.get("/K")
    if k is None:
        return ""
    parts = [mcid_by_page[pidx].get(m, "") for m in _iter_mcids(k)]
    return _norm(" ".join(p for p in parts if p))


def _same_page(a, b) -> bool:
    pa, pb = a.get("/Pg"), b.get("/Pg")
    if pa is None or pb is None:
        return True  # no page info -> assume same (single-stream page)
    try:
        return pa.objgen == pb.objgen
    except Exception:
        return pa is pb


def _parenttree_page_array(st_root, page_obj):
    """Return the ParentTree /Nums value array for `page_obj` (indexed by MCID).

    Only the common flat ``/Nums`` layout is handled; returns None otherwise so
    the caller can skip the repoint safely.
    """
    sp = page_obj.get("/StructParents")
    if sp is None:
        return None
    try:
        key = int(sp)
    except Exception:
        return None
    pt = st_root.get("/ParentTree")
    if pt is None:
        return None
    nums = pt.get("/Nums")
    if nums is None:
        return None
    try:
        for i in range(0, len(nums) - 1, 2):
            if int(nums[i]) == key:
                val = nums[i + 1]
                return val if isinstance(val, pikepdf.Array) else None
    except Exception:
        return None
    return None


def _repoint_parenttree(st_root, page_obj, mcids, new_parent):
    """Point the given page MCIDs at `new_parent` in the ParentTree."""
    arr = _parenttree_page_array(st_root, page_obj)
    if arr is None:
        return
    for m in mcids:
        try:
            if 0 <= m < len(arr):
                arr[m] = new_parent
        except Exception:
            continue


def fix_pdf(in_path: str, out_path: str) -> int:
    """Merge line-split <P> siblings. Returns number of merges performed."""
    if os.environ.get("ORION_PARA_MERGE_DISABLE", "") == "1":
        pikepdf.open(in_path).save(out_path)
        print("paragraph_merge_fixer: disabled via env; copied through")
        return 0

    pdf = pikepdf.open(in_path)
    st_root = pdf.Root.get("/StructTreeRoot")
    if st_root is None:
        pdf.save(out_path)
        print("paragraph_merge_fixer: no StructTreeRoot; copied through")
        return 0

    mcid_by_page = _mcid_text_map(pdf)
    style_by_page = _mcid_style_map(pdf)

    merges = 0
    visited = set()

    def process_parent(parent):
        """Merge consecutive <P> children of `parent`; recurse into kids."""
        nonlocal merges
        try:
            key = parent.objgen if parent.is_indirect else id(parent)
        except Exception:
            key = id(parent)
        if key in visited:
            return
        visited.add(key)

        k = parent.get("/K")
        children = _as_klist(k)

        # Recurse into element children first so nested structure is handled
        # regardless of merges at this level.
        for c in children:
            if isinstance(c, pikepdf.Dictionary) and "/K" in c \
                    and _struct_type(c) not in ("/P", ""):
                process_parent(c)

        if not isinstance(k, pikepdf.Array) or len(children) < 2:
            return  # nothing to merge at this level

        new_children = []
        anchor = None          # current surviving <P> we are merging into
        anchor_text = ""

        for c in children:
            is_p = isinstance(c, pikepdf.Dictionary) and _struct_type(c) == "/P"
            if not is_p:
                anchor = None
                anchor_text = ""
                new_children.append(c)
                continue

            frag_text = _elem_text(pdf, c, mcid_by_page)

            if anchor is None:
                anchor = c
                anchor_text = frag_text
                new_children.append(c)
                continue

            # Join `c` into the anchor only if the anchor paragraph did not
            # end, `c` does not begin a new block-level unit, and both are on
            # the same page (cross-page merges would corrupt the per-page
            # marked-content parent tree).
            # Style guard: never fuse fragments set in a different font or
            # size.  A heading ("Executive Summary") has no terminal
            # punctuation, so the punctuation test alone would treat the
            # following body paragraph as its continuation and swallow it.
            join = (not _ends_paragraph(anchor_text)
                    and not _starts_new_block(frag_text)
                    and _same_page(anchor, c)
                    and _styles_compatible(
                        _elem_style(pdf, anchor, style_by_page),
                        _elem_style(pdf, c, style_by_page)))

            if join:
                a_kids = _as_klist(anchor.get("/K"))
                c_kids = _as_klist(c.get("/K"))
                # Reparent any MCR dicts so their /Parent points at the anchor.
                for ck in c_kids:
                    if isinstance(ck, pikepdf.Dictionary) and "/Parent" in ck:
                        ck["/Parent"] = anchor
                anchor["/K"] = pikepdf.Array(a_kids + c_kids)
                if anchor.get("/Pg") is None and c.get("/Pg") is not None:
                    anchor["/Pg"] = c.get("/Pg")
                # Repoint the absorbed MCIDs at the surviving <P> so the
                # ParentTree stays consistent (MCID -> parent element).
                pg_obj = c.get("/Pg") or anchor.get("/Pg")
                if pg_obj is not None:
                    _repoint_parenttree(st_root, pg_obj,
                                        list(_iter_mcids(c.get("/K"))), anchor)
                anchor_text = _norm(anchor_text + " " + frag_text)
                merges += 1
                # `c` is dropped (not appended) -> removed from the tree.
            else:
                anchor = c
                anchor_text = frag_text
                new_children.append(c)

        if len(new_children) != len(children):
            parent["/K"] = pikepdf.Array(new_children)

    root_k = st_root.get("/K")
    for child in _as_klist(root_k):
        if isinstance(child, pikepdf.Dictionary):
            process_parent(child)

    pdf.save(out_path)
    print(f"paragraph_merge_fixer: merged {merges} split paragraph fragment(s)")
    return merges


def main(argv):
    if len(argv) != 3:
        print("Usage: python3 paragraph_merge_fixer.py <input.pdf> <output.pdf>",
              file=sys.stderr)
        return 2
    try:
        fix_pdf(argv[1], argv[2])
        return 0
    except Exception as exc:  # pragma: no cover
        import traceback
        print(f"paragraph_merge_fixer: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
