#!/usr/bin/env python3
"""
heading_normalizer.py

Builds a real heading hierarchy so screen-reader users can navigate the
document, and clears the "Repeated H1 / Empty H1" defects.

The problem this solves
-----------------------
PDFix's AddTags() tends to mark the repeating page banner as <H1> on every
page and to leave the document's ACTUAL section headings tagged as <P>.  On a
typical 8-page report that yields:

    H1 p1: "2023 Legislative Summary"    <- the running page banner
    H1 p2: ""   (empty shell)
    H1 p3: ""   (empty shell)
    ...  6 empty H1 elements ...
    H1 p5: "2023 Legislative Summary"    <- the banner again

while "Executive Summary", "Below is a list of our bills...", "Oregon
Administrative Rules & Implementation" are all <P>.  Result: heading
navigation is useless (8 entries, mostly blank, no outline), and QA reports
"Repeated H1 tags" and "Empty H1 tag".

What it does
------------
1. DROP empty heading elements (no MCIDs / no text). Zero risk: nothing to lose.

2. DETECT real headings by TYPOGRAPHY, not by hardcoded strings, so this
   generalises across documents.  A <P> is a heading candidate when its text
   is short, is not sentence-like body copy, and its (font, size) differs from
   the document's body style by being either larger or bold.

   Effective size = Tf size * text-matrix scale (many producers emit "1 Tf"
   and carry the real size in the Tm).  The q/Q graphics-state stack is
   tracked, since it saves/restores the font — without that a bold face leaks
   past its Q and body text is misread as bold.

3. ASSIGN LEVELS by size rank: the largest heading style becomes H1, the next
   H2, and so on (capped at H6).  Ranking by size guarantees no skipped
   levels among the styles actually present.

4. DE-DUPLICATE the running banner: text that repeats as a heading on 3+ pages
   is a running header.  The FIRST occurrence is kept (it is the document
   title); later occurrences are removed from the structure tree and their
   content is wrapped as /Artifact, which is what a running header should be.
   Their ParentTree slots are nulled.

Only <P> elements are considered for promotion.  Table headers are <TH> and
are left alone.

Usage
-----
    python3 heading_normalizer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator
from pikepdf import ContentStreamInstruction as CSI

# This module is executed as a subprocess (`python heading_normalizer.py in out`)
# by the remediation pipeline, so the package-relative import is not always
# available.  Support both entry paths.
try:  # imported as part of the package
    from .title_tag import (
        TITLE_TAG,
        apply_title_tag,
        document_title,
        ensure_title_rolemap,
        matches_document_title,
        title_key,
    )
except ImportError:  # executed as a standalone script
    from title_tag import (  # type: ignore[no-redef]
        TITLE_TAG,
        apply_title_tag,
        document_title,
        ensure_title_rolemap,
        matches_document_title,
        title_key,
    )

_WS = set(b" \t\r\n\x00\x0c")
_HEADING_MAX_CHARS = 120
_BANNER_MIN_PAGES = 2

_NON_HEADING_CONTAINERS = {"/Table", "/TR", "/TH", "/TD", "/L", "/LI", "/LBody"}

_ARTIFACT_BMC = CSI([Name("/Artifact")], Operator("BMC"))


def _pagination_artifact(subtype=None) -> CSI:
    """Build ``/Artifact <</Type /Pagination [/Subtype …]>> BDC``.

    A BARE ``/Artifact BMC`` is indistinguishable from content that PDFix
    artifacted by mistake, and final_structure_repair.reclaim_artifacts() pulls
    any readable top-level artifact back into the tree as a <P>.  That is how
    every running header this pass removed came back: two stages undoing each
    other.  Declaring the artifact's type (PDF 32000-1 §14.8.2.2) is both the
    spec-correct way to mark pagination furniture AND the signal reclaim needs
    to leave it alone.
    """
    props = {"/Type": Name("/Pagination")}
    if subtype is not None:
        props["/Subtype"] = subtype
    return CSI([Name("/Artifact"), Dictionary(props)], Operator("BDC"))


def _banner_subtype(pdf, pindex, mcids):
    """Classify a banner as /Header or /Footer from where it sits on the page.

    Returns None when the position is ambiguous or unreadable — /Subtype is
    optional, so emitting /Type /Pagination alone is still valid and still
    protects the artifact from reclamation.
    """
    try:
        page = pdf.pages[pindex]
        mb = [float(x) for x in page.obj.MediaBox]
        height = mb[3] - mb[1]
        if height <= 0:
            return None
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return None

    ys, depth = [], 0
    for ins in instrs:
        o = _op(ins)
        if o in ("BDC", "BMC"):
            m = _mcid_of_bdc_ins(ins) if o == "BDC" else None
            if depth > 0:
                depth += 1
            elif m is not None and m in mcids:
                depth = 1
        elif o == "EMC":
            if depth > 0:
                depth -= 1
        elif o == "Tm" and depth > 0:
            try:
                ys.append(float(ins.operands[5]))
            except Exception:
                pass

    if not ys:
        return None
    top = max(ys)
    if top > height * 0.75:
        return Name("/Header")
    if top < height * 0.25:
        return Name("/Footer")
    return None


_EMC = CSI([], Operator("EMC"))


def _op(instr) -> str:
    try:
        return str(instr.operator)
    except Exception:
        return "?"


def _klist(k):
    if k is None:
        return []
    return list(k) if isinstance(k, pikepdf.Array) else [k]


def _kids(elem):
    return _klist(elem.get("/K"))


def _stype(elem) -> str:
    try:
        s = elem.get("/S")
        return str(s) if s is not None else ""
    except Exception:
        return ""


def _iter_mcids(k):
    for c in _klist(k):
        if isinstance(c, pikepdf.Dictionary):
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


def _page_index(pdf, page_obj):
    if page_obj is None:
        return None
    try:
        og = page_obj.objgen
    except Exception:
        return None
    for i, p in enumerate(pdf.pages):
        if p.obj.objgen == og:
            return i
    return None


def _scan_pages(pdf):
    """(page_index, mcid) -> {'text': str, 'font': str, 'size': float}"""
    out = {}
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
        mc, gstack = [], []
        gs = {"font": None, "tf": 1.0}
        tm = 1.0

        for ins in instrs:
            op = _op(ins)
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
                mc.append(m)
            elif op == "EMC":
                if mc:
                    mc.pop()
            elif op == "Tf":
                try:
                    gs["font"] = fmap.get(str(ins.operands[0]), str(ins.operands[0]))
                    gs["tf"] = float(ins.operands[1])
                except Exception:
                    pass
            elif op == "Tm":
                try:
                    a, b, c, d = [float(x) for x in ins.operands[:4]]
                    tm = math.sqrt(abs(a * d - b * c)) or 1.0
                except Exception:
                    pass
            elif op in ("Tj", "TJ", "'", '"'):
                cur = next((x for x in reversed(mc) if x is not None), None)
                if cur is None:
                    continue
                raw = b""
                try:
                    if op == "TJ":
                        for e in ins.operands[0]:
                            if isinstance(e, pikepdf.String):
                                raw += bytes(e)
                    else:
                        s = ins.operands[-1]
                        if isinstance(s, pikepdf.String):
                            raw += bytes(s)
                except Exception:
                    pass
                d2 = acc.setdefault(cur, {"raw": b"", "font": Counter(), "size": 0.0})
                d2["raw"] += raw
                if any(ch not in _WS for ch in raw):
                    if gs["font"]:
                        d2["font"][gs["font"]] += 1
                    d2["size"] = max(d2["size"], gs["tf"] * tm)

        for m, v in acc.items():
            out[(pindex, m)] = {
                "text": v["raw"].decode("latin-1", "replace").strip(),
                "font": v["font"].most_common(1)[0][0] if v["font"] else "",
                "size": round(v["size"], 1),
            }
    return out


def _top_level_mcids(pdf):
    """(page_index) -> set of MCIDs whose BDC is NOT nested inside another
    tagged marked-content sequence.

    Only these may be converted to /Artifact.  Converting a NESTED sequence
    would place an artifact inside tagged content — itself a PDF/UA violation
    ("Artifact present inside tagged content"), which is exactly the defect
    nested_artifact_unwrapper exists to remove.  A banner whose sequence is
    nested is therefore left in the tree and demoted instead.
    """
    safe = {}
    for pindex, page in enumerate(pdf.pages):
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue
        s_set = set()
        depth = 0          # nesting depth of TAGGED (non-artifact) sequences
        for ins in instrs:
            op = _op(ins)
            if op in ("BDC", "BMC"):
                is_art = False
                m = None
                try:
                    ops = ins.operands
                    is_art = str(ops[0]) == "/Artifact"
                    if op == "BDC" and len(ops) >= 2 \
                            and isinstance(ops[1], pikepdf.Dictionary) \
                            and "/MCID" in ops[1]:
                        m = int(ops[1]["/MCID"])
                except Exception:
                    pass
                if m is not None and depth == 0:
                    s_set.add(m)
                if not is_art:
                    depth += 1
                else:
                    depth += 1
            elif op == "EMC":
                if depth > 0:
                    depth -= 1
        safe[pindex] = s_set
    return safe


def _scan_ops(page):
    """Text-showing operators with their style and enclosing MC sequence.

    Returns (instrs, ops) where each op is
        {i, mcid, bdc, emc, font, size, text}
    `bdc`/`emc` are the indices of the enclosing marked-content sequence.
    """
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return [], []

    res_ = page.get("/Resources")
    fonts = (res_.get("/Font") if res_ is not None else None) or {}
    fmap = {}
    for k, v in fonts.items():
        try:
            fmap[str(k)] = str(v.get("/BaseFont", "?"))
        except Exception:
            fmap[str(k)] = "?"

    partner = {}
    stk = []
    for i, ins in enumerate(instrs):
        o = _op(ins)
        if o in ("BDC", "BMC"):
            stk.append(i)
        elif o == "EMC":
            if stk:
                partner[stk.pop()] = i

    ops = []
    mc = []
    gs = {"font": None, "tf": 1.0}
    gstack = []
    tm = 1.0
    for i, ins in enumerate(instrs):
        o = _op(ins)
        if o == "q":
            gstack.append(dict(gs))
        elif o == "Q":
            if gstack:
                gs = gstack.pop()
        elif o in ("BDC", "BMC"):
            m = None
            if o == "BDC":
                try:
                    oo = ins.operands
                    if len(oo) >= 2 and isinstance(oo[1], pikepdf.Dictionary) \
                            and "/MCID" in oo[1]:
                        m = int(oo[1]["/MCID"])
                except Exception:
                    m = None
            mc.append((i, m))
        elif o == "EMC":
            if mc:
                mc.pop()
        elif o == "Tf":
            try:
                gs["font"] = fmap.get(str(ins.operands[0]), str(ins.operands[0]))
                gs["tf"] = float(ins.operands[1])
            except Exception:
                pass
        elif o == "Tm":
            try:
                a, b, c, d = [float(x) for x in ins.operands[:4]]
                tm = math.sqrt(abs(a * d - b * c)) or 1.0
            except Exception:
                pass
        elif o in ("Tj", "TJ", "'", '"'):
            cur = bdc = None
            for bi, m in reversed(mc):
                if m is not None:
                    cur, bdc = m, bi
                    break
            if cur is None:
                continue
            raw = b""
            try:
                if o == "TJ":
                    for e in ins.operands[0]:
                        if isinstance(e, pikepdf.String):
                            raw += bytes(e)
                else:
                    sx = ins.operands[-1]
                    if isinstance(sx, pikepdf.String):
                        raw += bytes(sx)
            except Exception:
                pass
            ops.append({"i": i, "mcid": cur, "bdc": bdc,
                        "emc": partner.get(bdc),
                        "font": gs["font"] or "", "size": gs["tf"] * tm,
                        "text": raw})
    return instrs, ops


def _split_leading_headings(pdf, st, body_font, body_size, res):
    """Split a heading that PDFix fused into the body paragraph.

    PDFix often emits a section heading and the paragraph that follows it as a
    SINGLE marked-content sequence:

        /P <</MCID 56>> BDC
            (Oregon Administrative Rules & Implementation)  <- Meiryo-Bold
            (Each division should consider what new rules...)  <- Calibri
        EMC

    No structure-level fix can separate these, because there is only one MCID.
    This splits the sequence in two — heading run and body run — giving each
    its own MCID and its own <P>.  The promotion pass that follows then turns
    the heading half into a real <H*>.

    Only a LEADING run whose style differs from the body (bold, or larger) and
    which is followed by body-styled text in the same sequence is split.
    """
    page_of = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}

    # element that owns each (page, mcid)
    owner = {}
    seen = set()

    def collect(node):
        for c in _kids(node):
            if isinstance(c, pikepdf.Dictionary) and "/S" in c:
                key = c.objgen if c.is_indirect else id(c)
                if key in seen:
                    continue
                seen.add(key)
                pi = _page_index(pdf, c.get("/Pg"))
                # Consider <P> AND existing <H*>.  A sequence that fuses a
                # heading (or a running banner) with the body/table text that
                # follows it is very often ALREADY tagged /H1 by PDFix, simply
                # because the sequence happens to START with large text.
                # Restricting the split to /P therefore skips precisely the
                # worst cases -- leaving a heading whose text is the banner
                # plus a paragraph of unrelated body copy welded onto it.
                if re.fullmatch(r"/P|/H[1-6]?", _stype(c)) and pi is not None:
                    for m in _iter_mcids(c.get("/K")):
                        owner[(pi, m)] = (c, node)
                collect(c)

    collect(st)
    if not owner:
        return

    pt = st.get("/ParentTree")

    for pi, page in enumerate(pdf.pages):
        instrs, ops = _scan_ops(page)
        if not ops:
            continue

        max_mcid = -1
        for ins in instrs:
            if _op(ins) == "BDC":
                m = _mcid_of_bdc_ins(ins)
                if m is not None:
                    max_mcid = max(max_mcid, m)

        by_seq = {}
        for o in ops:
            by_seq.setdefault(o["bdc"], []).append(o)

        plans = []
        for bdc, seq_ops in by_seq.items():
            if bdc is None:
                continue
            seq_ops.sort(key=lambda z: z["i"])
            mcid = seq_ops[0]["mcid"]
            own = owner.get((pi, mcid))
            if own is None:
                continue

            glyph_ops = [o for o in seq_ops if _has_glyph_bytes(o["text"])]
            if not glyph_ops:
                continue
            first = glyph_ops[0]

            def is_head(o):
                return ((_is_bold(o["font"]) and not _is_bold(body_font))
                        or o["size"] > body_size + 0.6)

            if not is_head(first):
                continue

            # Leading run = ops sharing the FIRST op's exact style.  Splitting
            # on any style change (not merely heading-vs-body) also separates
            # two headings of different levels that were emitted in the same
            # sequence, e.g. a 14pt section title immediately followed by an
            # 11pt sub-heading.
            def style(o):
                return (o["font"], round(o["size"], 1))

            s0 = style(first)
            lead = []
            for o in seq_ops:
                if not _has_glyph_bytes(o["text"]):
                    lead.append(o)
                    continue
                if style(o) == s0:
                    lead.append(o)
                else:
                    break
            lead = [o for o in lead if _has_glyph_bytes(o["text"])]
            if not lead:
                continue
            rest = [o for o in seq_ops if o["i"] > lead[-1]["i"]
                    and _has_glyph_bytes(o["text"])]
            if not rest:
                continue        # whole sequence is the heading: nothing to split
            head_text = b"".join(o["text"] for o in lead).decode(
                "latin-1", "replace").strip()
            if not _looks_like_heading_text(head_text):
                continue
            plans.append({"bdc": bdc, "emc": seq_ops[0]["emc"],
                          "last_head_i": lead[-1]["i"], "mcid": mcid,
                          "elem": own[0], "parent": own[1]})

        if not plans:
            continue

        plan_by_bdc = {p["bdc"]: p for p in plans}
        new_instrs = []
        alloc = max_mcid + 1
        applied = []
        i = 0
        n = len(instrs)
        while i < n:
            p = plan_by_bdc.get(i)
            if p is None or p["emc"] is None:
                new_instrs.append(instrs[i])
                i += 1
                continue

            head = instrs[i + 1:p["last_head_i"] + 1]
            tail = instrs[p["last_head_i"] + 1:p["emc"]]
            body_mcid = alloc
            alloc += 1

            new_instrs.append(CSI([Name("/P"), Dictionary(MCID=p["mcid"])],
                                  Operator("BDC")))
            new_instrs.extend(head)
            new_instrs.append(_EMC)
            new_instrs.append(CSI([Name("/P"), Dictionary(MCID=body_mcid)],
                                  Operator("BDC")))
            new_instrs.extend(tail)
            new_instrs.append(_EMC)

            applied.append({"elem": p["elem"], "parent": p["parent"],
                            "head_mcid": p["mcid"], "body_mcid": body_mcid})
            i = p["emc"] + 1

        if not applied:
            continue

        page.Contents = pdf.make_stream(
            pikepdf.unparse_content_stream(new_instrs))

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
            elem, parent = a["elem"], a["parent"]
            # existing element keeps the BODY half (+ any other MCIDs it had)
            old = [m for m in _iter_mcids(elem.get("/K"))
                   if m != a["head_mcid"]]
            elem["/K"] = Array([a["body_mcid"]] + old)

            # It now holds body copy, not the heading run.  If it was tagged as
            # a heading, that tag belonged to the leading run we just split off
            # -- leaving it would keep a paragraph welded to an <H*>.  The
            # split-off head element is re-evaluated by the promotion pass
            # below and gets the right level (or is artifacted, if it is the
            # running banner).
            if re.fullmatch(r"/H[1-6]?", _stype(elem)):
                elem["/S"] = Name("/P")

            head_p = pdf.make_indirect(pikepdf.Dictionary(
                Type=Name("/StructElem"), S=Name("/P"), Pg=page.obj,
                P=parent, K=Array([a["head_mcid"]])))

            k = _kids(parent)
            new_k = []
            for x in k:
                if isinstance(x, pikepdf.Dictionary) and x.is_indirect \
                        and elem.is_indirect and x.objgen == elem.objgen:
                    new_k.append(head_p)       # heading goes first
                new_k.append(x)
            parent["/K"] = Array(new_k)

            if arr is not None:
                while len(arr) <= max(a["head_mcid"], a["body_mcid"]):
                    arr.append(pikepdf.Object.parse(b"null"))
                arr[a["head_mcid"]] = head_p
                arr[a["body_mcid"]] = elem

            res["headings_split"] = res.get("headings_split", 0) + 1


def _mcid_of_bdc_ins(ins):
    try:
        oo = ins.operands
        if len(oo) >= 2 and isinstance(oo[1], pikepdf.Dictionary) \
                and "/MCID" in oo[1]:
            return int(oo[1]["/MCID"])
    except Exception:
        pass
    return None


def _strip_mcids_from_tree(node, page_obj, mcids):
    """Detach the given page MCIDs from any structure element referencing them.

    Used after content on a page has been converted to /Artifact: an artifacted
    MCID must no longer be reachable from the structure tree, or the tree still
    claims content that is now marked as non-content.  Only elements whose /Pg
    is this page are touched, since MCIDs are only unique per page.
    """
    if not isinstance(node, pikepdf.Dictionary):
        return
    kids = node.get("/K")
    if kids is None:
        return

    pg = node.get("/Pg")
    try:
        same_page = (pg is not None and pg.objgen == page_obj.objgen)
    except Exception:
        same_page = False

    items = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
    keep = []
    for k in items:
        if isinstance(k, pikepdf.Dictionary):
            if str(k.get("/Type", "")) == "/MCR" and "/MCID" in k:
                kpg = k.get("/Pg") or pg
                try:
                    kpg_same = (kpg is not None
                                and kpg.objgen == page_obj.objgen)
                except Exception:
                    kpg_same = False
                try:
                    if kpg_same and int(k["/MCID"]) in mcids:
                        continue          # drop this MCR
                except Exception:
                    pass
            else:
                _strip_mcids_from_tree(k, page_obj, mcids)
            keep.append(k)
            continue
        # bare int MCID -- belongs to this element's /Pg
        try:
            if same_page and int(k) in mcids:
                continue                  # drop this MCID reference
        except Exception:
            pass
        keep.append(k)

    if len(keep) != len(items):
        node["/K"] = Array(keep)


def _has_glyph_bytes(b: bytes) -> bool:
    return any(c not in _WS for c in b)


def _elem_info(pdf, elem, scan):
    pindex = _page_index(pdf, elem.get("/Pg"))
    mcids = list(_iter_mcids(elem.get("/K")))
    texts, fonts, size = [], Counter(), 0.0
    for m in mcids:
        d = scan.get((pindex, m))
        if not d:
            continue
        if d["text"]:
            texts.append(d["text"])
        if d["font"]:
            fonts[d["font"]] += 1
        size = max(size, d["size"])
    return {
        "page": pindex,
        "mcids": mcids,
        "text": " ".join(texts).strip(),
        "font": fonts.most_common(1)[0][0] if fonts else "",
        "size": size,
    }


_SUBSET_PREFIX = re.compile(r"^/?[A-Z]{6}\+")


def _font_key(font: str) -> str:
    """Font identity with the subset prefix stripped.

    The same typeface is embedded once per subset, so "/GHWVEL+Meiryo-Bold" and
    "/ABCDEF+Meiryo-Bold" are the SAME style and must produce the same key —
    otherwise one heading style is split across several ranks.
    """
    return _SUBSET_PREFIX.sub("", (font or "").lstrip("/")).strip().casefold()


def _style_key(info) -> tuple:
    """The typographic identity of a heading: rounded size + font family.

    Size alone is not enough. In real Word documents two heading levels
    routinely share a point size and differ only in typeface — ranking on size
    collapses them into one level. Size is rounded to 1dp so that 11.0 and
    11.04 (the same style, different text-matrix rounding) do not split.
    """
    return (round(float(info.get("size") or 0.0), 1), _font_key(info.get("font", "")))


def _is_bold(font: str) -> bool:
    f = font.lower()
    return "bold" in f or "black" in f or "heavy" in f or "semib" in f


def _banner_key(t: str) -> str:
    """Normalized key for running-header detection.

    A running header often absorbs the page number ("2023 Legislative Summary"
    on one page, "2023 Legislative Summary 4" on another), so exact string
    equality misses the repeat.  Compare on letters only, lowercased.
    """
    return re.sub(r"[^a-z]", "", t.lower())


def _looks_like_heading_text(t: str) -> bool:
    if not t or len(t) > _HEADING_MAX_CHARS:
        return False
    # body copy usually ends in a period and contains several sentences
    if t.count(". ") >= 2:
        return False
    words = t.split()
    if len(words) > 20:
        return False
    return True


def normalize_headings(in_path: str, out_path: str) -> dict:
    res = {"empty_headings_removed": 0, "promoted": 0, "banner_artifacted": 0,
           "banner_demoted": 0, "levels": {}, "retagged_existing": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("heading_normalizer: no StructTreeRoot; copied through")
        return res

    scan = _scan_pages(pdf)
    safe_mcids = _top_level_mcids(pdf)

    # ---- collect all elements with their parent ---------------------------
    elems = []          # (elem, parent, ancestor_chain)
    seen = set()

    def walk(node, chain):
        for c in _kids(node):
            if isinstance(c, pikepdf.Dictionary) and "/S" in c:
                key = c.objgen if c.is_indirect else id(c)
                if key in seen:
                    continue
                seen.add(key)
                elems.append((c, node, chain))
                walk(c, chain + [_stype(c)])

    walk(st, [])

    # ---- body style = most common (font,size) among substantial <P> -------
    body_counter = Counter()
    for e, _p, _ch in elems:
        if _stype(e) != "/P":
            continue
        info = _elem_info(pdf, e, scan)
        if len(info["text"]) >= 120 and info["size"] > 0:
            body_counter[(info["font"], info["size"])] += 1
    body_font, body_size = (body_counter.most_common(1)[0][0]
                            if body_counter else ("", 11.0))

    # ---- 0. split headings that PDFix fused into the body paragraph -------
    res["headings_split"] = 0
    if os.environ.get("ORION_HEADING_SPLIT_DISABLE", "") != "1":
        # Repeat: the "rest" half of a split may itself start with a heading
        # (title -> sub-heading -> body all in one original sequence).
        for _round in range(4):
            before = res["headings_split"]
            try:
                _split_leading_headings(pdf, st, body_font, body_size, res)
            except Exception as exc:   # never fail the whole pass on this
                print(f"heading_normalizer: split skipped: {exc}",
                      file=sys.stderr)
                break
            if res["headings_split"] == before:
                break
        if res["headings_split"]:
            # content stream changed -> rescan and rebuild the element list
            scan = _scan_pages(pdf)
            safe_mcids = _top_level_mcids(pdf)
            elems = []
            seen = set()
            walk(st, [])

    # ---- 1. remove empty heading elements ---------------------------------
    for e, parent, _ch in list(elems):
        if not re.fullmatch(r"/H[1-6]?", _stype(e)):
            continue
        info = _elem_info(pdf, e, scan)
        has_elem_kid = any(isinstance(c, pikepdf.Dictionary) and "/S" in c
                           for c in _kids(e))
        if not info["text"] and not has_elem_kid:
            k = parent.get("/K")
            if isinstance(k, pikepdf.Array):
                keep = [c for c in k
                        if not (isinstance(c, pikepdf.Dictionary)
                                and c.is_indirect and e.is_indirect
                                and c.objgen == e.objgen)]
                if len(keep) != len(k):
                    parent["/K"] = Array(keep)
                    res["empty_headings_removed"] += 1

    # refresh element list after removals
    elems = []
    seen = set()
    walk(st, [])

    # ---- 2. find heading candidates (existing H* + promotable <P>) --------
    cands = []          # (elem, parent, info)
    for e, parent, chain in elems:
        s = _stype(e)
        info = _elem_info(pdf, e, scan)
        if not info["text"]:
            continue
        # An existing <Title> from a previous run must stay in the candidate
        # list: it consumes level 1, and dropping it here would let the next
        # heading claim level 1 and produce two H1s after role resolution.
        if s == TITLE_TAG or re.fullmatch(r"/H[1-6]?", s):
            cands.append((e, parent, info))
            continue
        if s != "/P":
            continue
        # A <P> inside a table cell or a list item is CELL/ITEM content, not a
        # document heading — bold table headers are <TH> and already carry
        # their semantics.  Promoting them would invent a bogus outline.
        if any(t in _NON_HEADING_CONTAINERS for t in chain):
            continue
        bigger = info["size"] > body_size + 0.6
        bold = _is_bold(info["font"]) and not _is_bold(body_font)
        if (bigger or bold) and _looks_like_heading_text(info["text"]):
            cands.append((e, parent, info))

    # ---- 3. running-banner detection --------------------------------------
    text_pages = {}
    for _e, _p, info in cands:
        text_pages.setdefault(_banner_key(info["text"]), set()).add(info["page"])
    banner_keys = {k for k, pages in text_pages.items()
                   if k and len(pages) >= _BANNER_MIN_PAGES}

    # ---- 4. level assignment by STYLE rank --------------------------------
    #
    # Rank by (size, font family), not size alone.  Two heading levels sharing
    # a point size and differing only in typeface are extremely common in Word
    # documents, and ranking on size collapses them into a single level — the
    # exact defect where three H2s came out as H3 in the legislative-summary
    # sample (all Meiryo-Bold 11pt, while the genuine H3s were Calibri-Bold
    # 11pt).
    #
    # Ties on size are broken by FIRST APPEARANCE in reading order: `cands` is
    # in document order, so the style that introduces itself earlier is the
    # shallower one.  That is what a human infers from the same evidence.
    first_seen: dict[tuple, int] = {}
    for _i, (_e, _p, info) in enumerate(cands):
        if info["size"] > 0:
            first_seen.setdefault(_style_key(info), _i)

    ranked = sorted(first_seen, key=lambda s: (-s[0], first_seen[s]))
    level_of = {style: min(i + 1, 6) for i, style in enumerate(ranked)}
    res["heading_styles"] = {f"{s[0]}/{s[1]}": lv for s, lv in level_of.items()}

    # ---- 4b. document title ------------------------------------------------
    # The document title is not a heading — it is the <Title> of the document.
    # Under TITLE_MODE "rolemap" it is role-mapped to H1, so it OCCUPIES level
    # 1 and the heading after it correctly stays at H2.  See title_tag.py.
    doc_key = title_key(document_title(pdf))
    title_applied = False
    res["title_tagged"] = 0

    def _try_title(elem, info) -> bool:
        """Retag *elem* as <Title> if it is the document title. One per document."""
        nonlocal title_applied
        if title_applied or not doc_key:
            return False
        if not matches_document_title(info["text"], doc_key):
            return False
        if not apply_title_tag(pdf, elem):
            return False
        title_applied = True
        res["title_tagged"] = 1
        res["levels"][TITLE_TAG.lstrip("/")] = 1
        return True

    # ---- 5. apply ---------------------------------------------------------
    banner_seen = set()
    artifact_targets = {}      # page_index -> set(mcid)
    style_level: dict[tuple, int] = {}   # style key -> level, once assigned

    # PDF/UA "nesting of heading levels": a heading may not be MORE than one
    # level deeper than the heading immediately before it in reading order,
    # no matter what size-rank (step 4) computed.  Size-rank is global and
    # blind to document order, so a one-off larger/bold false-positive
    # candidate (e.g. a bold lead-in sentence before a bulleted list) can
    # consume an intermediate rank and push every *real* heading after it
    # deeper than it should go.  `cands` is in document reading order
    # (built from the same DFS walk used for the struct tree), so a running
    # clamp here is sufficient and doesn't require the typography heuristics
    # above to be perfect.  Going SHALLOWER is always legal per the spec, so
    # only the deeper direction is clamped.
    prev_level = 0

    for e, parent, info in cands:
        t = info["text"]
        bkey = _banner_key(t)

        # Idempotent re-run: the element is already a <Title>.  Leave it alone,
        # re-assert the RoleMap entry (a later stage may have rebuilt the
        # StructTreeRoot), and record that level 1 is taken.
        if _stype(e) == TITLE_TAG:
            ensure_title_rolemap(pdf)
            title_applied = True
            res["title_tagged"] = 1
            res["levels"][TITLE_TAG.lstrip("/")] = 1
            prev_level = 1
            # The <Title> IS the first occurrence of its banner text.  Claim the
            # banner key here, otherwise the next repeat of the running header
            # is mistaken for the first occurrence and promoted to H1.
            if bkey in banner_keys:
                banner_seen.add(bkey)
            continue

        if bkey in banner_keys:
            if bkey not in banner_seen:
                banner_seen.add(bkey)       # first occurrence = document title
                lvl = 1
                # Prefer a real <Title> tag when this banner IS the document
                # title.  It role-maps to H1, so level 1 is still consumed and
                # prev_level stays 1 — the next heading remains H2.
                if _try_title(e, info):
                    res["retagged_existing"] += 1
                else:
                    if _stype(e) != "/H1":
                        e["/S"] = Name("/H1")
                        res["retagged_existing"] += 1
                    res["levels"]["H1"] = res["levels"].get("H1", 0) + 1
                prev_level = lvl
                continue
            # Later occurrence = a running header.  Artifact it ONLY if every
            # one of its marked-content sequences is top-level; artifacting a
            # nested sequence would create "Artifact inside tagged content".
            pg_safe = safe_mcids.get(info["page"], set())
            can_artifact = (info["page"] is not None
                            and info["mcids"]
                            and all(m in pg_safe for m in info["mcids"]))
            if can_artifact:
                k = parent.get("/K")
                if isinstance(k, pikepdf.Array):
                    keep = [c for c in k
                            if not (isinstance(c, pikepdf.Dictionary)
                                    and c.is_indirect and e.is_indirect
                                    and c.objgen == e.objgen)]
                    if len(keep) != len(k):
                        parent["/K"] = Array(keep)
                artifact_targets.setdefault(info["page"], set()).update(info["mcids"])
                res["banner_artifacted"] += 1
            else:
                # Cannot safely artifact -> keep it tagged, but demote it out
                # of the heading outline so it is not a repeated H1.
                if _stype(e) != "/P":
                    e["/S"] = Name("/P")
                res["banner_demoted"] = res.get("banner_demoted", 0) + 1
            continue

        # Document title that is NOT a repeated banner (single-page docs, or a
        # title that appears only on the cover).  Only the FIRST heading-level
        # element in reading order is eligible: a mid-document heading that
        # happens to repeat the title text is a section heading, not the title.
        if prev_level == 0 and _try_title(e, info):
            res["retagged_existing"] += 1
            prev_level = 1            # <Title> role-maps to H1 and consumes level 1
            continue

        # A style keeps the level it was first given ("sticky").  Without this,
        # the no-skip clamp assigns a level from whatever heading happened to
        # precede this one, so the SAME style drifts between levels depending on
        # its neighbours — the run of Calibri-Bold 11pt headings would walk H3,
        # H4, H5 as the clamp ratcheted downward.
        style = _style_key(info)
        sticky = style_level.get(style)
        intended = sticky if sticky is not None else level_of.get(style, 2)

        # The clamp still applies on every occurrence, downward only: a sticky
        # level may never introduce a skip relative to the previous heading.
        # Going shallower is always legal, so only the deeper direction moves.
        lvl = min(intended, prev_level + 1)
        if lvl != intended:
            res["levels_clamped"] = res.get("levels_clamped", 0) + 1
        if sticky is None:
            style_level[style] = lvl
        prev_level = lvl
        tag = f"/H{lvl}"
        was = _stype(e)
        if was != tag:
            e["/S"] = Name(tag)
            if was == "/P":
                res["promoted"] += 1
            else:
                res["retagged_existing"] += 1
        res["levels"][f"H{lvl}"] = res["levels"].get(f"H{lvl}", 0) + 1

    # ---- 6. artifact the removed banner MCIDs in the content stream -------
    #
    # An /Artifact sequence must contain NO tagged marked content.  The banner
    # sequence we are about to artifact can itself CONTAIN a nested tagged BDC
    # -- typically an orphan heading BDC left in the stream after step 1 pulled
    # its (empty) struct element out of the tree.  Simply swapping the OUTER
    # BDC for an Artifact BMC and passing the inner BDC through unchanged
    # leaves that tagged sequence sitting inside an artifact, which is exactly
    # the PDF/UA defect "tagged content present inside an artifact".
    # `_top_level_mcids` only guarantees the target is not nested INSIDE other
    # tagged content; it says nothing about what the target CONTAINS.  So every
    # nested tagged sequence swallowed by the artifact is converted to an
    # artifact too, and its MCID is detached from the structure tree.
    for pindex, mcids in artifact_targets.items():
        page = pdf.pages[pindex]
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue
        out, depth_replace = [], 0
        changed = False
        nested_mcids = set()      # tagged MCIDs absorbed into the artifact
        # Typed artifact for this page's banner, so reclaim_artifacts() can tell
        # "deliberately artifacted running header" from "PDFix artifacted real
        # body text by mistake". Both the banner sequence and anything it
        # swallows are marked, so no fragment is left looking accidental.
        art_ins = _pagination_artifact(_banner_subtype(pdf, pindex, mcids))
        for ins in instrs:
            op = _op(ins)
            if op in ("BDC", "BMC"):
                m = _mcid_of_bdc_ins(ins) if op == "BDC" else None
                is_art = False
                try:
                    is_art = str(ins.operands[0]) == "/Artifact"
                except Exception:
                    is_art = False

                # start of the banner sequence -> becomes the artifact
                if m is not None and m in mcids and depth_replace == 0:
                    out.append(art_ins)
                    depth_replace = 1
                    changed = True
                    continue

                if depth_replace:
                    depth_replace += 1
                    if not is_art:
                        # tagged content inside an artifact -> artifact it too
                        if m is not None:
                            nested_mcids.add(m)
                        out.append(art_ins)
                        continue
            elif op == "EMC" and depth_replace:
                depth_replace -= 1
                out.append(_EMC)
                continue
            out.append(ins)
        if changed:
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
            res["nested_tagged_artifacted"] = (
                res.get("nested_tagged_artifacted", 0) + len(nested_mcids))

            all_mcids = set(mcids) | nested_mcids

            # detach every artifacted MCID from the structure tree
            _strip_mcids_from_tree(st, page.obj, all_mcids)

            # null the ParentTree slots of the artifacted MCIDs
            pt = st.get("/ParentTree")
            if pt is not None and "/Nums" in pt:
                nums = list(pt["/Nums"])
                sp = page.obj.get("/StructParents")
                key = int(sp) if sp is not None else pindex
                for i in range(0, len(nums) - 1, 2):
                    if int(nums[i]) == key and isinstance(nums[i + 1], pikepdf.Array):
                        arr = nums[i + 1]
                        for m in all_mcids:
                            if 0 <= m < len(arr):
                                try:
                                    arr[m] = pikepdf.Object.parse(b"null")
                                except Exception:
                                    pass
                        break

    pdf.save(out_path)
    print(f"heading_normalizer: removed {res['empty_headings_removed']} empty heading(s); "
          f"title_tagged={res.get('title_tagged', 0)}; "
          f"promoted {res['promoted']} <P> to headings; "
          f"retagged {res['retagged_existing']}; "
          f"artifacted {res['banner_artifacted']} / demoted {res.get('banner_demoted', 0)} "
          f"repeated banner heading(s); "
          f"split {res.get('headings_split', 0)} fused heading(s); "
          f"levels={res['levels']}")
    return res


def main(argv):
    if len(argv) < 3:
        print("Usage: heading_normalizer.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        r = normalize_headings(argv[1], argv[2])
        print(json.dumps(r))
        return 0
    except Exception as exc:
        import traceback
        print(f"heading_normalizer: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
