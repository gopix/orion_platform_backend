"""
run_heading_parent_fix.py
-------------------------
Subprocess entry point: detect and fix H1-H6 elements whose parent
structure element type is invalid per PDF/UA 6.4.2.

Usage:
    python run_heading_parent_fix.py <pdf_path>

Prints a JSON object to stdout:
    {"fixed": <int>, "skipped": <int>}       -- success
    {"fixed": 0, "skipped": 0, "error": ...} -- failure

Exit 0 = success, 1 = error.
"""
import sys
import os
import json
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python run_heading_parent_fix.py <pdf_path>",
            file=sys.stderr,
        )
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"ERROR: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # Ensure the engines directory (this file's directory) is importable
    engines_dir = str(Path(__file__).resolve().parent)
    if engines_dir not in sys.path:
        sys.path.insert(0, engines_dir)

    try:
        from heading_parent_fixer import fix_invalid_heading_parents
    except ImportError as exc:
        msg = f"Could not import heading_parent_fixer: {exc}"
        print(f"ERROR: {msg}", file=sys.stderr)
        print(json.dumps({"fixed": 0, "skipped": 0, "error": msg}))
        sys.exit(1)

    try:
        result = fix_invalid_heading_parents(pdf_path)
        print(json.dumps(result))
        sys.exit(0)
    except Exception as exc:
        msg = str(exc)
        print(f"ERROR: {msg}", file=sys.stderr)
        print(json.dumps({"fixed": 0, "skipped": 0, "error": msg}))
        sys.exit(1)


if __name__ == "__main__":
    main()
