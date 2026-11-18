#!/usr/bin/env python3
"""
inline_span_fixer.py

Wraps character-formatting runs (a bold or italic phrase inside an otherwise
regular paragraph) in their own <Span> element.

Why
---
PDFix's AddTags() emits one marked-content sequence per paragraph, so a bold
lead-in and the regular text that follows it share a single MCID and there is
nothing for a <Span> to point at.  Word's own export splits them, which is why
the manual remediation of the 2023-Legislative-Summary sample carries 14 <Span>
elements — "- Business Filing Technical Changes.", "- Accessible Audits." and
so on — each a Calibri-Bold run inside a Calibri parent.

Scope, stated honestly
----------------------
<Span> carries no accessibility semantics on its own: PDF/UA does not require
it, and no screen reader announces "bold".  What it buys is a place to hang
/Lang, /ActualText or /Alt on a sub-paragraph run later, and parity with what a
Word-produced file looks like.  It is a fidelity improvement, not a compliance
one.

This pass deliberately does NOT reproduce the other inline elements a Word
export leaves behind.  In the reference file 43 of its 55 <StyleSpan> elements
wrap nothing but a single <Link> that is already tagged, and its <Sub> elements
wrap ordinary words; those are pass-through containers that add elements without
adding meaning, and every one of them role-maps to plain /Span anyway.

How the split works
-------------------
The dominant font of a sequence is the one covering the most bytes.  A
contiguous run in any other (non-symbol) font is a formatting run:

    /P <</MCID 12>> BDC
       Tf /TT1 -> Calibri-Bold        <- run A  (minority -> <Span>)
       TJ 'Business Filing Technical Changes.'
       Tf /TT0 -> Calibri             <- run B  (dominant -> stays with host)
       TJ ' Allows the Corporation Division to ...'
    EMC

becomes two sequences, cut at the `Tf`, the minority one getting a fresh MCID
owned by a new <Span>.  MCIDs are never reused — PDF 32000-1 §14.7.4.2 requires
uniqueness within a content stream — and the host element's /K is rewritten so
the segments stay in reading order.

Sequences containing nested marked content are skipped: splitting those would
need the enclosing brackets rebuilt, and no observed formatting run needs it.

Usage
-----
    python3 inline_span_fixer.py <input.pdf> <output.pdf>
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
except ImportError:
    from struct_utils import fix_struct_parents, rebuild_parent_tree  # type: ignore

_SYMBOL_FONT = re.compile(r"(symbol|wingding|zapf|dingbat|webding|marlett)", re.I)
_TEXT_OPS = {"Tj", "TJ", "'", '"'}
_SUBSET = re.compile(r"^[A-Z]{6}\+")

# Elements whose marked content may contain formatting runs.
_HOST_TAGS = {"/P", "/LBody", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6",
              "/TD", "/TH", "/Lbl", "/Caption"}

# A run shorter than this is kerning noise, not a styled phrase.
_MIN_RUN_BYTES = 2


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


def _shown(operands, o) -> bytes:
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


def _mcid_of(ins):
    if _op(ins) != "BDC":
        return None
    try:
        ops = ins.operands
        if len(ops) > 1 and isinstance(ops[1], Dictionary) and "/MCID" in ops[1]:
            return int(ops[1]["/MCID"])
    except Exception:
        pass
    return None


def _font_map(page) -> dict:
    res = page.obj.get("/Resources")
    fonts = (res.get("/Font") if res is not None else None) or {}
    out = {}
    for k, v in fonts.items():
        try:
            out[str(k)] = _SUBSET.sub("", str(v.get("/BaseFont", "?")).lstrip("/"))
        except Exception:
            out[str(k)] = "?"
    return out


def _claim_map(pdf) -> dict:
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return {}
    pmap = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
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
        pg = node.get("/Pg")
        pi = pmap.get(pg.objgen) if pg is not None else None
        if pi is not None and _stype(node) in _HOST_TAGS:
            for m in _iter_mcids(node.get("/K")):
                out.setdefault((pi, m), node)
        walk(node.get("/K"))

    walk(st.get("/K"))
    return out


# ---------------------------------------------------------------------------
# plan the splits for one page
# ---------------------------------------------------------------------------

def _plan_page(pdf, pi, claims) -> list:
    """[{mcid, cuts: [(index, is_minority)], open_i, close_i}] for this page."""
    page = pdf.pages[pi]
    fmap = _font_map(page)
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return []

    plans = []
    curfont = None
    gstack: list = []
    i = 0
    while i < len(instrs):
        ins = instrs[i]
        o = _op(ins)
        if o == "q":
            gstack.append(curfont)
            i += 1
            continue
        if o == "Q":
            if gstack:
                curfont = gstack.pop()
            i += 1
            continue
        if o == "Tf":
            try:
                curfont = fmap.get(str(ins.operands[0]), "?")
            except Exception:
                pass
            i += 1
            continue

        m = _mcid_of(ins)
        if o == "BDC" and m is not None and (pi, m) in claims:
            # collect the sequence
            body = []          # (index, kind, font, bytes)
            j = i + 1
            nested = False
            font_here = curfont
            last_tf = None
            local_stack: list = []
            while j < len(instrs):
                o2 = _op(instrs[j])
                if o2 in ("BDC", "BMC"):
                    nested = True
                    local_stack.append(j)
                elif o2 == "EMC":
                    if not local_stack:
                        break
                    local_stack.pop()
                elif o2 == "q":
                    gstack.append(font_here)
                elif o2 == "Q":
                    if gstack:
                        font_here = gstack.pop()
                elif o2 == "Tf":
                    try:
                        font_here = fmap.get(str(instrs[j].operands[0]), "?")
                    except Exception:
                        pass
                    last_tf = j
                elif o2 in _TEXT_OPS:
                    body.append((j, font_here, _shown(instrs[j].operands, o2), last_tf))
                j += 1
            close_i = j

            if not nested and body:
                weight: dict = {}
                for _idx, f, raw, _tf in body:
                    if f and not _SYMBOL_FONT.search(f):
                        weight[f] = weight.get(f, 0) + len(raw)
                if len(weight) > 1:
                    dom = max(weight, key=lambda f: weight[f])
                    # Segment by dominant / minority.  A whitespace-only run is
                    # NEUTRAL: producers routinely emit the space between two
                    # halves of one styled phrase in the regular face, and
                    # treating that as a boundary chopped "- Business Filing
                    # Technical Changes." into "- B" and "usiness Filing…".
                    # Neutral runs join whatever segment is open.
                    segs = []
                    for idx, f, raw, tf in body:
                        if not raw.strip():
                            if segs:
                                segs[-1][2].append((idx, raw, tf))
                                continue
                            minor = False
                        else:
                            minor = bool(f and f != dom
                                         and not _SYMBOL_FONT.search(f))
                        if segs and segs[-1][0] == minor:
                            segs[-1][2].append((idx, raw, tf))
                        else:
                            segs.append([minor, f, [(idx, raw, tf)]])

                    # A minority segment too short to be a styled phrase is
                    # kerning noise — fold it back into its neighbour.
                    merged = []
                    for s in segs:
                        text = b"".join(r for _i, r, _t in s[2]).strip()
                        if s[0] and len(text) < _MIN_RUN_BYTES and merged:
                            merged[-1][2].extend(s[2])
                            continue
                        if merged and merged[-1][0] == s[0]:
                            merged[-1][2].extend(s[2])
                            continue
                        merged.append(s)
                    segs = merged

                    if any(s[0] for s in segs) and len(segs) > 1:
                        cuts = []
                        for si, (minor, f, items) in enumerate(segs):
                            if si == 0:
                                continue
                            first_idx, _raw, tf = items[0]
                            cut_at = tf if (tf is not None and tf > (
                                segs[si - 1][2][-1][0])) else first_idx
                            cuts.append((cut_at, minor))
                        if cuts:
                            plans.append({"mcid": m, "open_i": i,
                                          "close_i": close_i, "cuts": cuts,
                                          "first_minor": segs[0][0]})
            i = close_i + 1
            continue

        i += 1
    return plans


def _rewrite_page(pdf, pi, plans, claims, res) -> list:
    """Apply the planned cuts. Returns [(host, old_mcid, ordered_segments)]."""
    page = pdf.pages[pi]
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return []

    next_mcid = -1
    for ins in instrs:
        m = _mcid_of(ins)
        if m is not None and m > next_mcid:
            next_mcid = m
    next_mcid += 1

    by_open = {p["open_i"]: p for p in plans}
    cut_at: dict = {}
    for p in plans:
        for idx, minor in p["cuts"]:
            cut_at[idx] = (p, minor)

    out: list = []
    results: list = []
    active = None
    segments: list = []

    for i, ins in enumerate(instrs):
        if i in by_open:
            active = by_open[i]
            segments = [(active["mcid"], active["first_minor"])]
            out.append(ins)
            continue

        if active is not None and i in cut_at:
            _p, minor = cut_at[i]
            out.append(CSI([], Operator("EMC")))
            tag = Name("/Span") if minor else Name(
                str(instrs[active["open_i"]].operands[0]))
            out.append(CSI([tag, Dictionary({"/MCID": next_mcid})],
                           Operator("BDC")))
            segments.append((next_mcid, minor))
            next_mcid += 1
            out.append(ins)
            continue

        if active is not None and i == active["close_i"]:
            out.append(ins)
            host = claims.get((pi, active["mcid"]))
            if host is not None:
                results.append((host, active["mcid"], list(segments)))
            active = None
            segments = []
            continue

        out.append(ins)

    if results:
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
        res["pages_touched"] += 1
    return results


def fix_inline_spans(in_path: str, out_path: str) -> dict:
    res = {"spans_created": 0, "sequences_split": 0, "pages_touched": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("inline_span_fixer: no StructTreeRoot; copied through")
        return res

    claims = _claim_map(pdf)
    all_results = []
    for pi in range(len(pdf.pages)):
        plans = _plan_page(pdf, pi, claims)
        if not plans:
            continue
        all_results += [(pi, r) for r in _rewrite_page(pdf, pi, plans, claims, res)]

    for pi, (host, old_m, segments) in all_results:
        page_obj = pdf.pages[pi].obj
        kids = _kids(host)
        pos = None
        for idx, c in enumerate(kids):
            try:
                if not isinstance(c, Dictionary) and int(c) == old_m:
                    pos = idx
                    break
            except Exception:
                continue
        if pos is None:
            continue

        replacement = []
        for mcid, minor in segments:
            if minor:
                span = pdf.make_indirect(Dictionary(
                    Type=Name("/StructElem"), S=Name("/Span"),
                    P=host, Pg=page_obj, K=Array([mcid]),
                ))
                replacement.append(span)
                res["spans_created"] += 1
            else:
                replacement.append(mcid)
        kids[pos:pos + 1] = replacement
        host["/K"] = Array(kids)
        res["sequences_split"] += 1

    try:
        fix_struct_parents(pdf)
        rebuild_parent_tree(pdf)
    except Exception as exc:
        print(f"inline_span_fixer: parent rebuild failed: {exc}", file=sys.stderr)

    pdf.save(out_path)
    print(f"inline_span_fixer: created {res['spans_created']} <Span>; "
          f"split {res['sequences_split']} sequence(s); "
          f"pages_touched={res['pages_touched']}")
    return res


def main(argv) -> int:
    if len(argv) < 3:
        print("Usage: inline_span_fixer.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        res = fix_inline_spans(argv[1], argv[2])
        print(json.dumps(res))
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
