"""
diagnose_encoding.py
====================
Run this on the pipeline's output PDF to diagnose Character Encoding failure.

Usage:
    python diagnose_encoding.py path/to/your_remediated.pdf

It will:
1. Report every font and whether it has /ToUnicode (including fonts inside XObjects)
2. Run inject_into_writer on it and show what gets patched
3. Save a fixed copy alongside the original (_diag_fixed.pdf)
"""

import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, DecodedStreamObject, NameObject

# ── bring in the encoding maps from font_encoding_fixer ──────────────────────
# Adjust the import path if font_encoding_fixer lives in a package
try:
    from font_encoding_fixer import inject_tounicode, _select_cmap, inject_into_writer
    print("[OK] font_encoding_fixer imported successfully")
except ImportError as e:
    print(f"[FAIL] Cannot import font_encoding_fixer: {e}")
    sys.exit(1)


def find_all_fonts(obj, path="", visited=None, results=None):
    """Recursively find ALL fonts including those inside Form XObjects."""
    if visited is None: visited = set()
    if results is None: results = []
    try:
        obj = obj.get_object() if hasattr(obj, 'get_object') else obj
    except:
        return results
    obj_id = id(obj)
    if obj_id in visited: return results
    visited.add(obj_id)
    if not isinstance(obj, DictionaryObject): return results

    fonts = obj.get("/Font")
    if fonts:
        try:
            fonts = fonts.get_object()
            for fname, fref in fonts.items():
                font = fref.get_object() if hasattr(fref, 'get_object') else fref
                has_tu  = "/ToUnicode" in font
                base    = str(font.get("/BaseFont", "?"))
                enc     = str(font.get("/Encoding", "?"))
                subtype = str(font.get("/Subtype", "?"))
                results.append((path + fname, base, enc, subtype, has_tu))
        except Exception as ex:
            print(f"  [WARN] Font dict error at {path}: {ex}")

    # Recurse into XObjects (Form XObjects can embed their own fonts)
    xobj = obj.get("/XObject")
    if xobj:
        try:
            xobj = xobj.get_object()
            for k, v in xobj.items():
                find_all_fonts(v, path + f"/XObject{k}/Resources/", visited, results)
        except: pass

    res = obj.get("/Resources")
    if res and path:            # avoid re-entering already-scanned resource dict
        find_all_fonts(res, path + "/Resources/", visited, results)

    return results


def main(pdf_path: str):
    p = Path(pdf_path)
    if not p.exists():
        print(f"[FAIL] File not found: {pdf_path}")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"DIAGNOSING: {p.name}")
    print(f"{'='*70}")

    reader = PdfReader(str(p))
    print(f"Pages: {len(reader.pages)}")

    # ── 1. Audit all fonts ────────────────────────────────────────────────
    print("\n── FONT AUDIT (all pages + XObjects) ───────────────────────────────")
    all_fonts = []
    for pg_num, page in enumerate(reader.pages, 1):
        res = page.get("/Resources")
        if res:
            find_all_fonts(res, f"Page{pg_num}/Font/", set(), all_fonts)

    seen_bases = set()
    missing_tu = []
    for loc, base, enc, subtype, has_tu in all_fonts:
        key = (base, enc)
        if key in seen_bases: continue
        seen_bases.add(key)
        status = "✓ ToUnicode" if has_tu else "✗ MISSING ToUnicode"
        print(f"  {status:20s}  {base:30s}  Enc={enc}  Sub={subtype}")
        if not has_tu:
            missing_tu.append((loc, base, enc, subtype))

    print(f"\nFonts MISSING ToUnicode: {len(missing_tu)}")
    if not missing_tu:
        print("  → All fonts already have ToUnicode.")
        print("  → The Character Encoding failure is NOT a ToUnicode issue.")
        print("  → Check whether you are opening the correct output file in Acrobat.")
        return

    # ── 2. Check whether _select_cmap can handle them ────────────────────
    print("\n── CMAP SELECTION CHECK ────────────────────────────────────────────")
    for loc, base, enc, subtype in missing_tu:
        # Build a minimal font dict for _select_cmap
        from pypdf.generic import DictionaryObject, NameObject
        fd = DictionaryObject()
        if base != "?": fd[NameObject("/BaseFont")] = NameObject(base)
        if enc  != "?": fd[NameObject("/Encoding")] = NameObject(enc)
        if subtype != "?": fd[NameObject("/Subtype")] = NameObject(subtype)
        result = _select_cmap(fd)
        if result:
            print(f"  {base:30s} → will inject '{result[0]}'")
        else:
            print(f"  {base:30s} → [UNKNOWN] no CMap available — Acrobat may still flag this")

    # ── 3. Run inject_tounicode and save fixed copy ───────────────────────
    fixed_path = p.parent / f"{p.stem}_diag_fixed{p.suffix}"
    print(f"\n── APPLYING inject_tounicode → {fixed_path.name} ──────────────────")
    result = inject_tounicode(str(p), str(fixed_path))
    print(f"  fonts_patched : {result['fonts_patched']}")
    print(f"  fonts_skipped : {result['fonts_skipped']}")
    print(f"  fonts_unknown : {result['fonts_unknown']}")
    for d in result['details']:
        print(f"    {d}")

    # ── 4. Verify fixed copy ──────────────────────────────────────────────
    print(f"\n── VERIFYING {fixed_path.name} ──────────────────────────────────────")
    r2 = PdfReader(str(fixed_path))
    still_missing = []
    for pg_num, page in enumerate(r2.pages, 1):
        res = page.get("/Resources")
        if res:
            out = []
            find_all_fonts(res, f"Page{pg_num}/Font/", set(), out)
            for loc, base, enc, subtype, has_tu in out:
                if not has_tu:
                    still_missing.append(base)

    if still_missing:
        print(f"  [FAIL] Still missing ToUnicode after fix: {set(still_missing)}")
    else:
        print("  [OK] All fonts now have ToUnicode in the fixed file.")
        print(f"\n  Open '{fixed_path.name}' in Acrobat to verify the check passes.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_encoding.py <path_to_remediated.pdf>")
        sys.exit(1)
    main(sys.argv[1])
