"""
alt_text_fixer.py
-----------------
Walk the PDF structure tree, find <Figure> elements missing an /Alt attribute,
and inject one using:
  1. Caption child text   -- if a Caption element exists inside the Figure
  2. Claude vision API    -- render the page and ask Claude to describe it
  3. Fallback             -- "Figure N"

CLI usage:
    python alt_text_fixer.py <input.pdf> <output.pdf>

The Claude API key must be in the environment variable "orion-claude-key".
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import NameObject, TextStringObject

# Try to import anthropic at module level -- fail gracefully if not installed
try:
    import anthropic as _anthropic_mod
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_mod = None
    _ANTHROPIC_AVAILABLE = False

# Force UTF-8 output so Windows cp1252 console doesn't crash on special chars
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ------------------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------------------

def fix_alt_text(input_path: str, output_path: str, api_key: str | None = None) -> dict:
    """
    Walk the structure tree, inject /Alt on every Figure that lacks one.

    Returns a dict:
        figures_found   - total <Figure> elements seen
        alt_added       - how many got a new /Alt
        already_had_alt - how many already had a non-empty /Alt
        failed          - how many we couldn't process
        details         - list of {figure, page, alt, source}
    """
    if api_key is None:
        api_key = os.environ.get("orion-claude-key", "")

    print(f"[ALT] input={input_path!r}")
    print(f"[ALT] output={output_path!r}")
    print(f"[ALT] api_key={'<set>' if api_key else '<missing>'}")

    results: dict[str, Any] = {
        "figures_found": 0,
        "alt_added": 0,
        "already_had_alt": 0,
        "failed": 0,
        "details": [],
    }

    writer = PdfWriter(clone_from=str(input_path))

    # Build page-ref -> page-number index
    page_refs: dict[tuple[int, int], int] = {}
    for i, page in enumerate(writer.pages):
        ref = page.indirect_reference
        if ref is not None:
            page_refs[(ref.idnum, ref.generation)] = i

    print(f"[ALT] pages indexed: {len(page_refs)}")

    # Walk structure tree
    root_obj = writer._root_object
    struct_root = root_obj.get("/StructTreeRoot")
    if not struct_root:
        print("[ALT] No /StructTreeRoot found -- nothing to do")
        with open(output_path, "wb") as fh:
            writer.write(fh)
        return results

    try:
        struct_root = struct_root.get_object()
    except Exception as e:
        print(f"[ALT] Cannot resolve StructTreeRoot: {e}")
        with open(output_path, "wb") as fh:
            writer.write(fh)
        return results

    # Dump first few levels of structure tree for diagnosis
    _dump_tree(struct_root, max_depth=4)

    fig_counter = [0]
    seen: set[int] = set()
    _walk(struct_root, page_refs, api_key, str(input_path), results, seen, fig_counter)

    print(f"[ALT] walk done: found={results['figures_found']} added={results['alt_added']} "
          f"skipped={results['already_had_alt']} failed={results['failed']}")

    with open(output_path, "wb") as fh:
        writer.write(fh)

    print(f"[ALT] saved -> {output_path}")
    return results


# ------------------------------------------------------------------------------
# Structure-tree walker
# ------------------------------------------------------------------------------

def _dump_tree(obj, depth=0, max_depth=4, _seen=None):
    """Print the structure tree for diagnosis."""
    if _seen is None:
        _seen = set()
    if depth > max_depth:
        return
    try:
        obj = obj.get_object()
    except Exception:
        return
    oid = id(obj)
    if oid in _seen:
        return
    _seen.add(oid)
    if not hasattr(obj, "get"):
        print(f"[TREE] {'  ' * depth}LEAF {type(obj).__name__}: {repr(str(obj))[:40]}")
        return
    s = obj.get("/S", "")
    alt = obj.get("/Alt", "")
    keys = [str(k) for k in obj.keys()]
    print(f"[TREE] {'  ' * depth}S={str(s)!r} alt={repr(str(alt))[:30]} keys={keys[:6]}")
    kids = obj.get("/K")
    if kids is None:
        return
    try:
        kids_r = kids.get_object()
    except Exception:
        kids_r = kids
    if hasattr(kids_r, "get"):
        # Single child element (DictionaryObject) -- do NOT iterate its keys
        _dump_tree(kids_r, depth + 1, max_depth, _seen)
    elif hasattr(kids_r, "__iter__") and not isinstance(kids_r, (str, bytes)):
        for kid in list(kids_r)[:10]:
            _dump_tree(kid, depth + 1, max_depth, _seen)
    else:
        print(f"[TREE] {'  ' * (depth+1)}SCALAR {type(kids_r).__name__}: {repr(str(kids_r))[:40]}")


def _walk(obj, page_refs, api_key, pdf_path, results, seen, fig_counter):
    try:
        obj = obj.get_object()
    except Exception:
        return

    obj_id = id(obj)
    if obj_id in seen:
        return
    seen.add(obj_id)

    if not hasattr(obj, "get"):
        return

    elem_type_raw = obj.get("/S")
    elem_type = str(elem_type_raw) if elem_type_raw is not None else ""
    # Strip leading slash for comparison
    elem_type_clean = elem_type.lstrip("/")

    # Debug: print element types so we can see what's in the tree
    if elem_type_clean and len(seen) <= 30:
        print(f"[ALT-TREE] elem_type={elem_type_clean!r}")

    if elem_type_clean == "Figure":
        fig_counter[0] += 1
        fig_num = fig_counter[0]
        results["figures_found"] += 1
        print(f"[ALT] Figure #{fig_num} found")

        current_alt = obj.get("/Alt")
        extracted_prefix = ""
        if current_alt:
            alt_str = str(current_alt).strip()
            alt_lower = alt_str.lower()
            # Check if the alt contains the PDFix "NO ALT TEXT" overlay marker
            has_no_alt_marker = (
                "no alt text" in alt_lower
                or "no alt" in alt_lower
                # Catch garbled variants: "no*alt tex", "no_alt_text", "no-alt-text", etc.
                or bool(re.search(r"no[\s\*_\-]?alt[\s\*_\-]?tex", alt_lower))
                # ✕ (U+2715) is the PDFix badge mark — its presence means the
                # alt text was machine-stamped, not a real description
                or "\u2715" in alt_str
            )
            # Exact junk: only "figure" alone (bare placeholder)
            is_bare_junk = alt_str.lower() == "figure"
            is_junk = not alt_str or has_no_alt_marker or is_bare_junk
            if alt_str and not is_junk:
                # Repair UTF-8-as-Latin1 mojibake in otherwise-valid alt text
                if _is_mojibake(alt_str):
                    fixed = _fix_mojibake(alt_str)
                    if fixed != alt_str:
                        print(f"[ALT] Figure #{fig_num} repairing mojibake: {repr(fixed)[:60]}")
                        try:
                            obj[NameObject("/Alt")] = TextStringObject(fixed)
                        except Exception as _me:
                            print(f"[ALT] Figure #{fig_num} mojibake repair error: {_me}")
                else:
                    print(f"[ALT] Figure #{fig_num} already has /Alt={repr(alt_str)[:60]} -- skipping")
                results["already_had_alt"] += 1
                _recurse_kids(obj, page_refs, api_key, pdf_path, results, seen, fig_counter)
                return
            else:
                print(f"[ALT] Figure #{fig_num} /Alt is junk ({repr(alt_str)[:40]!r}) -- replacing")
                # Try to salvage useful text before the marker
                if has_no_alt_marker:
                    # Split on the marker (handle both clean and garbled versions)
                    for marker in ("\u2715 NO ALT TEXT", "NO ALT TEXT", "\u2022 NO ALT"):
                        if marker.lower() in alt_lower:
                            idx = alt_lower.index(marker.lower())
                            prefix = alt_str[:idx].strip()
                            if len(prefix) > 5 and _is_meaningful_prefix(prefix):
                                extracted_prefix = _clean_extracted_prefix(prefix)
                                print(f"[ALT] Figure #{fig_num} extracted prefix: {repr(extracted_prefix)[:60]}")
                            elif len(prefix) > 5:
                                print(f"[ALT] Figure #{fig_num} prefix rejected (raw data): {repr(prefix)[:60]}")
                            break

        # Determine page number
        page_num = _get_page_num(obj, page_refs)
        print(f"[ALT] Figure #{fig_num} page_num={page_num}")

        # Strategy 1: text salvaged from junk /Alt (before the NO ALT TEXT marker)
        # Repair mojibake in the extracted prefix before using it
        if extracted_prefix and _is_mojibake(extracted_prefix):
            extracted_prefix = _fix_mojibake(extracted_prefix)
        alt_text = extracted_prefix
        source = "extracted-prefix"

        # Strategy 2: caption text
        if not alt_text:
            alt_text = _extract_caption(obj)
            source = "caption"

        if not alt_text:
            # Strategy 3: Claude vision
            if api_key and page_num is not None:
                try:
                    img_bytes = _render_page(pdf_path, page_num)
                    if img_bytes:
                        alt_text = _call_claude(img_bytes, api_key, fig_num)
                        source = "claude-vision"
                        print(f"[ALT] Figure #{fig_num} claude alt={repr(alt_text)[:80]}")
                    else:
                        print(f"[ALT] Figure #{fig_num} no image bytes -- skipping claude")
                except Exception as e:
                    print(f"[ALT] Figure #{fig_num} claude failed: {e}")

        # Strategy 3: fallback
        if not alt_text:
            alt_text = f"Figure {fig_num}"
            source = "fallback"
            print(f"[ALT] Figure #{fig_num} using fallback alt text")

        try:
            obj[NameObject("/Alt")] = TextStringObject(alt_text)
            results["alt_added"] += 1
            results["details"].append({
                "figure": fig_num,
                "page": page_num,
                "alt": alt_text,
                "source": source,
            })
            print(f"[ALT] Figure #{fig_num} /Alt set via {source}: {repr(alt_text)[:60]}")
        except Exception as e:
            print(f"[ALT] Figure #{fig_num} ERROR setting /Alt: {e}")
            results["failed"] += 1

    # Always recurse into kids
    _recurse_kids(obj, page_refs, api_key, pdf_path, results, seen, fig_counter)


def _recurse_kids(obj, page_refs, api_key, pdf_path, results, seen, fig_counter):
    kids = obj.get("/K")
    if kids is None:
        return
    try:
        kids_resolved = kids.get_object()
    except Exception:
        kids_resolved = kids

    # Kids can be:
    #   - a single DictionaryObject (one child) -- iterating it yields KEYS, so check first
    #   - an ArrayObject (multiple children)
    #   - an integer MCID -- skip
    if hasattr(kids_resolved, "get"):
        # Single structure element dictionary
        _walk(kids_resolved, page_refs, api_key, pdf_path, results, seen, fig_counter)
    elif hasattr(kids_resolved, "__iter__") and not isinstance(kids_resolved, (str, bytes)):
        for kid in kids_resolved:
            _walk(kid, page_refs, api_key, pdf_path, results, seen, fig_counter)
    # else: MCID integer or other leaf -- nothing to recurse


# ------------------------------------------------------------------------------
# Mojibake helpers
# ------------------------------------------------------------------------------

def _fix_mojibake(s: str) -> str:
    """Try cp1252 then latin-1 round-trip to fix UTF-8-decoded-as-Windows-encoding mojibake.
    PDFix typically mis-decodes UTF-8 as cp1252 (e.g. em-dash 0xE2 0x80 0x94 -> euro + quotes).
    """
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = s.encode(enc).decode("utf-8")
            if fixed != s and "\ufffd" not in fixed:
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


def _is_mojibake(s: str) -> bool:
    """Detect mojibake by attempting the cp1252/latin-1 round-trip fix."""
    return _fix_mojibake(s) != s


# Noise patterns to strip from the *end* of an extracted prefix:
# e.g. "Conservation Workflow — 4-Step Process Figure 7: ...no alt text provided"
_PREFIX_NOISE_RE = re.compile(
    r"(\s*[\u2014\-]+\s*no\s+alt\s+text\s+provided\.?|"
    r"\s*Figure\s+\d+\s*:[^\n]{0,120})",
    re.IGNORECASE,
)


def _clean_extracted_prefix(text: str) -> str:
    """Strip trailing noise phrases from a candidate extracted prefix."""
    cleaned = _PREFIX_NOISE_RE.sub("", text).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned


def _is_meaningful_prefix(text: str) -> bool:
    """
    Return True only if *text* looks like a real image description,
    not raw chart-axis data or OCR noise.

    Raw data like "100 Revenue (USD '000) 75 50 25 42 Q1 68 Q2 55" has far
    more numeric tokens than meaningful words, so we reject it and let the
    claude-vision path produce a proper description instead.
    """
    # First strip potential noise from the end before evaluating
    cleaned = _clean_extracted_prefix(text)
    words   = re.findall(r"[A-Za-z]{3,}", cleaned)
    numbers = re.findall(r"\b\d[\d,.%]*\b", cleaned)
    if not words:
        return False
    # Reject when numeric tokens outnumber meaningful words by 2:1 or more
    if len(numbers) >= max(2, len(words) * 2):
        return False
    return True

# ------------------------------------------------------------------------------
# Caption extraction
# ------------------------------------------------------------------------------

def _extract_caption(figure_obj) -> str:
    """
    Look for a Caption child inside a Figure element.
    Check /ActualText, /Alt, /T on the Caption element.
    """
    kids = figure_obj.get("/K")
    if kids is None:
        return ""
    try:
        kids_resolved = kids.get_object()
    except Exception:
        return ""

    items = kids_resolved if (hasattr(kids_resolved, "__iter__") and
                              not isinstance(kids_resolved, (str, bytes))) else [kids_resolved]
    for kid in items:
        try:
            k = kid.get_object()
            if not hasattr(k, "get"):
                continue
            s = str(k.get("/S", "")).lstrip("/")
            if s == "Caption":
                for key in ("/ActualText", "/Alt", "/T"):
                    val = k.get(key)
                    if val:
                        txt = str(val).strip()
                        if txt:
                            print(f"[ALT] found Caption text via {key}: {repr(txt)[:60]}")
                            return txt
        except Exception:
            continue
    return ""


# ------------------------------------------------------------------------------
# Page number resolution
# ------------------------------------------------------------------------------

def _get_page_num(obj, page_refs: dict) -> int | None:
    try:
        pg = obj.get("/Pg")
        if pg is None:
            return None
        # pg is typically an IndirectObject
        if hasattr(pg, "idnum"):
            key = (pg.idnum, pg.generation)
            return page_refs.get(key)
        # Already resolved -- try id match
        pg_obj = pg.get_object()
        for (idnum, gen), num in page_refs.items():
            pass  # can't reverse-map from id() reliably, return None
    except Exception:
        pass
    return None


# ------------------------------------------------------------------------------
# Page rendering
# ------------------------------------------------------------------------------

def _render_page(pdf_path: str, page_num: int) -> bytes:
    """Render or extract an image from a PDF page.
    Priority: fitz (pymupdf) -> pdf2image -> pypdf embedded image extraction.
    """
    # Try fitz first
    try:
        import fitz  # pymupdf
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        doc.close()
        print(f"[ALT] rendered page {page_num} via fitz ({len(img_bytes)} bytes)")
        return img_bytes
    except ImportError:
        pass
    except Exception as e:
        print(f"[ALT] fitz render failed: {e}")

    # Try pdf2image
    try:
        import io
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=150, first_page=page_num + 1, last_page=page_num + 1)
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        img_bytes = buf.getvalue()
        print(f"[ALT] rendered page {page_num} via pdf2image ({len(img_bytes)} bytes)")
        return img_bytes
    except ImportError:
        pass
    except Exception as e:
        print(f"[ALT] pdf2image render failed: {e}")

    # Fallback: extract first embedded raster image from the page via pypdf
    return _extract_page_image_pypdf(pdf_path, page_num)


def _extract_page_image_pypdf(pdf_path: str, page_num: int) -> bytes:
    """Extract the largest embedded raster image from a page using pypdf only."""
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    page = reader.pages[page_num]
    best = b""
    try:
        for img in page.images:
            try:
                data = img.data
                if len(data) > len(best):
                    best = data
            except Exception:
                pass
    except Exception as e:
        print(f"[ALT] pypdf image extract error: {e}")
    if best:
        print(f"[ALT] extracted embedded image via pypdf ({len(best)} bytes)")
    else:
        print("[ALT] no embedded image found via pypdf")
    return best


def _render_page_pdf2image(pdf_path: str, page_num: int) -> bytes:
    """Legacy stub -- superseded by _render_page."""
    import io
    from pdf2image import convert_from_path
    images = convert_from_path(pdf_path, dpi=150, first_page=page_num + 1, last_page=page_num + 1)
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------------------------
# Claude Vision API
# ------------------------------------------------------------------------------

def _call_claude(image_bytes: bytes, api_key: str, fig_num: int) -> str:
    """
    Call claude-haiku-4-5-20251001 vision to generate a concise alt text
    for the figure shown in image_bytes (a full page render).
    """
    if not _ANTHROPIC_AVAILABLE:
        print(f"[ALT] Figure #{fig_num} anthropic not installed -- skipping")
        return ""

    client = _anthropic_mod.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "This is a page from a PDF document. "
                        "Generate concise, descriptive alt text (1-2 sentences, under 200 characters) "
                        "for the primary figure, chart, diagram, or image visible on this page. "
                        "Focus on what the image shows and its purpose. "
                        "Do not start with 'This image shows' or 'This figure shows'. "
                        "Return only the alt text, nothing else."
                    ),
                },
            ],
        }],
    )

    raw = response.content[0].text.strip()
    # Truncate to 500 chars as a safety measure
    return raw[:500]


# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: alt_text_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)

    _api_key = os.environ.get("orion-claude-key", "")
    _result = fix_alt_text(sys.argv[1], sys.argv[2], api_key=_api_key)
    print(json.dumps(_result, indent=2))
