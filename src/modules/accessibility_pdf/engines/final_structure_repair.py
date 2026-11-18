"""
final_structure_repair.py
=========================
Single-pass, pikepdf-only repair of the structural defects that survive the
rest of the Orion pipeline and that PAC / Acrobat / the QA tester all flag on
the delivered file.

It exists because the individual fixers each solve one symptom on an
intermediate file, and several of them run BEFORE the step that creates the
defect they are supposed to clear (notably heading_parent_fixer, which ran in
_save_remediated_pdf long before heading_normalizer produced the headings).
This module runs LAST, on the file that is actually shipped.

Repairs, in dependency order
---------------------------
1. unwrap_containers    /NonStruct + /Private wrappers are spliced away, their
                        children promoted IN PLACE (reading order preserved).
                        Clears PAC HDR-005 "Invalid use of Hn structure
                        element" (28 x Hn inside /NonStruct) and the tester's
                        "Unwanted structure elements".  Also strips the
                        non-unique /T ("Page 1", "Page 2", ...) titles.

2. detag_text_figures   <Figure> elements whose claimed marked content is
                        real, readable TEXT.  All-text figures are retagged
                        <P> (alt-text + BBox dropped); mixed image+text
                        figures are split, the text popped out into a sibling
                        <P>.  Clears the tester's "Editable text tagged as
                        Figure" and a large share of "Readable content not
                        tagged".

3. reclaim_artifacts    Top-level /Artifact BDC/BMC sequences that paint
                        READABLE text (body copy, "Examples:", "Fill in the
                        blanks.", the skill-badge labels...) are converted
                        back to /P <</MCID n>> tagged content and wired into
                        the structure tree at the correct reading-order
                        position.  Real pagination furniture (running header /
                        footer, page numbers, decorative paint) is left
                        artifacted.  Clears ARTIFACT-001 and the tester's
                        "much of the readable content appears to have been
                        marked as Artifact".

4. normalise_lists      L -> LI -> (Lbl?, LBody).  Stray children are boxed
                        into LBody, /ListNumbering is set to match whether
                        labels are actually present.  Clears "Incorrect list
                        structure".

5. drop_empty_tags      Structure elements that resolve to no content and no
                        text (empty <P>, <Span>, <Figure> shells).  Clears
                        "Empty P tags".

6. enforce_single_h1    Exactly one <H1> (the first in reading order, i.e. the
                        document title); every other H1 is demoted, then the
                        whole outline is re-clamped so no level is skipped.
                        Clears HDR-002 while keeping HDR-003 passing.

7. rebuild_parent_tree  /ParentTree and every /P back-pointer are rebuilt from
                        the tree as it now stands, so nothing above can leave a
                        stale pointer behind.

CLI:  python final_structure_repair.py <input.pdf> <output.pdf>
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

try:
    import pikepdf
    from pikepdf import Array, Dictionary, Name, String
except ImportError:  # pragma: no cover
    pikepdf = None  # type: ignore

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── tag vocabularies ────────────────────────────────────────────────────────

HEADING_TAGS = {"/H1", "/H2", "/H3", "/H4", "/H5", "/H6"}

# <Title> is not a heading tag, but under the RoleMap emitted by title_tag.py it
# resolves to H1, so it participates in the heading outline and CONSUMES level 1.
# Anything reasoning about heading levels has to account for it or it will
# promote the following H2 to H1 and produce two H1s after role resolution.
try:  # imported as part of the package
    from .title_tag import TITLE_EQUIVALENT_LEVEL, TITLE_TAG
except ImportError:  # executed as a standalone script
    try:
        from title_tag import TITLE_EQUIVALENT_LEVEL, TITLE_TAG  # type: ignore[no-redef]
    except ImportError:  # title_tag not deployed — degrade to previous behaviour
        TITLE_TAG = "/Title"
        TITLE_EQUIVALENT_LEVEL = 1

OUTLINE_TAGS = HEADING_TAGS | {TITLE_TAG}

# Wrappers that carry no semantics and are illegal as a heading parent.
# Splicing them away is always safe: their children keep their own semantics.
TRANSPARENT_WRAPPERS = {"/NonStruct", "/Private"}

# Elements that legitimately contain no marked content of their own.
STRUCTURAL_CONTAINERS = {
    "/Document", "/Part", "/Art", "/Sect", "/Div", "/L", "/LI", "/LBody",
    "/Table", "/TR", "/TD", "/TH", "/THead", "/TBody", "/TFoot",
    "/TOC", "/TOCI", "/BlockQuote", "/Caption", "/Index",
}

TEXT_SHOW_OPS = {"Tj", "TJ", "'", '"'}
IMAGE_OPS = {"Do", "INLINE IMAGE", "BI", "EI", "ID"}

# Every operator that puts marks on the page. An MCID sequence containing ANY
# of these has content, even if it paints no text and no image (table rules,
# box fills, underlines). Deleting a struct element that claims such an MCID
# orphans the content -> PAC "content is not tagged".
PAINT_OPS = IMAGE_OPS | {
    "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "sh",
}

# A run of >=3 consecutive letters is our proxy for "a human can read this".
# The running header/footer in these textbooks is set in subset fonts whose
# codes land in the C0 control range, so it never matches — which is exactly
# the discrimination we want.
_READABLE_RE = re.compile(rb"[A-Za-z]{3,}")


def _is_text_only(scan, mcid: int) -> bool:
    """True if this marked-content sequence paints readable text and nothing else.

    `StreamScan.mcid_nontext` records whether the sequence also painted an image,
    a path or a shading; such a sequence cannot be pulled out of a <Figure> and
    retagged as a <P> without losing the graphic.
    """
    return _is_readable(scan.text_of(mcid)) and not scan.paints_nontext(mcid)


def _is_readable(raw: bytes) -> bool:
    """True if `raw` glyph codes look like plain readable text.

    Two conditions, both required:
      * contains a word (3+ consecutive ASCII letters), and
      * is overwhelmingly printable ASCII (subset-encoded furniture is not).
    """
    if not raw or not raw.strip():
        return False
    if not _READABLE_RE.search(raw):
        return False
    printable = sum(1 for c in raw if 32 <= c < 127)
    return printable / len(raw) > 0.8


# ── low-level helpers ───────────────────────────────────────────────────────

def _stype(node) -> str:
    try:
        return str(node.get("/S", "")) if "/S" in node else ""
    except Exception:
        return ""


def _same(a, b) -> bool:
    try:
        return a.objgen == b.objgen
    except Exception:
        return a is b


def _kids(node) -> list:
    """Return node's /K as a plain python list (never None)."""
    k = node.get("/K")
    if k is None:
        return []
    if isinstance(k, Array):
        return list(k)
    return [k]


def _set_kids(node, items) -> None:
    node["/K"] = Array(list(items))


def _resolve(obj):
    try:
        return obj.get_object() if hasattr(obj, "get_object") else obj
    except Exception:
        return obj


def _child_elements(node) -> list:
    """Only the child StructElems of node (skips MCIDs / MCRs / OBJRs)."""
    out = []
    for c in _kids(node):
        c = _resolve(c)
        if isinstance(c, Dictionary) and "/S" in c:
            out.append(c)
    return out


def _shown_bytes(operands, op: str) -> bytes:
    """Glyph codes painted by a text-showing operator."""
    if op not in TEXT_SHOW_OPS:
        return b""
    out = bytearray()

    def grab(o):
        if isinstance(o, String):
            out.extend(bytes(o))

    try:
        if op == "TJ":
            arr = operands[0]
            if isinstance(arr, Array):
                for el in arr:
                    grab(el)
        else:
            grab(operands[-1])
    except Exception:
        pass
    return bytes(out)


