"""
ppt_loader.py
=============
SHARED .pptx -> normalized-context loader for the PPT accessibility engine.

Used by BOTH:
  * the validator agents (ppt_validator/*), which read context["slides"], and
  * the remediator pipeline, which uses the same normalized view to decide what
    to fix and the (slide_index, shape_id) identifiers to locate the real
    python-pptx shapes to modify.

Keeping one loader means the two halves can never disagree about what a slide
"contains". The loader is READ-ONLY: it extracts a plain-dict snapshot and never
mutates the presentation. Remediation re-opens the file for writes and uses the
identifiers below to find each shape.

Returned context
-----------------
{
  "document_name": str,
  "pptx_path": str,
  "total_slides": int,
  "slide_width": float, "slide_height": float,      # points
  "presentation": {title, author, subject, keywords, category, comments,
                   language, created, modified, last_modified_by},
  "slides": [ slide, ... ],
}

slide = {
  "index": int, "slide_id": int, "number": int,     # number == index+1
  "title": str|None, "layout": str|None, "hidden": bool,
  "background": "RRGGBB"|None, "notes": str|None,
  "shapes": [ shape, ... ],
}

shape = {
  "shape_id": int, "name": str, "type": str,        # normalized type name
  "z_order": int, "order": int,                     # reading / z order
  "has_text_frame": bool, "is_title": bool,
  "is_placeholder": bool, "placeholder_type": str|None,
  "decorative": bool, "alt_text": str|None,
  "text": str,
  "paragraphs": [ {"line_breaks": int,
                   "runs": [ {"text","size","font","bold","italic","color"} ]} ],
  "fill_color": "RRGGBB"|None, "autosize": "none"|"shape"|"text"|None,
  "left": float|None, "top": float|None,
  "width": float|None, "height": float|None,        # points
  "image": {"filename","content_type","size_bytes"}|None,
  "table": {"rows","cols","header_row","has_merged","cells"}|None,
  "hyperlinks": [ {"text","url","tooltip"} ],
  "shapes": [ shape, ... ],                          # present for groups
}

Every extraction is wrapped defensively: a malformed shape yields best-effort
data (Nones), never an exception that aborts the whole load.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

# Microsoft "mark as decorative" extension namespace (Office 2017+).
_DECORATIVE_TAG = "decorative"
_EMU_PER_PT = 12700.0


# ------------------------------------------------------------------ scalars --
def _pt(length) -> float | None:
    """python-pptx Length (EMU) -> points, or None."""
    if length is None:
        return None
    try:
        return round(float(length) / _EMU_PER_PT, 1)
    except (TypeError, ValueError):
        return None


def _rgb_or_none(color) -> str | None:
    """A ColorFormat -> 'RRGGBB' only when it is an explicit RGB colour.

    Theme colours cannot be resolved to a hex value without the theme, so they
    return None — the colour-dependent checks then treat them as 'unknown'
    rather than guessing.
    """
    try:
        if color is None or color.type is None:
            return None
        rgb = color.rgb           # raises for non-RGB (theme) colours
        return str(rgb)
    except Exception:
        return None


def _bool(v) -> bool:
    return bool(v) if v is not None else False


# ------------------------------------------------------------- xml helpers --
def _first_cNvPr(shape):
    try:
        els = shape._element.xpath(".//p:cNvPr")
        return els[0] if els else None
    except Exception:
        return None


def _alt_text(shape) -> str | None:
    cNvPr = _first_cNvPr(shape)
    if cNvPr is None:
        return None
    descr = cNvPr.get("descr")
    if descr and descr.strip():
        return descr.strip()
    # Some tools store alt text only in the title attribute.
    title = cNvPr.get("title")
    return title.strip() if title and title.strip() else None


def _is_decorative(shape) -> bool:
    """True if the shape carries the Office 'mark as decorative' extension."""
    cNvPr = _first_cNvPr(shape)
    if cNvPr is None:
        return False
    try:
        for el in cNvPr.iter():
            tag = el.tag.rsplit("}", 1)[-1].lower()
            if _DECORATIVE_TAG in tag:
                val = el.get("val")
                return val is None or str(val) not in ("0", "false")
    except Exception:
        pass
    return False


def _count_breaks(paragraph) -> int:
    try:
        return len(paragraph._p.findall(qn("a:br")))
    except Exception:
        return 0


# --------------------------------------------------------------- type map --
def _shape_type_name(shape) -> str:
    try:
        if shape.is_placeholder:
            return "placeholder"
    except Exception:
        pass
    st = getattr(shape, "shape_type", None)
    mapping = {
        MSO_SHAPE_TYPE.PICTURE: "picture",
        MSO_SHAPE_TYPE.TABLE: "table",
        MSO_SHAPE_TYPE.GROUP: "group",
        MSO_SHAPE_TYPE.TEXT_BOX: "text",
        MSO_SHAPE_TYPE.AUTO_SHAPE: "shape",
        MSO_SHAPE_TYPE.CHART: "chart",
        MSO_SHAPE_TYPE.LINKED_PICTURE: "picture",
        MSO_SHAPE_TYPE.MEDIA: "media",
        MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT: "ole",
    }
    return mapping.get(st, "shape")


def _autosize(text_frame) -> str | None:
    try:
        from pptx.enum.text import MSO_AUTO_SIZE
        a = text_frame.auto_size
        if a == MSO_AUTO_SIZE.NONE:
            return "none"
        if a == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT:
            return "shape"
        if a == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE:
            return "text"
    except Exception:
        pass
    return None


# ----------------------------------------------------------------- runs/tf --
def _run_dict(run) -> dict[str, Any]:
    font = run.font
    return {
        "text": run.text or "",
        "size": (font.size.pt if font.size is not None else None),
        "font": font.name,
        "bold": _bool(font.bold),
        "italic": _bool(font.italic),
        "color": _rgb_or_none(getattr(font, "color", None)),
    }


def _paragraphs(text_frame) -> list[dict[str, Any]]:
    out = []
    for p in text_frame.paragraphs:
        runs = []
        for r in p.runs:
            try:
                runs.append(_run_dict(r))
            except Exception:
                runs.append({"text": getattr(r, "text", "") or ""})
        out.append({"line_breaks": _count_breaks(p), "runs": runs})
    return out


def _hyperlinks(shape) -> list[dict[str, Any]]:
    links = []
    # run-level hyperlinks
    try:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                for r in p.runs:
                    addr = None
                    try:
                        addr = r.hyperlink.address
                    except Exception:
                        addr = None
                    if addr:
                        links.append({"text": r.text or "", "url": addr,
                                      "tooltip": _hlink_tooltip(r)})
    except Exception:
        pass
    # shape-level click action
    try:
        addr = shape.click_action.hyperlink.address
        if addr:
            links.append({"text": shape.name, "url": addr, "tooltip": None})
    except Exception:
        pass
    return links


def _hlink_tooltip(run) -> str | None:
    try:
        for hl in run._r.findall(qn("a:rPr") + "/" + qn("a:hlinkClick")):
            tt = hl.get("tooltip")
            if tt:
                return tt
    except Exception:
        pass
    return None


def _table(shape) -> dict[str, Any] | None:
    try:
        if not shape.has_table:
            return None
    except Exception:
        return None
    try:
        tbl = shape.table
        n_rows, n_cols = len(tbl.rows), len(tbl.columns)
        has_merged = False
        cells = []
        for r in range(n_rows):
            row = []
            for c in range(n_cols):
                cell = tbl.cell(r, c)
                try:
                    if cell.is_merge_origin or cell.is_spanned:
                        has_merged = True
                except Exception:
                    pass
                row.append(cell.text)
            cells.append(row)
        return {"rows": n_rows, "cols": n_cols,
                "header_row": _bool(getattr(tbl, "first_row", False)),
                "has_merged": has_merged, "cells": cells}
    except Exception:
        return None


def _image(shape) -> dict[str, Any] | None:
    try:
        if shape.shape_type not in (MSO_SHAPE_TYPE.PICTURE,
                                    MSO_SHAPE_TYPE.LINKED_PICTURE):
            return None
        img = shape.image
        return {"filename": img.filename, "content_type": img.content_type,
                "size_bytes": len(img.blob)}
    except Exception:
        return None


def _shape_fill(shape) -> str | None:
    try:
        from pptx.enum.dml import MSO_FILL_TYPE
        fill = shape.fill
        if fill.type == MSO_FILL_TYPE.SOLID:
            return _rgb_or_none(fill.fore_color)
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ shapes --
def _shape_dict(shape, order_ctr: list[int]) -> dict[str, Any]:
    z = order_ctr[0]
    order_ctr[0] += 1

    has_tf = False
    try:
        has_tf = shape.has_text_frame
    except Exception:
        has_tf = False

    is_ph, ph_type = False, None
    try:
        if shape.is_placeholder:
            is_ph = True
            ph_type = str(shape.placeholder_format.type)
    except Exception:
        pass

    data: dict[str, Any] = {
        "shape_id": getattr(shape, "shape_id", None),
        "name": getattr(shape, "name", "") or "",
        "type": _shape_type_name(shape),
        "z_order": z,
        "order": z,
        "has_text_frame": has_tf,
        "is_title": False,          # set by caller (needs slide.title)
        "is_placeholder": is_ph,
        "placeholder_type": ph_type,
        "decorative": _is_decorative(shape),
        "alt_text": _alt_text(shape),
        "text": "",
        "paragraphs": [],
        "fill_color": _shape_fill(shape),
        "autosize": None,
        "left": _pt(getattr(shape, "left", None)),
        "top": _pt(getattr(shape, "top", None)),
        "width": _pt(getattr(shape, "width", None)),
        "height": _pt(getattr(shape, "height", None)),
        "image": _image(shape),
        "table": _table(shape),
        "hyperlinks": _hyperlinks(shape),
    }

    if has_tf:
        try:
            data["text"] = shape.text_frame.text or ""
            data["paragraphs"] = _paragraphs(shape.text_frame)
            data["autosize"] = _autosize(shape.text_frame)
        except Exception:
            pass

    # Recurse into groups so nested shapes are validated too.
    try:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            data["shapes"] = [_shape_dict(c, order_ctr) for c in shape.shapes]
    except Exception:
        pass

    return data


def _slide_bg(slide) -> str | None:
    try:
        return _rgb_or_none(slide.background.fill.fore_color)
    except Exception:
        return None


def _slide_hidden(slide) -> bool:
    try:
        return slide._element.get("show") == "0"
    except Exception:
        return False


def _slide_dict(slide, index: int) -> dict[str, Any]:
    try:
        title_shape = slide.shapes.title
    except Exception:
        title_shape = None
    title = None
    title_id = None
    if title_shape is not None:
        try:
            title = title_shape.text or None
            title_id = title_shape.shape_id
        except Exception:
            pass

    order_ctr = [0]
    shapes = []
    for sh in slide.shapes:
        try:
            shapes.append(_shape_dict(sh, order_ctr))
        except Exception:
            continue
    # flag the title shape
    for s in shapes:
        if title_id is not None and s.get("shape_id") == title_id:
            s["is_title"] = True

    notes = None
    try:
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text or None
    except Exception:
        pass

    return {
        "index": index,
        "number": index + 1,
        "slide_id": getattr(slide, "slide_id", None),
        "title": title,
        "layout": (slide.slide_layout.name if slide.slide_layout else None),
        "hidden": _slide_hidden(slide),
        "background": _slide_bg(slide),
        "notes": notes,
        "shapes": shapes,
    }


def _presentation_meta(prs) -> dict[str, Any]:
    cp = prs.core_properties
    def g(attr):
        try:
            v = getattr(cp, attr)
            return v if v else None
        except Exception:
            return None
    return {
        "title": g("title"), "author": g("author"), "subject": g("subject"),
        "keywords": g("keywords"), "category": g("category"),
        "comments": g("comments"), "language": g("language"),
        "created": str(g("created")) if g("created") else None,
        "modified": str(g("modified")) if g("modified") else None,
        "last_modified_by": g("last_modified_by"),
    }


# ------------------------------------------------------------------- public --
def load_ppt_context(pptx_path: str | Path) -> dict[str, Any]:
    """Load a .pptx into the normalized validator/remediator context dict."""
    pptx_path = str(pptx_path)
    prs = Presentation(pptx_path)
    slides = [_slide_dict(s, i) for i, s in enumerate(prs.slides)]
    return {
        "document_name": Path(pptx_path).name,
        "pptx_path": pptx_path,
        "total_slides": len(slides),
        "slide_width": _pt(prs.slide_width),
        "slide_height": _pt(prs.slide_height),
        "presentation": _presentation_meta(prs),
        "slides": slides,
    }


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: ppt_loader.py <in.pptx> [out.json]", file=sys.stderr)
        raise SystemExit(2)
    ctx = load_ppt_context(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else None
    text = json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out} ({ctx['total_slides']} slides)")
    else:
        print(text)
