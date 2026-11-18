#!/usr/bin/env python3
"""
producer_metadata_fixer.py

Replaces the PDFix trial string that PDFix writes into document metadata at
Save() time. Cleans BOTH places it appears:

  * the /Info dictionary  -> /Producer
  * the XMP packet        -> pdf:Producer   (and any stray "PDFix" residue)

This is the module the JOB chain tried to import and failed on:
    No module named 'src.modules.accessibility_pdf.engines.producer_metadata_fixer'
Drop this file at that path (mind the accessibility_pdf vs accessibility_PDF
casing) and keep the public function name your runner imports (fix_producer_metadata).

Note: this only touches metadata. The *visible* page stamp is a separate object
handled by pdfix_watermark_stripper.py -- run that first, then this.

Usage (CLI):
    python producer_metadata_fixer.py in.pdf
    python producer_metadata_fixer.py in.pdf -o out.pdf --producer "Orion Accessibility+"

Importable:
    from producer_metadata_fixer import fix_producer_metadata
    summary = fix_producer_metadata("in.pdf", "out.pdf", producer="Orion Accessibility+")

Exit code 0 on success, 1 on hard error. One JSON summary to stdout; logs to stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import pikepdf

DEFAULT_PRODUCER = "Orion Bits Systems - Accessibility+"

# Any of these substrings (case-insensitive) marks a value as dirty trial residue.
_DIRTY = ("pdfix", "trial version")


def _log(msg: str) -> None:
    print(f"[producer_metadata_fixer] {msg}", file=sys.stderr)


def _is_dirty(value: str | None) -> bool:
    if not value:
        return False
    low = value.lower()
    return any(tok in low for tok in _DIRTY)


def fix_producer_metadata(input_path: str, output_path: str | None = None,
                          producer: str = DEFAULT_PRODUCER,
                          force: bool = False) -> dict:
    """
    Clean the Producer trial string from /Info and XMP.

    force=False : only rewrite when the existing value is trial residue.
    force=True  : always set Producer to `producer`.
    Returns a summary dict.
    """
    out_path = output_path or input_path
    info_before = None
    xmp_before = None
    info_changed = False
    xmp_changed = False
    xmp_residue_cleaned = 0

    with pikepdf.open(input_path, allow_overwriting_input=True) as pdf:
        # ---- /Info dictionary ----
        docinfo = pdf.docinfo
        if "/Producer" in docinfo:
            info_before = str(docinfo["/Producer"])
        if force or _is_dirty(info_before) or info_before is None:
            docinfo["/Producer"] = producer
            info_changed = True

        # ---- XMP packet ----
        try:
            with pdf.open_metadata(set_pikepdf_as_editor=False,
                                   update_docinfo=False) as meta:
                xmp_before = meta.get("pdf:Producer")
                if force or _is_dirty(xmp_before) or xmp_before is None:
                    meta["pdf:Producer"] = producer
                    xmp_changed = True
        except Exception as e:
            _log(f"XMP high-level edit skipped ({e}); trying raw scrub")

        # ---- raw XMP scrub for any residual "PDFix"/"Trial version" anywhere ----
        meta_stream = pdf.Root.get("/Metadata")
        if meta_stream is not None:
            try:
                raw = bytes(meta_stream.read_bytes()).decode("utf-8", "replace")
                cleaned = raw
                # replace trial producer value inside any <pdf:Producer>...</pdf:Producer>
                def _repl(m):
                    return f"{m.group(1)}{producer}{m.group(3)}"
                cleaned, k1 = re.subn(
                    r"(<pdf:Producer[^>]*>)(.*?)(</pdf:Producer>)",
                    lambda m: _repl(m) if _is_dirty(m.group(2)) or force else m.group(0),
                    cleaned, flags=re.DOTALL)
                # attribute form: pdf:Producer="Trial version ..."
                cleaned, k2 = re.subn(
                    r'(pdf:Producer=")([^"]*)(")',
                    lambda m: f'{m.group(1)}{producer}{m.group(3)}'
                    if _is_dirty(m.group(2)) or force else m.group(0),
                    cleaned)
                xmp_residue_cleaned = k1 + k2
                if cleaned != raw:
                    meta_stream.write(cleaned.encode("utf-8"))
                    xmp_changed = True
            except Exception as e:
                _log(f"raw XMP scrub warning: {e}")

        changed = info_changed or xmp_changed
        if changed:
            pdf.save(out_path)
            _log(f"written -> {out_path}")
        elif output_path and output_path != input_path:
            pdf.save(out_path)  # still emit an output copy if one was requested
            _log(f"no change; copied -> {out_path}")
        else:
            _log("no trial residue found; nothing to do")

    summary = {
        "info_producer_before": info_before,
        "info_producer_changed": info_changed,
        "xmp_producer_before": xmp_before,
        "xmp_producer_changed": xmp_changed,
        "xmp_residue_cleaned": xmp_residue_cleaned,
        "producer_set_to": producer if changed else info_before,
        "output": out_path,
        "changed": changed,
    }
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Strip PDFix trial Producer metadata.")
    ap.add_argument("input", help="input PDF")
    ap.add_argument("-o", "--output", help="output PDF (default: in place)")
    ap.add_argument("--producer", default=DEFAULT_PRODUCER,
                    help=f"replacement Producer value (default: {DEFAULT_PRODUCER!r})")
    ap.add_argument("--force", action="store_true",
                    help="always set Producer, even if current value looks clean")
    args = ap.parse_args(argv)
    try:
        summary = fix_producer_metadata(args.input, args.output,
                                        producer=args.producer, force=args.force)
    except Exception as e:
        print(json.dumps({"error": str(e), "changed": False}))
        _log(f"ERROR: {e}")
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def strip_producer(input_path: str, output_path: str | None = None,
                   producer: str = DEFAULT_PRODUCER, force: bool = False) -> dict:
    """
    Adapter matching the name/return-shape the JOB runner imports:
        from .producer_metadata_fixer import strip_producer
        _pr = strip_producer(path, producer="Orion Accessibility Engine")
        _log(... docinfo=_pr['docinfo'] xmp=_pr['xmp'] old=_pr['old'])
    Wraps fix_producer_metadata() and remaps keys.
    """
    r = fix_producer_metadata(input_path, output_path, producer=producer, force=force)
    return {
        "docinfo": r["info_producer_changed"],
        "xmp": r["xmp_producer_changed"],
        "old": r["info_producer_before"],
        "producer": r["producer_set_to"],
        "changed": r["changed"],
    }