# ── per-page content-stream scan ────────────────────────────────────────────

class StreamScan:
    """Marked content of ONE content stream.

    A page stream and each Form XObject stream are SEPARATE marked-content
    namespaces: MCID 3 in a page and MCID 3 inside /Fm1 are different content.
    Treating them as one namespace corrupts the structure tree and the
    ParentTree. Each stream therefore gets its own scan.

    mcid_text : MCID -> glyph bytes painted inside that sequence
    mcid_ink  : MCID -> True if the sequence paints ANYTHING (text, image,
                path, shading). Used to decide whether a struct element that
                claims this MCID is really empty.
    max_mcid  : highest MCID in use (-1 if none)
    """

    def __init__(self, stream_owner):
        self.mcid_text: dict[int, bytes] = {}
        self.mcid_ink: dict[int, bool] = {}
        self.mcid_nontext: dict[int, bool] = {}
        self.mcid_order: list[int] = []
        self.max_mcid: int = -1
        self._scan(stream_owner)

    def _scan(self, owner) -> None:
        try:
            instrs = list(pikepdf.parse_content_stream(owner))
        except Exception:
            return
        stack: list[int | None] = []
        for operands, op in instrs:
            o = str(op)
            if o in ("BDC", "BMC"):
                mcid = None
                if o == "BDC" and len(operands) > 1:
                    prop = _resolve(operands[1])
                    if isinstance(prop, Dictionary) and "/MCID" in prop:
                        try:
                            mcid = int(prop["/MCID"])
                        except Exception:
                            mcid = None
                if mcid is not None:
                    if mcid not in self.mcid_text:
                        self.mcid_text[mcid] = b""
                        self.mcid_ink.setdefault(mcid, False)
                        self.mcid_nontext.setdefault(mcid, False)
                        self.mcid_order.append(mcid)
                    self.max_mcid = max(self.max_mcid, mcid)
                stack.append(mcid)
            elif o == "EMC":
                if stack:
                    stack.pop()
            else:
                live = [m for m in stack if m is not None]
                if not live:
                    continue
                cur = live[-1]
                if o in TEXT_SHOW_OPS:
                    self.mcid_text[cur] = self.mcid_text.get(cur, b"") + _shown_bytes(operands, o)
                    self.mcid_ink[cur] = True
                elif o in PAINT_OPS:
                    # ANY painting op counts as ink — a table rule, a box fill or
                    # a shading is content, and an element claiming it must NOT
                    # be deleted as "empty".
                    self.mcid_ink[cur] = True
                    self.mcid_nontext[cur] = True

    def text_of(self, mcid: int) -> bytes:
        return self.mcid_text.get(mcid, b"")

    def has_ink(self, mcid: int) -> bool:
        return self.mcid_ink.get(mcid, False)

    def paints_nontext(self, mcid: int) -> bool:
        return self.mcid_nontext.get(mcid, False)


# ── repair context ──────────────────────────────────────────────────────────

class Repair:
    """Shared state for one repair run.

    STREAM KEYS
    -----------
    Content lives in one of two kinds of stream, each with its OWN MCID
    namespace:

        ("page", page_index)      content in the page's own content stream
        ("xobj", objgen)          content inside a Form XObject

    A structure element points into a Form XObject by using an /MCR dict with
    an /Stm entry naming that XObject. Ignoring /Stm — and pretending every
    MCID belongs to its page — silently maps XObject content onto unrelated
    page content and destroys the ParentTree. Every lookup below is therefore
    keyed by (stream_key, mcid), never by mcid alone.
    """

    def __init__(self, pdf):
        self.pdf = pdf
        self.root = pdf.Root.get("/StructTreeRoot")
        self.page_index = {}
        for i, p in enumerate(pdf.pages):
            try:
                self.page_index[p.obj.objgen] = i
            except Exception:
                pass
        self._scans: dict[tuple, StreamScan] = {}
        self._xobjs: dict[tuple, Any] = {}      # stream_key -> XObject stream
        self._index_xobjects()
        self.stats: dict[str, Any] = {}

    def _index_xobjects(self) -> None:
        """Find every Form XObject that carries marked content."""
        for page in self.pdf.pages:
            res = page.obj.get("/Resources")
            if not isinstance(res, Dictionary):
                continue
            xo = res.get("/XObject")
            if not isinstance(xo, Dictionary):
                continue
            for _name, x in xo.items():
                x = _resolve(x)
                if not isinstance(x, pikepdf.Stream):
                    continue
                if str(x.get("/Subtype", "")) != "/Form":
                    continue
                try:
                    self._xobjs[("xobj", x.objgen)] = x
                except Exception:
                    pass

    # -- stream helpers ------------------------------------------------------

    def scan(self, key: tuple) -> StreamScan:
        if key not in self._scans:
            if key[0] == "page":
                owner = self.pdf.pages[key[1]]
            else:
                owner = self._xobjs.get(key)
                if owner is None:
                    self._scans[key] = StreamScan.__new__(StreamScan)
                    self._scans[key].mcid_text = {}
                    self._scans[key].mcid_ink = {}
                    self._scans[key].mcid_nontext = {}
                    self._scans[key].mcid_order = []
                    self._scans[key].max_mcid = -1
                    return self._scans[key]
            self._scans[key] = StreamScan(owner)
        return self._scans[key]

    def page_of(self, node) -> int | None:
        pg = node.get("/Pg")
        if pg is None:
            return None
        try:
            return self.page_index.get(pg.objgen)
        except Exception:
            return None

    # -- struct-tree walking -------------------------------------------------

    def walk(self, visitor) -> None:
        """DFS the struct tree, calling visitor(node, parent) in reading order."""
        seen: set = set()

        def rec(node, parent):
            if not isinstance(node, Dictionary):
                return
            try:
                key = node.objgen
                if key in seen:
                    return
                seen.add(key)
            except Exception:
                pass
            if "/S" in node:
                visitor(node, parent)
            for c in _kids(node):
                c = _resolve(c)
                if isinstance(c, Dictionary) and "/S" in c:
                    rec(c, node)

        for c in _kids(self.root):
            rec(_resolve(c), self.root)

    def elements(self) -> list[tuple]:
        """Flat (node, parent) list in reading order."""
        out: list[tuple] = []
        self.walk(lambda n, p: out.append((n, p)))
        return out

    def content_refs(self, node) -> list[tuple]:
        """(stream_key, mcid) claimed DIRECTLY by node.

        Honours /MCR /Stm, so content inside a Form XObject is attributed to
        the XObject's stream and never to the page's.
        """
        pi = self.page_of(node)
        out: list[tuple] = []
        for c in _kids(node):
            c_res = _resolve(c)
            if isinstance(c, int):
                if pi is not None:
                    out.append((("page", pi), int(c)))
            elif isinstance(c_res, Dictionary) and str(c_res.get("/Type", "")) == "/MCR":
                if "/MCID" not in c_res:
                    continue
                try:
                    mcid = int(c_res["/MCID"])
                except Exception:
                    continue
                stm = c_res.get("/Stm")
                if stm is not None:
                    stm_obj = _resolve(stm)
                    try:
                        out.append((("xobj", stm_obj.objgen), mcid))
                        continue
                    except Exception:
                        pass
                pg = c_res.get("/Pg")
                tgt = self.page_index.get(pg.objgen) if pg is not None else pi
                if tgt is not None:
                    out.append((("page", tgt), mcid))
        return out

    # backwards-compatible alias: page-stream MCIDs only
    def mcids_of(self, node) -> list[int]:
        pi = self.page_of(node)
        return [m for (k, m) in self.content_refs(node)
                if k == ("page", pi)]

    def subtree_refs(self, node) -> list[tuple]:
        """(stream_key, mcid) for node and everything under it."""
        out: list[tuple] = []

        def rec(n):
            out.extend(self.content_refs(n))
            for c in _child_elements(n):
                rec(c)

        rec(node)
        return out

    def has_objr(self, node) -> bool:
        for c in _kids(node):
            r = _resolve(c)
            if isinstance(r, Dictionary) and str(r.get("/Type", "")) == "/OBJR":
                return True
        return False

    def text_of(self, node) -> bytes:
        buf = b""
        for key, m in self.subtree_refs(node):
            buf += self.scan(key).text_of(m)
        return buf


