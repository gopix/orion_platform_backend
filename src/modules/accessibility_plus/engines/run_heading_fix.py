"""
run_heading_fix.py
------------------
Subprocess entry: apply heading tag fix + add bookmarks to a PDF.

Usage:
    python run_heading_fix.py <pdf_path> [h1_min] [h2_min] [h3_min]

Defaults: h1_min=17  h2_min=13  h3_min=11.5
Exit 0 = success, 1 = error.
"""
import sys
import os
import json
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_heading_fix.py <pdf_path> [h1_min h2_min h3_min]",
              file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"ERROR: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    h1_min = float(sys.argv[2]) if len(sys.argv) > 2 else 17.0
    h2_min = float(sys.argv[3]) if len(sys.argv) > 3 else 13.0
    h3_min = float(sys.argv[4]) if len(sys.argv) > 4 else 11.5

    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))

    try:
        from heading_tagger import fix_heading_tags, add_bookmarks_from_headings
    except ImportError as e:
        print(f"ERROR: could not import heading_tagger: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        tag_result = fix_heading_tags(pdf_path, h1_min=h1_min, h2_min=h2_min, h3_min=h3_min)
        bm_result  = add_bookmarks_from_headings(pdf_path)
        result = {**tag_result, **bm_result}
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
