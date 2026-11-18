#!/usr/bin/env python3
"""
pdfix_watermark_stripper.py

Removes the visible PDFix *trial* watermark that PDFix stamps onto page content
at Save() time. Works without the PDFix SDK (pure pikepdf), so it can run as a
JOB-chain post-step after _save_remediated_pdf.

What it does
------------
1. Detects the watermark Form XObject(s) by content signature. The trial stamp is
   a small Form XObject whose own marked content carries
   /Alt(Trial version of PDFix SDK | www.pdfix.net). We match on that signature so
   we never touch a legitimate figure/logo.
2. For every page, walks the content stream at the *token* level (never regex) and
   drops each `/Xn Do` that paints a watermark XObject. If that Do sits alone inside
   an `/Artifact BMC ... EMC` (or BDC) block that paints nothing else, the whole
   artifact block is removed so no empty marked-content shell is left behind.
3. Unreferences the watermark from each page's /Resources /XObject, then garbage
   collects the now-orphaned object on save.

It intentionally does NOT touch any XObject that shows real text (Tj/TJ) or paints
real paths, and it leaves balanced q/Q and BMC/EMC nesting intact.

Usage (CLI):
    python pdfix_watermark_stripper.py in.pdf                 # in place
    python pdfix_watermark_stripper.py in.pdf -o out.pdf
    python pdfix_watermark_stripper.py in.pdf --dry-run

Importable:
    from pdfix_watermark_stripper import strip_watermark
    summary = strip_watermark("in.pdf", "out.pdf")

Exit code is 0 on success (including "nothing to do"), 1 on hard error.
Prints one JSON summary object to stdout; human log lines go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys

import pikepdf

# Signatures that identify the PDFix trial stamp inside a Form XObject stream.
# Case-insensitive substring match on the decoded stream bytes.
_WM_SIGNATURES = (b"trial version of pdfix", b"www.pdfix.net")

# Operators that mean "this block painted real visible content" -> never remove it.
_PAINT_OPS = {"Tj", "TJ", "'", '"', "sh",
              "f", "F", "f*", "S", "s", "B", "B*", "b", "b*"}


def _log(msg: str) -> None:
    print(f"[pdfix_watermark_stripper] {msg}", file=sys.stderr)


def _is_watermark_form(obj) -> bool:
    """True if a Form XObject's own content is the PDFix trial stamp."""
    try:
        if obj.get("/Subtype") != pikepdf.Name("/Form"):
            return False
        data = bytes(obj.read_bytes()).lower()
    except Exception:
        return False
    return any(sig in data for sig in _WM_SIGNATURES)


def _find_watermark_ids(pdf: pikepdf.Pdf) -> set:
    """Object ids (objgen) of every watermark Form XObject in the file."""
    wm = set()
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Stream) and _is_watermark_form(obj):
            wm.add(obj.objgen)
    return wm


def _page_watermark_names(page, wm_ids: set) -> set:
    """Local resource names (e.g. '/Fm2') on this page that map to a watermark id."""
    names = set()
    res = page.get("/Resources")
    if res is None:
        return names
    xobjs = res.get("/XObject")
    if xobjs is None:
        return names
    for name, ref in xobjs.items():
        try:
            if ref.objgen in wm_ids:
                names.add(str(name))
        except Exception:
            continue
    return names