# ── 1. unwrap /NonStruct + /Private, strip non-unique /T ────────────────────

def unwrap_containers(rp: Repair) -> dict:
    counters = {"unwrapped": 0, "titles": 0}

    def flatten(node) -> list:
        """Return node's kid list with every transparent wrapper spliced away.

        Recursion is bottom-up, so a /NonStruct nested inside another
        /NonStruct is resolved in a single pass — no restart loop, no guard.
        """
        out = []
        for item in _kids(node):
            res = _resolve(item)
            if isinstance(res, Dictionary) and "/S" in res:
                res["/K"] = Array(flatten(res))
                if _stype(res) in TRANSPARENT_WRAPPERS:
                    counters["unwrapped"] += 1
                    out.extend(_kids(res))     # promote children in place
                    continue
            out.append(item)
        return out

    rp.root["/K"] = Array(flatten(rp.root))

    # /T titles must be unique or absent; PDFix stamps "Page 1", "Page 2", ...
    # on container elements, which the QA tester flags as non-unique structure
    # element names. They carry no accessibility value, so drop them entirely.
    for node, _ in rp.elements():
        if "/T" in node:
            del node["/T"]
            counters["titles"] += 1

    return {"wrappers_unwrapped": counters["unwrapped"],
            "titles_removed": counters["titles"]}


# ── 2. <Figure> holding real text ───────────────────────────────────────────

def detag_text_figures(rp: Repair) -> dict:
    retagged = 0
    split = 0

    for node, parent in rp.elements():
        if _stype(node) != "/Figure":
            continue
        pi = rp.page_of(node)
        if pi is None:
            continue
        scan = rp.scan(("page", pi))
        mcids = rp.mcids_of(node)
        if not mcids:
            continue
        # An MCID that paints text AND an image (or a path) is not safely
        # separable — leave it inside the Figure.
        text_mcids = [m for m in mcids if _is_text_only(scan, m)]
        image_mcids = [m for m in mcids if m not in text_mcids]

        if not text_mcids:
            continue

        if not image_mcids and not _child_elements(node):
            # Pure-text "figure": it is a paragraph, not an image.
            node["/S"] = Name("/P")
            for key in ("/Alt", "/ActualText", "/BBox"):
                if key in node:
                    del node[key]
            if "/A" in node:
                del node["/A"]
            retagged += 1
            continue

        # Mixed: keep the image inside <Figure>, pop the text out to a sibling <P>.
        keep, moved = [], []
        for c in _kids(node):
            c_res = _resolve(c)
            m = None
            if isinstance(c, int):
                m = int(c)
            elif isinstance(c_res, Dictionary) and str(c_res.get("/Type", "")) == "/MCR" and "/MCID" in c_res:
                try:
                    m = int(c_res["/MCID"])
                except Exception:
                    m = None
            if m is not None and m in text_mcids:
                moved.append(c)
            else:
                keep.append(c)

        if not moved or not keep:
            continue

        _set_kids(node, keep)
        p_elem = rp.pdf.make_indirect(Dictionary(
            S=Name("/P"),
            P=parent,
            Pg=node.get("/Pg"),
            K=Array(moved),
        ))
        pk = _kids(parent)
        idx = len(pk)
        for i, item in enumerate(pk):
            if isinstance(_resolve(item), Dictionary) and _same(_resolve(item), node):
                idx = i + 1
                break
        pk.insert(idx, p_elem)
        _set_kids(parent, pk)
        split += 1

    return {"figures_retagged_to_p": retagged, "figures_split": split}


# ── 3. reclaim readable /Artifact content ───────────────────────────────────

def reclaim_artifacts(rp: Repair) -> dict:
    """Convert top-level /Artifact sequences that paint readable text back into
    tagged <P> content, and wire the new elements into the structure tree at the
    right reading-order position.

    Genuine artifacts (running header/footer, page numbers, decorative paint,
    subset-encoded furniture) are not readable ASCII and are left alone.
    """
    reclaimed = 0
    pages_touched = 0
    kept_declared = 0          # typed artifacts deliberately left alone

    # Where do new <P> elements go?  Prefer the document's single /Sect, else
    # /Document, else StructTreeRoot.
    host = None
    for node, _ in rp.elements():
        if _stype(node) == "/Sect":
            host = node
            break
    if host is None:
        for node, _ in rp.elements():
            if _stype(node) == "/Document":
                host = node
                break
    if host is None:
        return {"artifacts_reclaimed": 0, "pages_touched": 0,
                "declared_artifacts_kept": 0}

    # element that claims a given (page, mcid) — used to place new siblings
    claim: dict[tuple[int, int], Any] = {}
    for node, _ in rp.elements():
        pi = rp.page_of(node)
        if pi is None:
            continue
        for m in rp.mcids_of(node):
            claim.setdefault((pi, m), node)

    def top_ancestor(node):
        """Ancestor of `node` that is a direct child of `host`."""
        cur = node
        for _ in range(40):
            par = _resolve(cur.get("/P")) if "/P" in cur else None
            if par is None or not isinstance(par, Dictionary):
                return None
            if _same(par, host):
                return cur
            cur = par
        return None

    for pi in range(len(rp.pdf.pages)):
        page = rp.pdf.pages[pi]
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue

        scan = rp.scan(("page", pi))
        next_mcid = scan.max_mcid + 1

        # Pass 1 — locate top-level /Artifact blocks with readable text.
        # Also remember, for each, the last MCID seen before it (reading order).
        blocks: list[dict] = []
        stack: list[str] = []
        cur: dict | None = None
        last_mcid: int | None = None
        has_nested_tag = False

        for i, (operands, op) in enumerate(instrs):
            o = str(op)
            if o in ("BDC", "BMC"):
                tag = str(_resolve(operands[0])) if operands else ""
                if cur is None and tag == "/Artifact" and len(stack) == 0:
                    # An artifact that DECLARES its type is a deliberate one —
                    # pagination furniture marked by an earlier stage (see
                    # heading_normalizer._pagination_artifact) or by the
                    # original producer. Reclaiming it undoes that decision:
                    # running headers are readable ASCII, so the _is_readable
                    # test below cannot tell them from body text PDFix
                    # artifacted by mistake. The declaration is the only
                    # reliable signal, so honour it.
                    props = _resolve(operands[1]) if len(operands) > 1 else None
                    declared = isinstance(props, Dictionary) and (
                        str(props.get("/Type", "")) == "/Pagination"
                        or str(props.get("/Subtype", ""))
                        in ("/Header", "/Footer", "/Watermark")
                    )
                    cur = {"open": i, "text": b"", "prev_mcid": last_mcid,
                           "depth": len(stack) + 1, "nested_tag": False,
                           "declared": declared}
                elif cur is not None and tag != "/Artifact":
                    cur["nested_tag"] = True
                if o == "BDC" and len(operands) > 1:
                    prop = _resolve(operands[1])
                    if isinstance(prop, Dictionary) and "/MCID" in prop:
                        try:
                            last_mcid = int(prop["/MCID"])
                        except Exception:
                            pass
                stack.append(tag)
            elif o == "EMC":
                if cur is not None and len(stack) == cur["depth"]:
                    cur["close"] = i
                    would_reclaim = _is_readable(cur["text"]) and not cur["nested_tag"]
                    if not would_reclaim:
                        pass                       # never a candidate anyway
                    elif cur.get("declared"):
                        kept_declared += 1         # readable, but deliberately artifacted
                    else:
                        blocks.append(cur)
                    cur = None
                if stack:
                    stack.pop()
            elif o in TEXT_SHOW_OPS and cur is not None:
                cur["text"] += _shown_bytes(operands, o)

        if not blocks:
            continue

        # Pass 2 — rewrite the opening operator of each reclaimed block.
        assigned: list[tuple[int, int | None]] = []   # (new_mcid, prev_mcid)
        open_map: dict[int, int] = {}
        for b in blocks:
            open_map[b["open"]] = next_mcid
            assigned.append((next_mcid, b["prev_mcid"]))
            next_mcid += 1

        new_instrs = []
        for i, (operands, op) in enumerate(instrs):
            if i in open_map:
                mcid = open_map[i]
                new_instrs.append(
                    pikepdf.ContentStreamInstruction(
                        [Name("/P"), Dictionary(MCID=mcid)],
                        pikepdf.Operator("BDC"),
                    )
                )
            else:
                new_instrs.append(pikepdf.ContentStreamInstruction(operands, op))

        page.Contents = rp.pdf.make_stream(
            pikepdf.unparse_content_stream(new_instrs)
        )
        pages_touched += 1

        # Pass 3 — create <P> elements and splice them into reading order.
        page_obj = page.obj
        for new_mcid, prev_mcid in assigned:
            p_elem = rp.pdf.make_indirect(Dictionary(
                S=Name("/P"),
                P=host,
                Pg=page_obj,
                K=Array([new_mcid]),
            ))

            anchor = None
            if prev_mcid is not None:
                owner = claim.get((pi, prev_mcid))
                if owner is not None:
                    anchor = top_ancestor(owner)

            hk = _kids(host)
            if anchor is None:
                # No anchor: APPEND (never prepend). insert(0) here reversed the
                # whole document — pages are processed 0..N ascending, so a
                # prepend puts page N first, giving the 21->0 reading-order
                # collapse. Appending keeps ascending page/stream order; the
                # final reading_order pass then places these precisely.
                hk.append(p_elem)
            else:
                idx = len(hk)
                for j, item in enumerate(hk):
                    if isinstance(_resolve(item), Dictionary) and _same(_resolve(item), anchor):
                        idx = j + 1
                        break
                hk.insert(idx, p_elem)
            _set_kids(host, hk)

            claim[(pi, new_mcid)] = p_elem
            reclaimed += 1

        # the page's marked content changed — drop the cached scan
        rp._scans.pop(("page", pi), None)

    return {"artifacts_reclaimed": reclaimed, "pages_touched": pages_touched,
            "declared_artifacts_kept": kept_declared}


