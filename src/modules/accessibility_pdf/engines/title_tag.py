"""
title_tag.py — the document <Title> structure element.

WHY THIS MODULE EXISTS
----------------------
`Title` is a PDF 2.0 (ISO 32000-2) standard structure type.  It is **not** one
of the PDF 1.7 standard types that PDF/UA-1 is built on.  Orion declares
`pdfuaid:part 1`, so emitting a bare `/S /Title` would produce an unmapped,
non-standard structure type and veraPDF would fail the file outright.

The route taken here (TITLE_MODE = "rolemap") is the one Acrobat itself uses:

    /StructTreeRoot /RoleMap << ... /Title /H1 >>
    <</Type /StructElem /S /Title /K [...] >>          <- no /NS key

The element sits in the default (PDF 1.7) namespace where `Title` is
non-standard, and the single RoleMap entry is what makes it legal.  veraPDF
and PAC resolve the role and see a level-1 heading, so PDF/UA-1 conformance
is unchanged; Acrobat's tag tree and modern AT display it as the document
title.

LOAD-BEARING CONSEQUENCE
------------------------
Because the role resolves to H1, the Title element **occupies heading level
1**.  The heading that follows it must stay at H2 — re-levelling it up to H1
would yield two H1s after role resolution and trip the PDF/UA heading-nesting
rule.  Callers must therefore keep their running level counter at 1 after
emitting a Title, not reset it to 0.

THE OTHER ROUTE
---------------
TITLE_MODE = "pdf2" emits `/S /Title` with `/NS` pointing at the PDF 2.0
standard structure namespace and adds no RoleMap entry (PDF 2.0 forbids
remapping its own standard types).  That is the semantically correct form —
the title genuinely stops being a heading — but it requires the document to
declare PDF/UA-2 and it will fail PDF/UA-1 validation.  It is implemented
here so the switch is a one-line change, but it is not the default.
"""

from __future__ import annotations

import re

import pikepdf
from pikepdf import Array, Dictionary, Name, String

# "rolemap" -> PDF/UA-1 safe, /S /Title + RoleMap Title->H1   (default)
# "pdf2"    -> /S /Title + /NS PDF 2.0 SSN, no RoleMap        (needs PDF/UA-2)
TITLE_MODE = "rolemap"

TITLE_TAG = "/Title"

# The role a <Title> resolves to under TITLE_MODE == "rolemap".  Everything
# downstream that reasons about heading levels should treat /Title as this.
TITLE_EQUIVALENT_LEVEL = 1

_PDF2_SSN = "http://iso.org/pdf2/ssn"

_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Document title lookup
# ---------------------------------------------------------------------------

def document_title(pdf: pikepdf.Pdf) -> str:
    """Return the document title from DocInfo /Title, falling back to XMP dc:title.

    Orion's DocumentRemediatorAgent sets both, but this runs as a post-processing
    stage on files that may not have been through that agent, so check both.
    """
    try:
        info = pdf.docinfo
        if info is not None:
            t = info.get("/Title")
            if t:
                s = str(t).strip()
                if s:
                    return s
    except Exception:
        pass

    try:
        meta = pdf.Root.get("/Metadata")
        if meta is not None:
            xmp = meta.read_bytes().decode("utf-8", "replace")
            m = re.search(
                r"<dc:title>.*?<rdf:li[^>]*>(.*?)</rdf:li>", xmp, re.S | re.I
            )
            if m:
                s = _WS_RE.sub(" ", m.group(1)).strip()
                if s:
                    return s
    except Exception:
        pass

    return ""


def title_key(text: str) -> str:
    """Normalised comparison key: casefolded, whitespace-collapsed, punctuation-trimmed."""
    if not text:
        return ""
    s = _WS_RE.sub(" ", str(text)).strip().casefold()
    return s.strip(" \t\r\n.:;,-–—")


def matches_document_title(text: str, doc_key: str, *, min_len: int = 4) -> bool:
    """True if *text* is (or contains) the document title.

    Containment is allowed because the title's marked content often carries
    trailing whitespace or a subtitle fragment in the same sequence, but a very
    short title is not matched by containment — "2023" appearing inside a body
    heading must not win.
    """
    if not doc_key or len(doc_key) < min_len:
        return False
    tk = title_key(text)
    if not tk:
        return False
    return tk == doc_key or doc_key in tk


# ---------------------------------------------------------------------------
# Emitting the tag
# ---------------------------------------------------------------------------

def ensure_title_rolemap(pdf: pikepdf.Pdf) -> bool:
    """Add ``/Title -> /H1`` to the StructTreeRoot RoleMap. Idempotent.

    Returns True if the RoleMap now carries the entry.
    """
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return False

    rm = st.get("/RoleMap")
    if rm is None:
        rm = pdf.make_indirect(Dictionary())
        st["/RoleMap"] = rm

    existing = rm.get("/Title")
    if existing is not None:
        # Respect an existing mapping rather than fighting a tool that already
        # made a decision here — but only if it maps to something heading-like.
        if str(existing) in {"/H1", "/H2", "/H", "/P"}:
            return True

    rm[Name(TITLE_TAG)] = Name("/H1")
    return True


def _pdf2_namespace(pdf: pikepdf.Pdf):
    """Get or create the PDF 2.0 standard structure namespace object."""
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return None

    namespaces = st.get("/Namespaces")
    if isinstance(namespaces, pikepdf.Array):
        for ns in namespaces:
            try:
                if str(ns.get("/NS")) == _PDF2_SSN:
                    return ns
            except Exception:
                continue
    else:
        namespaces = pdf.make_indirect(Array([]))
        st["/Namespaces"] = namespaces

    ns = pdf.make_indirect(
        Dictionary({"/Type": Name("/Namespace"), "/NS": String(_PDF2_SSN)})
    )
    namespaces.append(ns)
    return ns


def apply_title_tag(pdf: pikepdf.Pdf, elem: pikepdf.Dictionary) -> bool:
    """Retag *elem* as the document <Title> and wire up whatever makes it legal.

    Returns True if the element now carries /S /Title.
    """
    if elem is None:
        return False

    try:
        if TITLE_MODE == "pdf2":
            ns = _pdf2_namespace(pdf)
            elem["/S"] = Name(TITLE_TAG)
            if ns is not None:
                elem["/NS"] = ns
            # PDF 2.0 forbids remapping its own standard types: no RoleMap here.
            return True

        # Default: rolemap mode.
        elem["/S"] = Name(TITLE_TAG)
        # A stale /NS from an earlier pass would push the element into a
        # namespace where the RoleMap does not apply.
        if "/NS" in elem:
            del elem["/NS"]
        ensure_title_rolemap(pdf)
        return True
    except Exception:
        return False


def has_title_element(pdf: pikepdf.Pdf) -> bool:
    """True if the structure tree already contains a <Title> element."""
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return False

    seen: set = set()

    def walk(node) -> bool:
        if isinstance(node, pikepdf.Array):
            return any(walk(x) for x in node)
        if not isinstance(node, pikepdf.Dictionary):
            return False
        if node.is_indirect:
            if node.objgen in seen:
                return False
            seen.add(node.objgen)
        if str(node.get("/S", "")) == TITLE_TAG:
            return True
        return walk(node.get("/K"))

    try:
        return walk(st.get("/K"))
    except Exception:
        return False
