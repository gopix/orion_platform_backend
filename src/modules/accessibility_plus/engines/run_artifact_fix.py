"""
run_artifact_fix.py
-------------------
Standalone subprocess entry point: apply artifact fixes to a PDF.

Usage:
    python run_artifact_fix.py <pdf_path>

Exit 0 = success, 1 = error.
"""
import sys
import os
import json
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_artifact_fix.py <pdf_path>", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"ERROR: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))

    try:
        from artifact_fixer import fix_artifact_issues
    except ImportError as e:
        print(f"ERROR: could not import artifact_fixer: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = fix_artifact_issues(pdf_path)
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