def _strip_page(page, wm_names: set, pdf: pikepdf.Pdf) -> tuple[int, int]:
    """
    Rewrite one page's content stream, removing watermark paints.
    Returns (blocks_removed, loose_dos_removed).
    """
    tokens = list(pikepdf.parse_content_stream(page))
    n = len(tokens)
    out = []
    blocks_removed = 0
    loose_removed = 0

    def op(i):
        return str(tokens[i].operator)

    def operand0(i):
        ops = tokens[i].operands
        return str(ops[0]) if ops else None

    i = 0
    while i < n:
        o = op(i)

        # Candidate artifact wrapper: /Artifact BMC | /Artifact BDC
        if o in ("BMC", "BDC") and operand0(i) == "/Artifact":
            depth = 1
            j = i + 1
            has_wm_do = False
            has_other = False
            while j < n and depth > 0:
                oj = op(j)
                if oj in ("BMC", "BDC"):
                    depth += 1
                elif oj == "EMC":
                    depth -= 1
                    if depth == 0:
                        break
                elif depth == 1 and oj == "Do":
                    if operand0(j) in wm_names:
                        has_wm_do = True
                    else:
                        has_other = True
                elif oj in _PAINT_OPS:
                    has_other = True
                j += 1
            # j indexes the matching EMC (or n if unbalanced)
            if depth == 0 and has_wm_do and not has_other:
                blocks_removed += 1
                i = j + 1  # skip the whole block incl. EMC
                continue
            # otherwise fall through and keep this BMC/BDC normally

        # Loose watermark Do not wrapped in a removable artifact block
        if o == "Do" and operand0(i) in wm_names:
            loose_removed += 1
            i += 1
            continue

        out.append(tokens[i])
        i += 1

    if blocks_removed or loose_removed:
        new_bytes = pikepdf.unparse_content_stream(out)
        page.Contents = pdf.make_stream(new_bytes)
        # Unreference the watermark XObjects from this page's resources
        xobjs = page.get("/Resources", {}).get("/XObject", None)
        if xobjs is not None:
            for name in list(wm_names):
                key = pikepdf.Name(name)
                if key in xobjs:
                    del xobjs[key]

    return blocks_removed, loose_removed


def strip_watermark(input_path: str, output_path: str | None = None,
                    dry_run: bool = False) -> dict:
    """Strip PDFix trial watermarks. Returns a summary dict."""
    out_path = output_path or input_path
    with pikepdf.open(input_path, allow_overwriting_input=True) as pdf:
        wm_ids = _find_watermark_ids(pdf)
        if not wm_ids:
            _log("no PDFix trial watermark XObject found; nothing to do")
            summary = {"watermark_xobjects": 0, "pages_touched": 0,
                       "artifact_blocks_removed": 0, "loose_dos_removed": 0,
                       "output": out_path, "changed": False}
            if not dry_run and output_path and output_path != input_path:
                pdf.save(out_path)
            return summary

        _log(f"watermark XObject ids: {sorted(g[0] for g in wm_ids)}")
        pages_touched = 0
        total_blocks = 0
        total_loose = 0
        touched_pages = []

        for idx, page in enumerate(pdf.pages):
            names = _page_watermark_names(page, wm_ids)
            if not names:
                continue
            blocks, loose = _strip_page(page, names, pdf)
            if blocks or loose:
                pages_touched += 1
                total_blocks += blocks
                total_loose += loose
                touched_pages.append(idx + 1)
                _log(f"page {idx + 1}: names={sorted(names)} "
                     f"blocks_removed={blocks} loose_dos_removed={loose}")

        # Drop orphaned watermark objects from the file.
        try:
            pdf.remove_unreferenced_resources()
        except Exception as e:  # non-fatal
            _log(f"remove_unreferenced_resources warning: {e}")

        summary = {
            "watermark_xobjects": len(wm_ids),
            "pages_touched": pages_touched,
            "pages": touched_pages,
            "artifact_blocks_removed": total_blocks,
            "loose_dos_removed": total_loose,
            "output": out_path,
            "changed": bool(pages_touched),
        }

        if dry_run:
            _log("dry-run: not writing output")
        else:
            pdf.save(out_path)
            _log(f"written -> {out_path}")

    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Strip PDFix trial watermark (pure pikepdf).")
    ap.add_argument("input", help="input PDF")
    ap.add_argument("-o", "--output", help="output PDF (default: in place)")
    ap.add_argument("--dry-run", action="store_true", help="analyze only, do not write")
    args = ap.parse_args(argv)
    try:
        summary = strip_watermark(args.input, args.output, dry_run=args.dry_run)
    except Exception as e:
        print(json.dumps({"error": str(e), "changed": False}))
        _log(f"ERROR: {e}")
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
