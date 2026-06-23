"""
run_link_fix.py
---------------
Standalone script: apply missing <Link> annotation + structure fix to a PDF.

Usage:
    python run_link_fix.py <pdf_path>

Can also be called from the pipeline as a subprocess.
Exit code 0 = success, 1 = error.
"""
import sys
import os
import json
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_link_fix.py <pdf_path>", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"ERROR: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # Add the script's directory to path so link_fixer.py is found
    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))

    try:
        from link_fixer import fix_missing_link_tags
    except ImportError as e:
        print(f"ERROR: could not import link_fixer: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = fix_missing_link_tags(pdf_path)
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
