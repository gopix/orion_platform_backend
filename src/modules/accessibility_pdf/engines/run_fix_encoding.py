#!/usr/bin/env python3
"""
run_fix_encoding.py
-------------------
Standalone helper: inject /ToUnicode CMap into a PDF.
Called as a subprocess from the download endpoint.

Usage:
    python run_fix_encoding.py <input.pdf> <output.pdf>
"""
import sys
from pathlib import Path

# Add this directory to path so font_encoding_fixer imports cleanly
sys.path.insert(0, str(Path(__file__).parent))

from font_encoding_fixer import inject_tounicode

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: run_fix_encoding.py <input.pdf> <output.pdf>", file=sys.stderr)
        sys.exit(1)

    result = inject_tounicode(sys.argv[1], sys.argv[2])
    print(f"OK patched={result['fonts_patched']} skipped={result['fonts_skipped']} unknown={result['fonts_unknown']}")