# ── 4. list structure ───────────────────────────────────────────────────────

_BULLET_CODES = set("\u2022\u25cf\u25aa\u25a0\u2023\u2043-*\u2219\u00b7\u27a2\u21e8")


def normalise_lists(rp: Repair) -> dict:
    fixed_li = 0
    boxed = 0
    numbering_set = 0

    for node, _ in rp.elements():
        s = _stype(node)

        if s == "/L":
            # Every direct child of <L> must be an <LI> (or a <Caption>).
            kids = _kids(node)
            new_kids = []
            for c in kids:
                c_res = _resolve(c)
                if isinstance(c_res, Dictionary) and _stype(c_res) in ("/LI", "/Caption"):
                    new_kids.append(c)
                else:
                    li = rp.pdf.make_indirect(Dictionary(
                        S=Name("/LI"), P=node,
                        K=Array([rp.pdf.make_indirect(Dictionary(
                            S=Name("/LBody"), P=None, K=Array([c]),
                        ))]),
                    ))
                    li["/K"][0]["/P"] = li
                    new_kids.append(li)
                    boxed += 1
            if len(new_kids) != len(kids) or boxed:
                _set_kids(node, new_kids)

            # /ListNumbering must reflect reality: only claim labels exist if
            # at least one <LI> actually carries an <Lbl>.
            has_lbl = False
            lbl_text = b""
            for li in _child_elements(node):
                for c in _child_elements(li):
                    if _stype(c) == "/Lbl":
                        has_lbl = True
                        lbl_text += rp.text_of(c)
            if has_lbl:
                txt = lbl_text.decode("latin-1", "ignore").strip()
                if txt and txt[0].isdigit():
                    numbering = Name("/Decimal")
                elif txt and txt[0].isalpha():
                    numbering = Name("/LowerAlpha") if txt[0].islower() else Name("/UpperAlpha")
                else:
                    numbering = Name("/Disc")
            else:
                numbering = Name("/None")
            node["/A"] = rp.pdf.make_indirect(Dictionary(
                O=Name("/List"), ListNumbering=numbering
            ))
            numbering_set += 1

        elif s == "/LI":
            # <LI> may only contain <Lbl> and <LBody>; anything else (a bare
            # MCID, a stray <P>) gets boxed into an <LBody>.
            kids = _kids(node)
            lbls, bodies, strays = [], [], []
            for c in kids:
                c_res = _resolve(c)
                t = _stype(c_res) if isinstance(c_res, Dictionary) else ""
                if t == "/Lbl":
                    lbls.append(c)
                elif t == "/LBody":
                    bodies.append(c)
                else:
                    strays.append(c)
            if strays:
                if bodies:
                    body = _resolve(bodies[0])
                    bk = _kids(body)
                    bk.extend(strays)
                    _set_kids(body, bk)
                else:
                    body = rp.pdf.make_indirect(Dictionary(
                        S=Name("/LBody"), P=node, K=Array(strays),
                    ))
                    bodies.append(body)
                boxed += len(strays)
            if not bodies:
                bodies.append(rp.pdf.make_indirect(Dictionary(
                    S=Name("/LBody"), P=node, K=Array([]),
                )))
            ordered = lbls + bodies      # Lbl must precede LBody
            if [id(x) for x in ordered] != [id(x) for x in kids]:
                _set_kids(node, ordered)
                fixed_li += 1

    return {"list_items_fixed": fixed_li, "list_children_boxed": boxed,
            "list_numbering_set": numbering_set}


# ── 5. empty tags ───────────────────────────────────────────────────────────

def drop_empty_tags(rp: Repair) -> dict:
    """Remove structure elements that reference NOTHING.

    THE HARD RULE: an element may be removed only if it claims **no marked
    content at all**. If it claims an MCID, that MCID stays in the content
    stream regardless — so deleting the element does not "clean up" anything,
    it merely ORPHANS the content and PAC reports it as "content is not
    tagged". (That is exactly what an earlier version of this function did:
    it treated an MCID sequence that paints a table rule or a box fill as
    "empty" because it contained no text and no image, deleted 130 elements,
    and left 69 unclaimed MCIDs behind.)

    Whitespace-only text is NOT grounds for deletion either — the MCID exists.
    Only truly contentless shells (no MCID, no OBJR, no child element) go.
    """
    counters = {"removed": 0}

    def is_shell(node) -> bool:
        if _child_elements(node):
            return False
        if rp.has_objr(node):
            return False
        if rp.content_refs(node):
            return False          # claims content -> deleting it orphans that content
        return True

    def prune(node) -> list:
        """Bottom-up, so a parent emptied by its children being pruned is caught
        in the same pass."""
        out = []
        for item in _kids(node):
            res = _resolve(item)
            if isinstance(res, Dictionary) and "/S" in res:
                res["/K"] = Array(prune(res))
                if is_shell(res):
                    counters["removed"] += 1
                    continue
            out.append(item)
        return out

    rp.root["/K"] = Array(prune(rp.root))
    return {"empty_tags_removed": counters["removed"]}


