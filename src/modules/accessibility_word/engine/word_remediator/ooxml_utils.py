"""Small OOXML helpers shared by the remediators.

Word rejects files whose child elements are out of schema order, so new elements
are always inserted before their first existing successor, never just appended.
"""
from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
TXBX = qn("w:txbxContent")

# Successor lists, taken from the ECMA-376 sequence for each parent.
PPR_OUTLINE_SUCCESSORS = ("w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")
RPR_LANG_SUCCESSORS = ("w:eastAsianLayout", "w:specVanish", "w:oMath")
TRPR_HEADER_SUCCESSORS = ("w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del", "w:trPrChange")
TBLPR_CAPTION_SUCCESSORS = ("w:tblDescription", "w:tblPrChange")


def insert_in_order(parent, child, successors: tuple[str, ...]):
    for tag in successors:
        found = parent.find(qn(tag))
        if found is not None:
            found.addprevious(child)
            return child
    parent.append(child)
    return child


def get_or_insert(parent, tag: str, successors: tuple[str, ...]):
    element = parent.find(qn(tag))
    if element is None:
        element = insert_in_order(parent, OxmlElement(tag), successors)
    return element


def get_or_insert_first(parent, tag: str, after: tuple[str, ...] = ()):
    """For elements that must lead their parent, optionally after the tags in `after`."""
    element = parent.find(qn(tag))
    if element is not None:
        return element
    element = OxmlElement(tag)
    index = 0
    for position, child in enumerate(parent):
        if child.tag in {qn(t) for t in after}:
            index = position + 1
    parent.insert(index, element)
    return element


def is_alternate_fallback(element) -> bool:
    """Fallback duplicates the Choice branch, and the validator reads only Choice."""
    return any(a.tag == MC_FALLBACK for a in element.iterancestors())


def in_text_box(element) -> bool:
    return any(a.tag == TXBX for a in element.iterancestors())


def in_table_cell(element) -> bool:
    return any(a.tag == qn("w:tc") for a in element.iterancestors())


def story_paragraphs(body):
    """Body and table paragraphs, the ones the validator treats as document flow."""
    return [p for p in body.iter(qn("w:p"))
            if not is_alternate_fallback(p) and not in_text_box(p)]


def paragraph_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def has_visual_content(element) -> bool:
    return next(element.iter(qn("w:drawing"), qn("w:pict"), qn("w:object")), None) is not None


def has_page_break(p) -> bool:
    return any(br.get(qn("w:type")) == "page" for br in p.iter(qn("w:br")))


def has_section_break(p) -> bool:
    ppr = p.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:sectPr")) is not None


def table_rows(tbl):
    """Rows that belong to this table only, never to a nested one."""
    for child in tbl:
        if child.tag == qn("w:tr"):
            yield child
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from table_rows(content)


def snippet(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."
