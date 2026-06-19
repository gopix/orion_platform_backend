"""
diagnose_fonts.py
-----------------
Run this on the Windows server to diagnose why font embedding isn't working.

Usage:
    cd C:\Orion\codebase\orion_backend
    python diagnose_fonts.py <path_to_remediated_pdf>

Example:
    python diagnose_fonts.py C:\temp\untagged_accessibility_practice_remediated.pdf
"""
import sys
import os
from pathlib import Path

print("=" * 60)
print("PDF Font Embedding Diagnostics")
print("=" * 60)

# 1. Python version
print(f"\n[1] Python: {sys.version}")
print(f"    Executable: {sys.executable}")

# 2. fontTools
print("\n[2] fontTools import test:")
try:
    from fontTools import ttLib
    import fontTools
    print(f"    OK — fontTools {fontTools.version}")
except ImportError as e:
    print(f"    FAILED: {e}")
    print("    FIX: pip install fonttools")
    sys.exit(1)

# 3. pikepdf
print("\n[3] pikepdf import test:")
try:
    import pikepdf
    print(f"    OK — pikepdf {pikepdf.__version__}")
    # Test pikepdf.Real
    r = pikepdf.Real("500")
    print(f"    pikepdf.Real works: {r}")
except ImportError as e:
    print(f"    FAILED: {e}")
    sys.exit(1)
except AttributeError as e:
    print(f"    pikepdf.Real MISSING: {e}")
    sys.exit(1)

# 4. Windows font files
print("\n[4] Windows font file check:")
FONT_MAP = {
    "/Helvetica":             r"C:\Windows\Fonts\arial.ttf",
    "/Helvetica-Bold":        r"C:\Windows\Fonts\arialbd.ttf",
    "/Helvetica-Oblique":     r"C:\Windows\Fonts\ariali.ttf",
    "/Helvetica-BoldOblique": r"C:\Windows\Fonts\arialbi.ttf",
    "/Times-Roman":           r"C:\Windows\Fonts\times.ttf",
    "/Times-Bold":            r"C:\Windows\Fonts\timesbd.ttf",
    "/Times-Italic":          r"C:\Windows\Fonts\timesi.ttf",
    "/Times-BoldItalic":      r"C:\Windows\Fonts\timesbi.ttf",
    "/Courier":               r"C:\Windows\Fonts\cour.ttf",
    "/Courier-Bold":          r"C:\Windows\Fonts\courbd.ttf",
    "/Courier-Oblique":       r"C:\Windows\Fonts\couri.ttf",
    "/Courier-BoldOblique":   r"C:\Windows\Fonts\courbi.ttf",
}
all_fonts_ok = True
for pdf_name, path in FONT_MAP.items():
    exists = Path(path).exists()
    status = "OK" if exists else "MISSING"
    if not exists:
        all_fonts_ok = False
    print(f"    {status}: {pdf_name} -> {path}")

if not all_fonts_ok:
    print("\n    WARNING: Some font files are missing!")
    print("    The engine cannot embed these fonts.")

# 5. Test embedding on PDF (if provided)
if len(sys.argv) < 2:
    print("\n[5] Skipped — no PDF path provided.")
    print("    Re-run with: python diagnose_fonts.py <pdf_path>")
else:
    pdf_path = Path(sys.argv[1])
    print(f"\n[5] Font embedding test on: {pdf_path}")
    if not pdf_path.exists():
        print(f"    FAILED: file not found: {pdf_path}")
    else:
        import shutil, tempfile
        tmp = Path(tempfile.mktemp(suffix=".pdf"))
        shutil.copy(pdf_path, tmp)

        # Check current font status
        pdf = pikepdf.open(tmp)
        seen = set()
        print("    Current fonts in PDF:")
        for page in pdf.pages:
            res = page.get("/Resources")
            if not res: continue
            fonts = res.get("/Font")
            if not fonts: continue
            for name, font_ref in fonts.items():
                font = font_ref
                base = str(font.get("/BaseFont",""))
                if base in seen: continue
                seen.add(base)
                subtype = str(font.get("/Subtype",""))
                has_desc = "/FontDescriptor" in font
                embedded = False
                if has_desc:
                    desc = font["/FontDescriptor"]
                    embedded = any(k in desc for k in ["/FontFile","/FontFile2","/FontFile3"])
                print(f"      {base} ({subtype}): Embedded={embedded}")
        pdf.close()

        # Now run embed_standard_fonts
        print("\n    Running embed_standard_fonts...")
        fixer_path = Path(__file__).parent / "src" / "modules" / "accessibility_plus" / "engines" / "font_encoding_fixer.py"
        if not fixer_path.exists():
            # Try relative path
            fixer_path = Path("src/modules/accessibility_plus/engines/font_encoding_fixer.py")

        if not fixer_path.exists():
            print(f"    FAILED: font_encoding_fixer.py not found at {fixer_path}")
        else:
            import importlib.util
            spec = importlib.util.spec_from_file_location("font_encoding_fixer", fixer_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.embed_standard_fonts(str(tmp))
            print(f"    embed_standard_fonts returned: {result}")

            # Verify
            if result:
                pdf2 = pikepdf.open(tmp)
                seen2 = set()
                print("\n    Font status AFTER embedding:")
                for page in pdf2.pages:
                    res = page.get("/Resources")
                    if not res: continue
                    fonts = res.get("/Font")
                    if not fonts: continue
                    for name, font_ref in fonts.items():
                        font = font_ref
                        base = str(font.get("/BaseFont",""))
                        if base in seen2: continue
                        seen2.add(base)
                        embedded = False
                        if "/FontDescriptor" in font:
                            desc = font["/FontDescriptor"]
                            embedded = any(k in desc for k in ["/FontFile","/FontFile2","/FontFile3"])
                        print(f"      {base}: Embedded={embedded}")
                pdf2.close()
        tmp.unlink(missing_ok=True)

print("\n" + "=" * 60)
print("Diagnostics complete.")