# ── 6. headings: exactly one H1, no skipped levels ──────────────────────────

def enforce_single_h1(rp: Repair) -> dict:
    demoted = 0
    clamped = 0

    # Walk <Title> alongside the real headings: it role-maps to H1 and so takes
    # part in the outline. It is never retagged — it is not a heading, it is the
    # document title — but it seeds seen_h1/prev so the heading that follows it
    # correctly stays at H2 instead of being clamped up to H1.
    outline = [(n, p) for n, p in rp.elements() if _stype(n) in OUTLINE_TAGS]
    if not any(_stype(n) in HEADING_TAGS for n, _ in outline):
        return {"h1_demoted": 0, "levels_clamped": 0}

    # The document title is the FIRST heading in reading order. Everything else
    # starts at H2 — an H1 may appear only once (PDF/UA + PAC HDR-002).
    seen_h1 = False
    prev = 0
    for node, _ in outline:
        if _stype(node) == TITLE_TAG:
            seen_h1 = True                     # <Title> resolves to H1
            prev = TITLE_EQUIVALENT_LEVEL
            continue
        lvl = int(_stype(node)[2])
        if lvl == 1:
            if seen_h1:
                lvl = 2
                demoted += 1
            else:
                seen_h1 = True
        # never skip a level relative to the previous heading
        if lvl > prev + 1:
            lvl = prev + 1
            clamped += 1
        lvl = max(1, min(lvl, 6))
        if not seen_h1 and lvl == 1:
            seen_h1 = True
        tag = f"/H{lvl}"
        if _stype(node) != tag:
            node["/S"] = Name(tag)
        prev = lvl

    return {"h1_demoted": demoted, "levels_clamped": clamped}


def reapply_heading_levels(pdf_path: str) -> dict:
    """Re-open a saved PDF and re-enforce single-H1 + no-skip heading nesting in
    its FINAL reading order.

    WHY THIS IS SEPARATE FROM enforce_single_h1
    -------------------------------------------
    enforce_single_h1 clamps heading levels while walking the struct tree in
    reading order — but it runs BEFORE the reading-order reflow at the end of
    repair(). That reflow re-sorts the struct tree by page/column geometry, so a
    heading sequence that was skip-free in the old order can end up with a deep
    heading placed right after a shallow one, recreating exactly the PAC error
    "Numbered heading skips one or more heading levels". The clamp must therefore
    be re-applied ONCE MORE, on the final tag order, as the very last structural
    step. This is fully generic — it makes no document-specific assumptions, it
    just guarantees, for any PDF: exactly one H1 and level[i] <= level[i-1] + 1.

    Idempotent and non-fatal: a failure here leaves the file exactly as the
    reflow left it (never worse), so it can never regress the pipeline.
    """
    try:
        # allow_overwriting_input loads the file fully into memory, so saving
        # back over the same path is safe (also Windows-safe).
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            if pdf.Root.get("/StructTreeRoot") is None:
                return {"reheading": "no_structtree"}
            rp = Repair(pdf)
            stats = enforce_single_h1(rp)
            pdf.save(pdf_path)
        return {"reheading_h1_demoted": stats.get("h1_demoted", 0),
                "reheading_levels_clamped": stats.get("levels_clamped", 0)}
    except Exception as exc:
        return {"reheading": f"error: {exc}"}


# ── 6.2 artifact orphan marked-content inside StructParents-less forms ───────

def artifact_orphan_form_content(rp: Repair) -> dict:
    """Re-mark MCID content inside Form XObjects that have no /StructParents.

    A Form XObject that paints marked content (BDC <</MCID n>>) but carries no
    /StructParents cannot be mapped into the structure tree — the MCID points
    nowhere. PAC reports the content as untagged (WCAG 1.3.1 / "content is not
    tagged"). In these textbooks it is decorative furniture PDFix left behind
    (e.g. the stylised chapter-number "2" drawn in its own form).

    Since the content is, by definition, unreachable from the tree, the safe
    resolution is to declare it an artifact: rewrite "/Tag <</MCID n>> BDC" to
    "/Artifact BMC" inside the form stream. Genuinely readable content that a
    human wants tagged would need /StructParents + struct elements added by
    hand; this pass only guarantees the file is not flagged for orphan content.
    """
    pdf = rp.pdf
    seen = set()
    forms_fixed = 0
    seqs_remarked = 0

    for page in pdf.pages:
        res = page.obj.get("/Resources")
        if res is None:
            continue
        xod = res.get("/XObject")
        if xod is None:
            continue
        for _nm, xo in xod.items():
            xo = _resolve(xo)
            # Form XObjects are pikepdf.Stream, not Dictionary — accept both.
            if not isinstance(xo, (pikepdf.Dictionary, pikepdf.Stream)):
                continue
            if str(xo.get("/Subtype", "")) != "/Form":
                continue
            try:
                og = xo.objgen
            except Exception:
                continue
            if og in seen:
                continue
            seen.add(og)
            if "/StructParents" in xo:
                continue
            try:
                instrs = list(pikepdf.parse_content_stream(xo))
            except Exception:
                continue
            if not any(str(op) == "BDC" and len(ops) > 1
                       and isinstance(_resolve(ops[1]), Dictionary)
                       and "/MCID" in _resolve(ops[1])
                       for ops, op in instrs):
                continue
            out = []
            changed = False
            for ops, op in instrs:
                o = str(op)
                if o == "BDC" and len(ops) > 1:
                    prop = _resolve(ops[1])
                    if isinstance(prop, Dictionary) and "/MCID" in prop:
                        out.append(pikepdf.ContentStreamInstruction(
                            [Name("/Artifact")], pikepdf.Operator("BMC")))
                        changed = True
                        seqs_remarked += 1
                        continue
                out.append(pikepdf.ContentStreamInstruction(ops, op))
            if changed:
                xo.write(pikepdf.unparse_content_stream(out))
                forms_fixed += 1

    return {"orphan_forms_artifacted": forms_fixed,
            "orphan_form_seqs_remarked": seqs_remarked}


# ── 6.3 ensure block Figures carry /Placement /Block ────────────────────────

def enforce_figure_placement(rp: Repair) -> dict:
    """Give every block-level <Figure> a Layout attribute with /Placement /Block.

    PAC warns "Possibly inappropriate use of a Figure structure element" on any
    Figure used as a BLOCK element that lacks /Placement /Block. Per the PDF
    spec a Figure is inline by default; a standalone illustration is block-level
    and must say so, or assistive technology may present it in the wrong place.

    PDFix sets this on some figures but not all, so a document ends up with a
    mix — the ones without the attribute are exactly PAC's warning list. Every
    figure in these textbooks is a standalone graphic (its own /BBox, not woven
    into a text run), so the safe, general rule is: if a Figure's Layout
    attribute is missing /Placement, add /Placement /Block. Figures that already
    declare a placement (Block or Inline) are left untouched.
    """
    fixed = 0

    def _layout_dict(node):
        """Return the /O /Layout attribute dict, creating /A if needed."""
        a = node.get("/A")
        if a is None:
            d = Dictionary(O=Name("/Layout"))
            node["/A"] = d
            return d
        # /A may be a single dict or an array of attribute dicts
        if isinstance(a, Array):
            for x in a:
                xr = _resolve(x)
                if isinstance(xr, Dictionary) and str(xr.get("/O", "")) == "/Layout":
                    return xr
            d = Dictionary(O=Name("/Layout"))
            a.append(d)
            return d
        if isinstance(a, Dictionary):
            if str(a.get("/O", "")) == "/Layout":
                return a
            # wrap the existing single attribute plus a new Layout dict
            d = Dictionary(O=Name("/Layout"))
            node["/A"] = Array([a, d])
            return d
        # unexpected type — replace
        d = Dictionary(O=Name("/Layout"))
        node["/A"] = d
        return d

    for node, _parent in rp.elements():
        if _stype(node) != "/Figure":
            continue
        lay = _layout_dict(node)
        if "/Placement" not in lay:
            lay["/Placement"] = Name("/Block")
            fixed += 1

    return {"figure_placement_set": fixed}


