"""
run_fix_alt_text.py  — subprocess wrapper for alt_text_fixer.fix_alt_text

Usage:
    python run_fix_alt_text.py <input.pdf> <output.pdf>

Environment:
    orion-claude-key   Claude API key for vision inference
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from alt_text_fixer import fix_alt_text

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: run_fix_alt_text.py <input.pdf> <output.pdf>", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("orion-claude-key", "")
    result = fix_alt_text(sys.argv[1], sys.argv[2], api_key=api_key)
    print(json.dumps(result))
