"""
font_encoding_fixer.py
======================
Post-processing step for the PDF accessibility pipeline.

Problem
-------
Adobe Acrobat's accessibility checker requires every font to carry a
/ToUnicode CMap so that its character codes can be reliably mapped to
Unicode.  Standard Type1 fonts (Helvetica, ZapfDingbats, …) produced by
tools such as ReportLab and PDFix SDK omit /ToUnicode because the PDF
specification technically allows it for the 14 standard fonts.  Acrobat
does not honor that exemption in its accessibility checker, so the
"Character encoding – Failed" error appears even on otherwise valid PDFs.

Solution
--------
After the main PDFix remediation pass, call ``inject_tounicode()`` on the
output file.  It:

1. Clones the PDF into a pypdf PdfWriter (preserves all content & structure).
2. Iterates every font dictionary across all pages.
3. For fonts that lack /ToUnicode, builds and injects an appropriate CMap:
   - WinAnsiEncoding (cp1252)  → covers Helvetica / Times / Courier families
   - ZapfDingbats              → uses the standard PDF Appendix D mapping
   - MacRomanEncoding          → uses Python's mac_roman codec
   - Fallback for bare Type1   → assumes WinAnsiEncoding (safe default)
4. Shared font objects (same indirect-reference target across multiple pages)
   are patched exactly once.
5. Writes the fixed PDF to ``output_path``.

Usage
-----
    from font_encoding_fixer import inject_tounicode

    inject_tounicode(
        input_path="remediated.pdf",
        output_path="remediated_fixed.pdf",
    )

Integration with the pipeline
------------------------------
Call this function as the final post-processing step, after PDFix has
finished and after the DisplayDocTitle pypdf patch has been applied:

    # accessibility_remediation_pipeline.py  (excerpt)
    _patch_display_doc_title(tmp_path, tmp_path)   # existing step
    inject_tounicode(tmp_path, output_path)         # new step
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ZapfDingbats → Unicode  (PDF spec Appendix D.5)
# ---------------------------------------------------------------------------
_ZAPF_MAP: Dict[int, int] = {
    0x20: 0x0020, 0x21: 0x2701, 0x22: 0x2702, 0x23: 0x2703, 0x24: 0x2704,
    0x25: 0x260E, 0x26: 0x2706, 0x27: 0x2707, 0x28: 0x2708, 0x29: 0x2709,
    0x2A: 0x261B, 0x2B: 0x261E, 0x2C: 0x270C, 0x2D: 0x270D, 0x2E: 0x270E,
    0x2F: 0x270F, 0x30: 0x2710, 0x31: 0x2711, 0x32: 0x2712, 0x33: 0x2713,
    0x34: 0x2714, 0x35: 0x2715, 0x36: 0x2716, 0x37: 0x2717, 0x38: 0x2718,
    0x39: 0x2719, 0x3A: 0x271A, 0x3B: 0x271B, 0x3C: 0x271C, 0x3D: 0x271D,
    0x3E: 0x271E, 0x3F: 0x271F, 0x40: 0x2720, 0x41: 0x2721, 0x42: 0x2722,
    0x43: 0x2723, 0x44: 0x2724, 0x45: 0x2725, 0x46: 0x2726, 0x47: 0x2727,
    0x48: 0x2605, 0x49: 0x2729, 0x4A: 0x272A, 0x4B: 0x272B, 0x4C: 0x272C,
    0x4D: 0x272D, 0x4E: 0x272E, 0x4F: 0x272F, 0x50: 0x2730, 0x51: 0x2731,
    0x52: 0x2732, 0x53: 0x2733, 0x54: 0x2734, 0x55: 0x2735, 0x56: 0x2736,
    0x57: 0x2737, 0x58: 0x2738, 0x59: 0x2739, 0x5A: 0x273A, 0x5B: 0x273B,
    0x5C: 0x273C, 0x5D: 0x273D, 0x5E: 0x273E, 0x5F: 0x273F, 0x60: 0x2740,
    0x61: 0x2741, 0x62: 0x2742, 0x63: 0x2743, 0x64: 0x2744, 0x65: 0x2745,
    0x66: 0x2746, 0x67: 0x2747, 0x68: 0x2748, 0x69: 0x2749, 0x6A: 0x274A,
    0x6B: 0x274B, 0x6C: 0x25CF, 0x6D: 0x274D, 0x6E: 0x25A0, 0x6F: 0x274F,
    0x70: 0x2750, 0x71: 0x2751, 0x72: 0x2752, 0x73: 0x25B2, 0x74: 0x25BC,
    0x75: 0x25C6, 0x76: 0x2756, 0x77: 0x25D7, 0x78: 0x2758, 0x79: 0x2759,
    0x7A: 0x275A, 0x7B: 0x275B, 0x7C: 0x275C, 0x7D: 0x275D, 0x7E: 0x275E,
    0x80: 0x2768, 0x81: 0x2769, 0x82: 0x276A, 0x83: 0x276B, 0x84: 0x276C,
    0x85: 0x276D, 0x86: 0x276E, 0x87: 0x276F, 0x88: 0x2770, 0x89: 0x2771,
    0x8A: 0x2772, 0x8B: 0x2773, 0x8C: 0x2774, 0x8D: 0x2775,
    0xA1: 0x2761, 0xA2: 0x2762, 0xA3: 0x2763, 0xA4: 0x2764, 0xA5: 0x2765,
    0xA6: 0x2766, 0xA7: 0x2767, 0xA8: 0x2663, 0xA9: 0x2666, 0xAA: 0x2665,
    0xAB: 0x2660, 0xAC: 0x2460, 0xAD: 0x2461, 0xAE: 0x2462, 0xAF: 0x2463,
    0xB0: 0x2464, 0xB1: 0x2465, 0xB2: 0x2466, 0xB3: 0x2467, 0xB4: 0x2468,
    0xB5: 0x2469, 0xB6: 0x2776, 0xB7: 0x2777, 0xB8: 0x2778, 0xB9: 0x2779,
    0xBA: 0x277A, 0xBB: 0x277B, 0xBC: 0x277C, 0xBD: 0x277D, 0xBE: 0x277E,
    0xBF: 0x277F, 0xC0: 0x2780, 0xC1: 0x2781, 0xC2: 0x2782, 0xC3: 0x2783,
    0xC4: 0x2784, 0xC5: 0x2785, 0xC6: 0x2786, 0xC7: 0x2787, 0xC8: 0x2788,
    0xC9: 0x2789, 0xCA: 0x278A, 0xCB: 0x278B, 0xCC: 0x278C, 0xCD: 0x278D,
    0xCE: 0x278E, 0xCF: 0x278F, 0xD0: 0x2790, 0xD1: 0x2791, 0xD2: 0x2792,
    0xD3: 0x2793, 0xD4: 0x2794, 0xD5: 0x2795, 0xD6: 0x2796, 0xD7: 0x2797,
    0xD8: 0x2798, 0xD9: 0x2799, 0xDA: 0x279A, 0xDB: 0x279B, 0xDC: 0x279C,
    0xDD: 0x279D, 0xDE: 0x279E, 0xDF: 0x279F, 0xE0: 0x27A0, 0xE1: 0x27A1,
    0xE2: 0x27A2, 0xE3: 0x27A3, 0xE4: 0x27A4, 0xE5: 0x27A5, 0xE6: 0x27A6,
    0xE7: 0x27A7, 0xE8: 0x27A8, 0xE9: 0x27A9, 0xEA: 0x27AA, 0xEB: 0x27AB,
    0xEC: 0x27AC, 0xED: 0x27AD, 0xEE: 0x27AE, 0xEF: 0x27AF,
    0xF1: 0x27B1, 0xF2: 0x27B2, 0xF3: 0x27B3, 0xF4: 0x27B4, 0xF5: 0x27B5,
    0xF6: 0x27B6, 0xF7: 0x27B7, 0xF8: 0x27B8, 0xF9: 0x27B9, 0xFA: 0x27BA,
    0xFB: 0x27BB, 0xFC: 0x27BC, 0xFD: 0x27BD, 0xFE: 0x27BE,
}


# ---------------------------------------------------------------------------
# CMap builders
# ---------------------------------------------------------------------------

def _codec_map(codec: str) -> Dict[int, int]:
    """Build a byte→Unicode mapping for a Python codec (e.g. 'cp1252')."""
    m: Dict[int, int] = {}
    for b in range(0x20, 0x100):
        try:
            ch = bytes([b]).decode(codec)
            m[b] = ord(ch)
        except (UnicodeDecodeError, ValueError):
            pass
    return m


# Pre-built maps (computed once at import time)
_WINANSI_MAP:   Dict[int, int] = _codec_map("cp1252")
_MACROMAN_MAP:  Dict[int, int] = _codec_map("mac_roman")


def _build_cmap_stream(cmap_name: str, mapping: Dict[int, int]) -> bytes:
    """
    Serialize a {byte_code: unicode_codepoint} mapping as a PDF ToUnicode CMap.

    PDF spec limits each bfchar block to 100 entries; we chunk accordingly.
    """
    items = sorted(mapping.items())
    if not items:
        raise ValueError("CMap mapping must not be empty")

    lo = items[0][0]
    hi = items[-1][0]

    lines: list[str] = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo",
        "<< /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        f"/CMapName /{cmap_name} def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        f"<{lo:02X}> <{hi:02X}>",
        "endcodespacerange",
    ]

    chunk_size = 100
    for i in range(0, len(items), chunk_size):
        block = items[i : i + chunk_size]
        lines.append(f"{len(block)} beginbfchar")
        for code, ucp in block:
            lines.append(f"<{code:02X}> <{ucp:04X}>")
        lines.append("endbfchar")

    lines += [
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ]
    return "\n".join(lines).encode("latin-1")


# ---------------------------------------------------------------------------
# Encoding detector
# ---------------------------------------------------------------------------

def _select_cmap(font_dict) -> tuple[str, bytes] | None:
    """
    Return (cmap_name, cmap_bytes) for the given font dictionary, or None
    if the font type is not one we know how to handle.
    """
    base  = str(font_dict.get("/BaseFont", ""))
    enc   = str(font_dict.get("/Encoding", ""))
    stype = str(font_dict.get("/Subtype", ""))

    # ZapfDingbats has its own standard encoding
    if "ZapfDingbats" in base or "Dingbat" in base:
        return "ZapfDingbats-UCS", _build_cmap_stream("ZapfDingbats-UCS", _ZAPF_MAP)

    if "MacRoman" in enc:
        return "MacRoman-UCS", _build_cmap_stream("MacRoman-UCS", _MACROMAN_MAP)

    # WinAnsiEncoding, or any bare Type1 (WinAnsi is the safe default)
    if "WinAnsi" in enc or stype == "/Type1":
        return "WinAnsi-UCS", _build_cmap_stream("WinAnsi-UCS", _WINANSI_MAP)

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inject_tounicode(input_path: str | Path, output_path: str | Path, force_replace: bool = True) -> dict:
    """
    Clone ``input_path``, inject /ToUnicode CMap entries into every font that
    lacks one, and write the result to ``output_path``.
    """
    input_path  = Path(input_path)
    output_path = Path(output_path)

    print(f"[font_encoding_fixer] inject_tounicode CALLED")
    print(f"[font_encoding_fixer]   input  = {input_path}  (exists={input_path.exists()}, size={input_path.stat().st_size if input_path.exists() else 'N/A'})")
    print(f"[font_encoding_fixer]   output = {output_path}")

    try:
        writer = PdfWriter(clone_from=str(input_path))
        print(f"[font_encoding_fixer] PDF cloned — pages={len(writer.pages)}")
    except Exception as e:
        print(f"[font_encoding_fixer] ERROR cloning PDF: {e}")
        raise

    patched:  int = 0
    skipped:  int = 0
    unknown:  int = 0
    details: list[str] = []
    _seen: set[int] = set()

    for page_num, page in enumerate(writer.pages):
        resources = page.get("/Resources")
        if resources is None:
            print(f"[font_encoding_fixer]   page {page_num}: no /Resources")
            continue
        resources = resources.get_object()

        font_dict = resources.get("/Font")
        if font_dict is None:
            print(f"[font_encoding_fixer]   page {page_num}: no /Font in resources")
            continue
        font_dict = font_dict.get_object()

        print(f"[font_encoding_fixer]   page {page_num}: fonts = {list(font_dict.keys())}")

        for font_name, font_ref in font_dict.items():
            font = font_ref.get_object()
            obj_key = id(font)

            if obj_key in _seen:
                print(f"[font_encoding_fixer]     {font_name}: already seen (shared object) — skip")
                continue
            _seen.add(obj_key)

            base  = str(font.get("/BaseFont", "?"))
            enc   = str(font.get("/Encoding", "?"))
            stype = str(font.get("/Subtype", "?"))
            has_tu = "/ToUnicode" in font

            print(f"[font_encoding_fixer]     {font_name}: BaseFont={base} Encoding={enc} Subtype={stype} HasToUnicode={has_tu}")

            if has_tu and not force_replace:
                print(f"[font_encoding_fixer]     {font_name}: HasToUnicode=True, skipping")
                skipped += 1
                continue
            if has_tu and force_replace:
                # PDFix adds broken ToUnicode — check if we have a good replacement
                result = _select_cmap(font)
                if result is None:
                    print(f"[font_encoding_fixer]     {font_name}: HasToUnicode=True, no replacement known — keeping existing")
                    skipped += 1
                    continue
                print(f"[font_encoding_fixer]     {font_name}: HasToUnicode=True — REPLACING with known-good CMap")
            else:
                result = _select_cmap(font)
            if result is None:
                print(f"[font_encoding_fixer]     {font_name}: _select_cmap returned None — UNKNOWN encoding, cannot patch")
                unknown += 1
                continue

            cmap_name, cmap_bytes = result
            stream = DecodedStreamObject()
            stream.set_data(cmap_bytes)
            ref = writer._add_object(stream)
            font[NameObject("/ToUnicode")] = ref

            msg = f"Injected {cmap_name} into {font_name} ({base})"
            details.append(msg)
            logger.info("font_encoding_fixer: %s", msg)
            print(f"[font_encoding_fixer]     PATCHED: {msg}")
            patched += 1

    print(f"[font_encoding_fixer] Summary: patched={patched} skipped={skipped} unknown={unknown}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as fh:
        writer.write(fh)

    out_size = output_path.stat().st_size if output_path.exists() else "N/A"
    print(f"[font_encoding_fixer] Written to {output_path} (size={out_size})")

    logger.info(
        "font_encoding_fixer: done — patched=%d skipped=%d unknown=%d → %s",
        patched, skipped, unknown, output_path,
    )
    return {
        "fonts_patched": patched,
        "fonts_skipped": skipped,
        "fonts_unknown": unknown,
        "details": details,
    }

def inject_into_writer(writer: PdfWriter) -> dict:
    """
    Same logic as inject_tounicode() but operates on an already-open PdfWriter.
    Use this when the caller already holds a writer to avoid a second read-write pass.
    """
    patched = 0; skipped = 0; unknown = 0; details = []
    _seen: set[int] = set()

    for page in writer.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        resources = resources.get_object()
        font_dict = resources.get("/Font")
        if font_dict is None:
            continue
        font_dict = font_dict.get_object()

        for font_name, font_ref in font_dict.items():
            font = font_ref.get_object()
            obj_key = id(font)
            if obj_key in _seen:
                continue
            _seen.add(obj_key)
            if "/ToUnicode" in font:
                skipped += 1
                continue
            result = _select_cmap(font)
            if result is None:
                unknown += 1
                continue
            cmap_name, cmap_bytes = result
            stream = DecodedStreamObject()
            stream.set_data(cmap_bytes)
            font[NameObject("/ToUnicode")] = writer._add_object(stream)
            details.append(f"Injected {cmap_name} into {font_name}")
            patched += 1

    return {"fonts_patched": patched, "fonts_skipped": skipped,
            "fonts_unknown": unknown, "details": details}


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) != 3:
        print("Usage: python font_encoding_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    force = "--no-force" not in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    result = inject_tounicode(args[0], args[1], force_replace=force)
    print(json.dumps(result, indent=2))