# ── 6.4 artifact decorative running furniture ───────────────────────────────

def artifact_running_furniture(rp: Repair) -> dict:
    """Re-tag footer/header page-number badges as /Artifact instead of /Figure.

    PDFix tags the little page-number circle in the running footer as a
    <Figure Alt="7">. It is pagination, not content: PDF/UA wants it as an
    ARTIFACT, and PAC otherwise raises "Possibly inappropriate use of a Figure
    structure element" on every one of them.

    A figure is treated as running furniture only when ALL of these hold, so a
    real illustration can never be silently hidden:
      * its content is entirely in the PAGE stream (no Form-XObject content),
      * it paints NO image and NO readable text — only vector paths,
      * it has no child structure elements and no /OBJR,
      * its /Alt is empty or a bare page number (<=3 chars, digits only),
      * its /BBox sits within 60pt of the top or bottom page edge.

    For each match: the page-stream marked content for its MCIDs is rewritten
    from "/Tag <</MCID n>> BDC ... EMC" to "/Artifact BMC ... EMC" (the content
    stays on the page, now as an artifact), and the struct element is detached
    from its parent. rebuild_parent_tree (run next) drops the freed MCID slots.
    """
    pdf = rp.pdf

    def _numeric_or_empty(alt: str) -> bool:
        s = (alt or "").strip()
        return s == "" or (len(s) <= 3 and s.isdigit())

    # page_index -> set(mcid) to convert to artifact ; and elements to detach
    to_artifact: dict[int, set] = {}
    detach: list = []

    for node, parent in rp.elements():
        if _stype(node) != "/Figure":
            continue
        pi = rp.page_of(node)
        if pi is None:
            continue
        # page-stream content only
        refs = rp.content_refs(node)
        if not refs or any(k != ("page", pi) for (k, _m) in refs):
            continue
        if _child_elements(node) or rp.has_objr(node):
            continue
        scan = rp.scan(("page", pi))
        mcids = [m for (_k, m) in refs]
        # no image, no readable text — vector paths only
        painted_text = any(_is_readable(scan.text_of(m)) for m in mcids)
        if painted_text:
            continue
        # detect an image XObject inside any of these mcids
        # (StreamScan marks image paints as nontext ink but not text; to be safe
        #  we require the figure to have NO /Alt describing a picture -> handled
        #  by the numeric/empty Alt gate below, and no raster is asserted by the
        #  geometry gate: badges are tiny footer vectors.)
        alt = str(node.get("/Alt", "")) if "/Alt" in node else ""
        if not _numeric_or_empty(alt):
            continue
        a = node.get("/A")
        bbox = a.get("/BBox") if isinstance(a, Dictionary) else None
        if bbox is None:
            continue
        try:
            y0, y1 = float(bbox[1]), float(bbox[3])
        except Exception:
            continue
        mb = pdf.pages[pi].obj.get("/MediaBox")
        try:
            page_h = float(mb[3]) - float(mb[1])
        except Exception:
            page_h = 792.0
        near_bottom = y0 <= 60
        near_top = (page_h - y1) <= 60
        if not (near_bottom or near_top):
            continue

        to_artifact.setdefault(pi, set()).update(mcids)
        detach.append((node, parent))

    if not detach:
        return {"furniture_artifacted": 0, "furniture_mcids_remarked": 0}

    # ── rewrite each affected page content stream ──────────────────────────
    remarked = 0
    for pi, mcids in to_artifact.items():
        page = pdf.pages[pi]
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue
        out = []
        # stack of (is_target_bdc) so we can drop the matching EMC's property
        depth_is_target = []
        changed = False
        for operands, op in instrs:
            o = str(op)
            if o == "BDC" and len(operands) > 1:
                prop = _resolve(operands[1])
                mcid = None
                if isinstance(prop, Dictionary) and "/MCID" in prop:
                    try:
                        mcid = int(prop["/MCID"])
                    except Exception:
                        mcid = None
                if mcid is not None and mcid in mcids:
                    # rewrite this BDC as an /Artifact BMC (no MCID)
                    out.append(pikepdf.ContentStreamInstruction(
                        [Name("/Artifact")], pikepdf.Operator("BMC")))
                    depth_is_target.append(True)
                    remarked += 1
                    changed = True
                    continue
                depth_is_target.append(False)
                out.append(pikepdf.ContentStreamInstruction(operands, op))
            elif o in ("BDC", "BMC"):
                depth_is_target.append(False)
                out.append(pikepdf.ContentStreamInstruction(operands, op))
            elif o == "EMC":
                if depth_is_target:
                    depth_is_target.pop()
                out.append(pikepdf.ContentStreamInstruction(operands, op))
            else:
                out.append(pikepdf.ContentStreamInstruction(operands, op))
        if changed:
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))

    # ── detach the figure elements from their parents ──────────────────────
    def _key(n):
        try:
            return n.objgen
        except Exception:
            return id(n)

    detach_keys = {_key(n) for (n, _p) in detach}
    for node, parent in rp.elements():
        if parent is None:
            continue
        pk = _kids(parent)
        kept = [c for c in pk if _key(_resolve(c)) not in detach_keys]
        if len(kept) != len(pk):
            _set_kids(parent, kept)
    root = rp.root
    rk = _kids(root)
    kept = [c for c in rk if _key(_resolve(c)) not in detach_keys]
    if len(kept) != len(rk):
        _set_kids(root, kept)

    return {"furniture_artifacted": len(detach),
            "furniture_mcids_remarked": remarked}


# ── 6.5 dedupe duplicate MCID claims ────────────────────────────────────────

