#!/usr/bin/env python3
"""
running_header_artifacter.py

Turns the repeated page banner into a pagination artifact, including the copies
that sit NESTED inside another tagged sequence.

The problem
-----------
heading_normalizer (5.92) already artifacts running headers, but only when every
one of the banner's marked-content sequences is top-level: artifacting a nested
sequence in place would leave tagged content inside an artifact, which is its
own PDF/UA violation.  When it cannot, it demotes the banner to <P> — safe, but
the banner stays in the logical tree and a screen reader announces the document
title again on every page.

It also runs BEFORE final_structure_repair, so it sees an unsettled tree; copies
that are top-level in the delivered file were not top-level (or not candidates)
when it looked.  On the 2023-Legislative-Summary sample, 5 banners survived to
delivery: 3 top-level, 2 nested one level deep inside a <P>.

What this does
--------------
Runs on the settled tree (after 5.96) and handles both shapes:

  top-level      /P <</MCID 44>> BDC  …banner…  EMC
      becomes    /Artifact <</Type /Pagination /Subtype /Header>> BDC …banner… EMC

  nested         /P <</MCID 123>> BDC  …text…  /P <</MCID 122>> BDC …banner… EMC  …text…  EMC
      becomes    /P <</MCID 123>> BDC  …text…  EMC
                 /Artifact <</Type /Pagination …>> BDC …banner… EMC
                 /P <</MCID N>>   BDC  …text…  EMC          <- N is a NEW mcid

The reopened half gets a FRESH MCID, never a reuse of the host's.  PDF 32000-1
§14.7.4.2 requires an MCID to be unique within its content stream, so reopening
with the original number would be non-conformant even though the bytes look
tidy.  The new MCID is appended to the host element's /K immediately after the
original, so the host keeps both halves and reading order is preserved.

Detection
---------
Text that repeats on 2+ pages AND sits in the top or bottom band of every page
it appears on.  The band test is what separates a running header from a phrase
that legitimately recurs in body copy.  The document's own <Title> is never
touched — that is the title, not furniture.

Usage
-----
    python3 running_header_artifacter.py <input.pdf> <output.pdf>
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

_WS_RE = re.compile(r"\s+")
_TEXT_OPS = {"Tj", "TJ", "'", '"'}

# How far from an edge counts as "page furniture".
_TOP_BAND = 0.86
_BOTTOM_BAND = 0.14

_MIN_PAGES = 2            # must recur on at least this many pages
_MAX_CHARS = 120          # a running header is short


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


def _pagination_artifact(subtype=None) -> CSI:
    props = {"/Type": Name("/Pagination")}
    if subtype is not None:
        props["/Subtype"] = subtype
    return CSI([Name("/Artifact"), Dictionary(props)], Operator("BDC"))


# ---------------------------------------------------------------------------
# scan: text + vertical position per MCID
# ---------------------------------------------------------------------------

def _page_scan(pdf, pi) -> dict:
    """mcid -> {"text": bytes, "y": float, "depth": int}"""
    page = pdf.pages[pi]
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return {}
    out: dict = {}
    stack: list = []
    for ins in instrs:
        o = _op(ins)
        if o in ("BDC", "BMC"):
            m = _mcid_of(ins)
            if m is not None:
                out.setdefault(m, {"text": b"", "y": None, "depth": len(stack)})
            stack.append(m)
        elif o == "EMC":
            if stack:
                stack.pop()
        elif o == "Tm":
            try:
                y = float(ins.operands[5])
            except Exception:
                y = None
            if y is not None:
                for m in reversed(stack):
                    if m is not None and m in out:
                        if out[m]["y"] is None or y > out[m]["y"]:
                            out[m]["y"] = y
                        break
        elif o in _TEXT_OPS:
            raw = _shown(ins.operands, o)
            for m in reversed(stack):
                if m is not None and m in out:
                    out[m]["text"] += raw
                    break
    return out


def _page_height(pdf, pi) -> float:
    try:
        mb = [float(x) for x in pdf.pages[pi].obj.MediaBox]
        return mb[3] - mb[1]
    except Exception:
        return 792.0


def _key(raw: bytes) -> str:
    try:
        s = raw.decode("latin-1", "ignore")
    except Exception:
        return ""
    return _WS_RE.sub(" ", s).strip().casefold()


# ---------------------------------------------------------------------------
# find the banners
# ---------------------------------------------------------------------------

def find_running_headers(pdf) -> list:
    """[(element, page_index, mcid, subtype)] for every banner copy to artifact."""
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return []

    pmap = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    scans = {pi: _page_scan(pdf, pi) for pi in range(len(pdf.pages))}

    # every element that directly owns marked content
    owners: list = []
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
        if pi is not None:
            for m in _iter_mcids(node.get("/K")):
                owners.append((node, pi, m))
        walk(node.get("/K"))

    walk(st.get("/K"))

    # group by text
    groups: dict = {}
    for el, pi, m in owners:
        info = scans.get(pi, {}).get(m)
        if not info or not info["text"].strip():
            continue
        k = _key(info["text"])
        if not k or len(k) > _MAX_CHARS:
            continue
        groups.setdefault(k, []).append((el, pi, m, info))

    out: list = []
    for k, items in groups.items():
        pages = {pi for _e, pi, _m, _i in items}
        if len(pages) < _MIN_PAGES:
            continue

        # every occurrence must sit in a page-edge band
        placed = []
        for el, pi, m, info in items:
            y = info["y"]
            if y is None:
                placed = []
                break
            h = _page_height(pdf, pi)
            frac = y / h if h else 0.5
            if frac >= _TOP_BAND:
                placed.append((el, pi, m, Name("/Header")))
            elif frac <= _BOTTOM_BAND:
                placed.append((el, pi, m, Name("/Footer")))
            else:
                placed = []          # one occurrence in body copy -> not furniture
                break
        if not placed:
            continue

        for el, pi, m, sub in placed:
            # The document <Title> is the title, not page furniture.
            if _stype(el) == "/Title":
                continue
            out.append((el, pi, m, sub))
    return out


# ---------------------------------------------------------------------------
# rewrite one page
# ---------------------------------------------------------------------------

def _bracket_and_paint(instrs):
    """(match, paint_prefix) for one instruction list.

    match[i] = index of the EMC closing the BDC/BMC at i.
    paint_prefix[i] = number of painting operators in instrs[:i].
    """
    match: dict = {}
    stack: list = []
    paint_prefix = [0] * (len(instrs) + 1)
    for i, ins in enumerate(instrs):
        o = _op(ins)
        paint_prefix[i + 1] = paint_prefix[i] + (
            1 if (o in _TEXT_OPS or o in ("Do", "S", "s", "f", "F", "f*",
                                          "B", "B*", "b", "b*", "sh")) else 0
        )
        if o in ("BDC", "BMC"):
            stack.append(i)
        elif o == "EMC":
            if stack:
                match[stack.pop()] = i
    return match, paint_prefix


def _rewrite_page(pdf, pi, targets, claims, res) -> tuple:
    """targets: {mcid: subtype}.

    Returns (reopened, dropped) where
      reopened = [(host_element, old_mcid, new_mcid)]  new half to register
      dropped  = [(host_element, mcid)]                half that paints nothing
    """
    page = pdf.pages[pi]
    try:
        instrs = list(pikepdf.parse_content_stream(page))
    except Exception:
        return [], []

    match, paint = _bracket_and_paint(instrs)

    next_mcid = -1
    for ins in instrs:
        m = _mcid_of(ins)
        if m is not None and m > next_mcid:
            next_mcid = m
    next_mcid += 1

    out: list = []
    stack: list = []          # [(instruction, mcid, open_index)]
    reopened: list = []
    dropped: list = []
    skip_emc = 0              # enclosing EMCs to swallow (their BDC was dropped)
    i = 0
    changed = False

    while i < len(instrs):
        ins = instrs[i]
        o = _op(ins)
        m = _mcid_of(ins)

        if o in ("BDC", "BMC"):
            if m is not None and m in targets:
                enclosing = list(stack)
                banner_end = match.get(i, i)

                # Close only the enclosing sequences that actually painted
                # something BEFORE the banner. One that did not is an empty
                # shell — emitting it would leave an inkless MCID, which is
                # exactly the "phantom MCID" that fails validate.py. Its
                # opening BDC is removed from `out` instead.
                for x, mm, oi in reversed(enclosing):
                    pre_painted = paint[i] - paint[oi + 1] > 0
                    if pre_painted:
                        out.append(CSI([], Operator("EMC")))
                    else:
                        for j in range(len(out) - 1, -1, -1):
                            if out[j] is x:
                                del out[j]
                                break
                        skip_emc += 1
                        if mm is not None:
                            host = claims.get((pi, mm))
                            if host is not None:
                                dropped.append((host, mm))

                # the banner itself, as a typed pagination artifact
                out.append(_pagination_artifact(targets[m]))
                depth = 0
                i += 1
                while i < len(instrs):
                    ins2 = instrs[i]
                    o2 = _op(ins2)
                    if o2 in ("BDC", "BMC"):
                        depth += 1
                        out.append(CSI([Name("/Artifact")], Operator("BMC")))
                        i += 1
                        continue
                    if o2 == "EMC":
                        out.append(CSI([], Operator("EMC")))
                        i += 1
                        if depth == 0:
                            break
                        depth -= 1
                        continue
                    out.append(ins2)
                    i += 1
                changed = True

                # Reopen each enclosing sequence, but only where content still
                # follows the banner — same reasoning in the other direction.
                new_stack = []
                for x, mm, oi in enclosing:
                    close = match.get(oi)
                    post_painted = (close is not None
                                    and paint[close] - paint[banner_end + 1] > 0)
                    if not post_painted:
                        skip_emc += 1
                        if mm is not None:
                            host = claims.get((pi, mm))
                            if host is not None and not any(
                                    h is host and mc == mm for h, mc in dropped):
                                dropped.append((host, mm))
                        continue
                    if mm is None:
                        out.append(x)
                        new_stack.append((x, mm, oi))
                        continue
                    props = {}
                    try:
                        old = x.operands[1]
                        for kk in old.keys():
                            if str(kk) != "/MCID":
                                props[str(kk)] = old[kk]
                    except Exception:
                        pass
                    props["/MCID"] = next_mcid
                    newins = CSI([x.operands[0], Dictionary(props)],
                                 Operator("BDC"))
                    host = claims.get((pi, mm))
                    if host is not None:
                        reopened.append((host, mm, next_mcid))
                    out.append(newins)
                    new_stack.append((newins, next_mcid, oi))
                    next_mcid += 1
                stack = new_stack
                continue

            stack.append((ins, m, i))
            out.append(ins)
            i += 1
            continue

        if o == "EMC":
            if skip_emc and not stack:
                skip_emc -= 1          # its BDC was removed; drop the pairing EMC
                i += 1
                continue
            if stack:
                stack.pop()
                out.append(ins)
            elif skip_emc:
                skip_emc -= 1
            else:
                out.append(ins)
            i += 1
            continue

        out.append(ins)
        i += 1

    if changed:
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
        res["pages_touched"] += 1
    return reopened, dropped


# ---------------------------------------------------------------------------
# structure-tree cleanup
# ---------------------------------------------------------------------------

def _detach_mcid(el, mcid) -> None:
    keep = []
    for c in _kids(el):
        if isinstance(c, Dictionary):
            if str(c.get("/Type", "")) == "/MCR" and "/MCID" in c:
                try:
                    if int(c["/MCID"]) == mcid:
                        continue
                except Exception:
                    pass
            keep.append(c)
            continue
        try:
            if int(c) == mcid:
                continue
        except Exception:
            pass
        keep.append(c)
    el["/K"] = Array(keep)


def _prune_empty(pdf, res) -> None:
    """Drop elements left with no content after their MCID was artifacted."""
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return
    seen: set = set()

    def prune(node) -> None:
        if not isinstance(node, Dictionary):
            return
        if node.is_indirect:
            if node.objgen in seen:
                return
            seen.add(node.objgen)
        kids = _kids(node)
        keep = []
        for c in kids:
            if isinstance(c, Dictionary) and "/S" in c:
                prune(c)
                has_content = bool(_kids(c))
                if not has_content:
                    res["empty_elements_removed"] += 1
                    continue
            keep.append(c)
        if len(keep) != len(kids):
            node["/K"] = Array(keep)

    prune(st)


def artifact_running_headers(in_path: str, out_path: str) -> dict:
    res = {"artifacted": 0, "pages_touched": 0, "sequences_split": 0,
           "empty_elements_removed": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("running_header_artifacter: no StructTreeRoot; copied through")
        return res

    found = find_running_headers(pdf)
    if not found:
        pdf.save(out_path)
        print("running_header_artifacter: no running headers found; copied through")
        return res

    pmap = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    claims: dict = {}
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
        if pi is not None:
            for m in _iter_mcids(node.get("/K")):
                claims.setdefault((pi, m), node)
        walk(node.get("/K"))

    walk(st.get("/K"))

    by_page: dict = {}
    for el, pi, m, sub in found:
        by_page.setdefault(pi, {})[m] = sub

    for pi in sorted(by_page):
        reopened, dropped = _rewrite_page(pdf, pi, by_page[pi], claims, res)
        for host, gone_m in dropped:
            # its sequence painted nothing on either side of the banner
            _detach_mcid(host, gone_m)
            res["empty_halves_dropped"] = res.get("empty_halves_dropped", 0) + 1
        for host, old_m, new_m in reopened:
            # host keeps both halves: insert the new mcid right after the old
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
                kids.append(new_m)
            else:
                kids.insert(pos + 1, new_m)
            host["/K"] = Array(kids)
            res["sequences_split"] += 1

    for el, pi, m, _sub in found:
        _detach_mcid(el, m)
        res["artifacted"] += 1

    _prune_empty(pdf, res)

    try:
        fix_struct_parents(pdf)
        rebuild_parent_tree(pdf)
    except Exception as exc:
        print(f"running_header_artifacter: parent rebuild failed: {exc}",
              file=sys.stderr)

    pdf.save(out_path)
    print(f"running_header_artifacter: artifacted {res['artifacted']} banner(s); "
          f"split {res['sequences_split']} enclosing sequence(s); "
          f"removed {res['empty_elements_removed']} empty element(s); "
          f"pages_touched={res['pages_touched']}")
    return res


def main(argv) -> int:
    if len(argv) < 3:
        print("Usage: running_header_artifacter.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        res = artifact_running_headers(argv[1], argv[2])
        print(json.dumps(res))
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