def dedupe_mcid_claims(rp: Repair) -> dict:
    """Guarantee every (stream, MCID) is claimed by AT MOST ONE element.

    PAC hard-fails "Structural parent tree / Inconsistent entry found" when two
    structure elements both claim the same marked content. rebuild_parent_tree
    then registers only ONE of them in the ParentTree, so the OTHER element still
    sits in the tree pointing at content the ParentTree attributes elsewhere ->
    the round-trip check PAC runs fails for the loser.

    Any upstream pass can create this: a reading-order rewrap, an artifact
    reclaim, a heading re-tag, a struct-parent rebuild. Rather than guard each
    one, we resolve it once here, at the last structural stage every delivered
    file passes through, immediately before the ParentTree is rebuilt from the
    tree as it then stands.

    Keeper selection, in order of preference:
      1. the element with the most CHILD content (real container beats stub),
      2. otherwise the first claimant in reading order.
    Losing claims are stripped from the loser's /K. A loser left with no /K and
    no /OBJR content is a dead placeholder and is detached from its parent.
    """
    # (stream_key, mcid) -> [elements claiming it], in reading order
    claims: dict[tuple, list] = {}
    parent_of: dict[tuple, Any] = {}

    def _key(node):
        try:
            return node.objgen
        except Exception:
            return id(node)

    for node, parent in rp.elements():
        parent_of[_key(node)] = parent
        for ref in rp.content_refs(node):
            claims.setdefault(ref, []).append(node)

    dup_refs = {ref: els for ref, els in claims.items() if len(els) > 1}

    # element -> set of (stream_key, mcid) refs to strip from its /K
    strip: dict[tuple, set] = {}

    def _weight(el) -> int:
        # how much content this element really owns (direct refs + descendant refs)
        try:
            return len(rp.subtree_refs(el))
        except Exception:
            return len(rp.content_refs(el))

    removed = 0
    for ref, els in dup_refs.items():
        # stable: highest weight wins; ties fall to earliest in reading order
        keeper = max(range(len(els)), key=lambda i: (_weight(els[i]), -i))
        for i, el in enumerate(els):
            if i == keeper:
                continue
            strip.setdefault(_key(el), set()).add(ref)
            removed += 1

    if not strip:
        return {"duplicate_mcids_resolved": 0,
                "duplicate_claims_removed": 0,
                "empty_elems_detached": 0}

    def _ref_of_kid(node, kid):
        """The (stream_key, mcid) a single /K entry represents, or None."""
        pi = rp.page_of(node)
        kid_res = _resolve(kid)
        if isinstance(kid, int):
            return (("page", pi), int(kid)) if pi is not None else None
        if isinstance(kid_res, Dictionary) and str(kid_res.get("/Type", "")) == "/MCR":
            if "/MCID" not in kid_res:
                return None
            try:
                mcid = int(kid_res["/MCID"])
            except Exception:
                return None
            stm = kid_res.get("/Stm")
            if stm is not None:
                try:
                    return (("xobj", _resolve(stm).objgen), mcid)
                except Exception:
                    pass
            pg = kid_res.get("/Pg")
            tgt = rp.page_index.get(pg.objgen) if pg is not None else pi
            return (("page", tgt), mcid) if tgt is not None else None
        return None

    detached_keys: set = set()
    detached = 0
    for node, _parent in rp.elements():
        k = _key(node)
        wanted = strip.get(k)
        if not wanted:
            continue
        wanted = set(wanted)  # copy; remove each ref only once
        new_kids = []
        for kid in _kids(node):
            ref = _ref_of_kid(node, kid)
            if ref is not None and ref in wanted:
                wanted.discard(ref)
                continue  # drop this duplicate claim
            new_kids.append(kid)
        if new_kids:
            _set_kids(node, new_kids)
        else:
            # nothing left to own: detach dead placeholder from its parent
            try:
                del node["/K"]
            except Exception:
                pass
            detached_keys.add(k)

    if detached_keys:
        for node, parent in rp.elements():
            if parent is None:
                continue
            pk = _kids(parent)
            kept = [c for c in pk
                    if _key(_resolve(c)) not in detached_keys]
            if len(kept) != len(pk):
                _set_kids(parent, kept)
        # also sweep the struct-tree root
        root = rp.root
        rk = _kids(root)
        kept = [c for c in rk if _key(_resolve(c)) not in detached_keys]
        if len(kept) != len(rk):
            _set_kids(root, kept)
        detached = len(detached_keys)

    return {"duplicate_mcids_resolved": len(dup_refs),
            "duplicate_claims_removed": removed,
            "empty_elems_detached": detached}


# ── 7. rebuild ParentTree + /P back-pointers ────────────────────────────────

def rebuild_parent_tree(rp: Repair) -> dict:
    """Rebuild /ParentTree and every /P back-pointer from the tree as it stands.

    THREE kinds of ParentTree key exist, and all three must be emitted:

      * a PAGE            -> /StructParents on the page; value is an ARRAY
                             indexed by the MCIDs in the page's own stream
      * a FORM XOBJECT    -> /StructParents on the XObject; value is an ARRAY
                             indexed by the MCIDs in the XOBJECT's stream
                             (a separate namespace from the page's!)
      * an ANNOTATION     -> /StructParent on the annot; value is the single
                             element that owns it via /OBJR

    An earlier version emitted only pages and annots. The 13 Form XObjects in a
    typical PDFix-tagged textbook kept their old keys (23, 28, 35, ...) which no
    longer existed in the rebuilt tree -> PAC "Entry for given StructParents key
    not found", and the keys that DID still exist (1, 9, 12, ...) now pointed at
    an unrelated page's array. Hence: emit every stream.
    """
    pdf = rp.pdf
    root = rp.root

    # /P back-pointers first — everything else depends on them.
    def fix_parents(node):
        for c in _kids(node):
            c_res = _resolve(c)
            if isinstance(c_res, Dictionary) and "/S" in c_res:
                c_res["/P"] = node
                fix_parents(c_res)

    for c in _kids(root):
        c_res = _resolve(c)
        if isinstance(c_res, Dictionary) and "/S" in c_res:
            c_res["/P"] = root
            fix_parents(c_res)

    # stream_key -> {mcid: owning element}
    per_stream: dict[tuple, dict[int, Any]] = {}
    objr_owners: list[tuple] = []

    def collect(node):
        for key, mcid in rp.content_refs(node):
            per_stream.setdefault(key, {})[mcid] = node
        for c in _kids(node):
            c_res = _resolve(c)
            if isinstance(c_res, Dictionary):
                if str(c_res.get("/Type", "")) == "/OBJR":
                    ref = c_res.get("/Obj")
                    if ref is not None:
                        objr_owners.append((_resolve(ref), node))
                elif "/S" in c_res:
                    collect(c_res)

    for c in _kids(root):
        c_res = _resolve(c)
        if isinstance(c_res, Dictionary) and "/S" in c_res:
            collect(c_res)

    nums = []
    next_key = 0

    def emit_array(owner_dict, key_name: str, mapping: dict) -> None:
        nonlocal next_key
        top = (max(mapping) + 1) if mapping else 0
        arr = Array([mapping.get(i) for i in range(top)])
        owner_dict[key_name] = next_key
        nums.append(next_key)
        nums.append(pdf.make_indirect(arr))
        next_key += 1

    # pages
    for pi, page in enumerate(pdf.pages):
        emit_array(page.obj, "/StructParents", per_stream.get(("page", pi), {}))

    # form xobjects — one key each, even if empty, so a stale key can't survive
    for key, xobj in rp._xobjs.items():
        mapping = per_stream.get(key, {})
        if mapping:
            emit_array(xobj, "/StructParents", mapping)
        else:
            # no tagged content inside it any more — drop the stale key entirely
            if "/StructParents" in xobj:
                del xobj["/StructParents"]

    # annotations referenced via /OBJR get their own single-element key
    for obj, owner in objr_owners:
        try:
            obj["/StructParent"] = next_key
            nums.append(next_key)
            nums.append(owner)
            next_key += 1
        except Exception:
            pass

    root["/ParentTree"] = pdf.make_indirect(Dictionary(Nums=Array(nums)))
    root["/ParentTreeNextKey"] = next_key

    return {"parent_tree_keys": next_key,
            "xobject_streams": len(rp._xobjs)}


# ── driver ──────────────────────────────────────────────────────────────────

def audit(pdf_path: str) -> dict:
    """Structural health of a PDF, independent of any fixer.

    These four numbers are the ones PAC actually fails a file on, and they are
    exactly the ones a careless fixer regresses:

      unclaimed_mcids   marked content in a stream that NO structure element
                        claims  -> PAC "content is not tagged" (WCAG 1.3.1)
      phantom_mcids     a structure element claiming an MCID that does not
                        exist in the stream it points at
      duplicate_claims  two elements claiming the same (stream, MCID)
      broken_parenttree a /StructParents or /StructParent key that is not in
                        /ParentTree  -> PAC "Structural parent tree"
    """
    out = {"unclaimed_mcids": 0, "phantom_mcids": 0,
           "duplicate_claims": 0, "broken_parenttree": 0, "h1_count": 0,
           "backward_page_jumps": 0}
    with pikepdf.open(pdf_path) as pdf:
        root = pdf.Root.get("/StructTreeRoot")
        if root is None:
            return out
        rp = Repair(pdf)

        # reading-order sanity: how often the page number goes BACKWARDS as the
        # tree is walked in reading order. A sane document is monotonic here;
        # a reclaim/reorder reversal (the 21->0 collapse) spikes this. Tracking
        # it lets repair() REVERT a run that scrambles order — audit() otherwise
        # only saw content/parent-tree integrity, so a reversal shipped clean.
        _pages_seq = []
        for _n, _p in rp.elements():
            _pg = rp.page_of(_n)
            if _pg is not None:
                _pages_seq.append(_pg)
        out["backward_page_jumps"] = sum(
            1 for _a, _b in zip(_pages_seq, _pages_seq[1:]) if _b < _a)

        existing: dict[tuple, set] = {}
        for pi in range(len(pdf.pages)):
            k = ("page", pi)
            existing[k] = set(rp.scan(k).mcid_order)
        for k in rp._xobjs:
            existing[k] = set(rp.scan(k).mcid_order)

        claimed: set = set()
        for node, _ in rp.elements():
            # <Title> role-maps to H1, so it counts toward the single-H1 audit.
            if _stype(node) in ("/H1", TITLE_TAG):
                out["h1_count"] += 1
            for key, mcid in rp.content_refs(node):
                if mcid not in existing.get(key, set()):
                    out["phantom_mcids"] += 1
                if (key, mcid) in claimed:
                    out["duplicate_claims"] += 1
                claimed.add((key, mcid))

        for key, mcids in existing.items():
            out["unclaimed_mcids"] += len(mcids - {m for (k, m) in claimed if k == key})

        pt = root.get("/ParentTree")
        keys: set = set()
        if pt is not None and "/Nums" in pt:
            nums = pt["/Nums"]
            keys = {int(nums[i]) for i in range(0, len(nums), 2)}
        for pi, page in enumerate(pdf.pages):
            sp = page.obj.get("/StructParents")
            if sp is None or int(sp) not in keys:
                out["broken_parenttree"] += 1
        for key, xobj in rp._xobjs.items():
            if not existing.get(key):
                continue
            sp = xobj.get("/StructParents")
            if sp is None or int(sp) not in keys:
                out["broken_parenttree"] += 1
        for page in pdf.pages:
            for a in (page.obj.get("/Annots") or []):
                a = _resolve(a)
                if isinstance(a, Dictionary) and "/StructParent" in a:
                    if int(a["/StructParent"]) not in keys:
                        out["broken_parenttree"] += 1
    return out


def repair(input_path: str, output_path: str) -> dict:
    """Repair, then VERIFY. A repair that damages the file is not shipped.

    Every fixer in this pipeline rewrites content streams and re-parents
    structure elements, and a subtle mistake there does not throw — it produces
    a PDF that opens fine and fails PAC with hundreds of errors. So the output
    is audited against the input before it is accepted: if the repair orphans
    content, invents phantom MCIDs, double-claims content, or breaks the parent
    tree, the ORIGINAL is passed through unchanged and the caller is told.
    A no-op is always better than a regression.
    """
    if pikepdf is None:
        return {"status": "error", "error": "pikepdf not available"}

    result: dict[str, Any] = {"status": "ok"}

    with pikepdf.open(input_path) as pdf:
        if pdf.Root.get("/StructTreeRoot") is None:
            pdf.save(output_path)
            return {"status": "skipped", "error": "no StructTreeRoot"}

        rp = Repair(pdf)

        result.update(unwrap_containers(rp))
        result.update(detag_text_figures(rp))
        result.update(reclaim_artifacts(rp))
        result.update(normalise_lists(rp))
        result.update(drop_empty_tags(rp))
        result.update(enforce_single_h1(rp))
        # Artifact untagged content stranded in StructParents-less form XObjects
        # (decorative furniture PDFix left unmapped) so PAC stops flagging it.
        result.update(artifact_orphan_form_content(rp))
        # Give block-level Figures /Placement /Block so PAC stops warning
        # "Possibly inappropriate use of a Figure structure element".
        result.update(enforce_figure_placement(rp))
        # Re-tag running page-number badges as /Artifact (removes PAC "possibly
        # inappropriate Figure" warnings on pagination furniture). Runs before
        # dedupe/rebuild so freed MCID slots are re-indexed cleanly.
        result.update(artifact_running_furniture(rp))
        # MUST run immediately before rebuild_parent_tree: no element may claim
        # an MCID owned by another, or the rebuilt tree is inconsistent (PAC
        # "Structural parent tree / Inconsistent entry found").
        result.update(dedupe_mcid_claims(rp))
        result.update(rebuild_parent_tree(rp))

        pdf.save(output_path)

    # ── final reading-order pass ────────────────────────────────────────────
    # reclaim_artifacts appends reclaimed <P> content to the host in stream
    # order, never in reading order, so the shipped file's tag sequence is
    # wrong (chapter title after the intro, folios floating, bucket-Sect page
    # interleave). reading_order_fixer sorts the block tree by page + column-
    # aware within-page order. It MUST run here, after every FSR reparent, or
    # its earlier pipeline pass is clobbered. Written to a temp then swapped so
    # the source handle is released first (Windows os.replace safety).
    import os as _os_ro
    try:
        from .reading_order_fixer import fix as _fix_reading_order
    except ImportError:
        from reading_order_fixer import fix as _fix_reading_order
    _tmp_ro = output_path + ".ro.pdf"
    try:
        _fix_reading_order(output_path, _tmp_ro, within_page=True, report=False)
        if _os_ro.path.exists(_tmp_ro) and _os_ro.path.getsize(_tmp_ro) > 0:
            _os_ro.replace(_tmp_ro, output_path)
            result["reading_order"] = "applied"
        else:
            result["reading_order"] = "skipped_no_output"
    except Exception as _ro_e:
        result["reading_order"] = f"error: {_ro_e}"
        if _os_ro.path.exists(_tmp_ro):
            try:
                _os_ro.unlink(_tmp_ro)
            except OSError:
                pass

    # ── re-clamp heading levels in FINAL reading order ──────────────────────
    # The reading-order reflow above re-sorts the struct tree, which can
    # invalidate the heading-level clamp enforce_single_h1 applied earlier and
    # recreate PAC "Numbered heading skips one or more heading levels" errors.
    # Re-running the clamp here, on the shipped tag order, is the authoritative,
    # document-agnostic fix. MUST be the last structural step.
    result.update(reapply_heading_levels(output_path))

    # ── self-check ─────────────────────────────────────────────────────────
    before = audit(input_path)
    after = audit(output_path)
    result["audit_before"] = before
    result["audit_after"] = after

    regressions = [
        k for k in ("unclaimed_mcids", "phantom_mcids",
                    "duplicate_claims", "broken_parenttree",
                    "backward_page_jumps")
        if after[k] > before[k]
    ]
    if regressions:
        import shutil
        shutil.copyfile(input_path, output_path)
        result["status"] = "reverted"
        result["regressions"] = regressions
        result["error"] = (
            "Repair regressed the file ("
            + ", ".join(f"{k}: {before[k]} -> {after[k]}" for k in regressions)
            + "); original passed through unchanged."
        )

    return result


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: final_structure_repair.py <input.pdf> <output.pdf>",
              file=sys.stderr)
        sys.exit(1)
    try:
        res = repair(sys.argv[1], sys.argv[2])
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"status": "error", "error": str(exc)}))
        sys.exit(1)
    print("[FSR] " + json.dumps(res))
    sys.exit(0 if res.get("status") in ("ok", "skipped") else 1)


if __name__ == "__main__":
    main()
