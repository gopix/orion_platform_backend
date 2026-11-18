#!/usr/bin/env python3
"""Rename the PDF accessibility package and rewrite every reference.

Usage:  python migrate_rename.py [--apply]
Default is a DRY RUN (prints what would change). Add --apply to make changes.
"""
import os, sys, re, io

# ---- configure here --------------------------------------------------------
REPO_ROOT   = "."                       # run from repo root (orion_backend)
OLD_PKG     = "accessibility_PDF"
NEW_PKG     = "accessibility_pdf"       # <- change to "accessibility_pdf" if you want lowercase
OLD_DIR     = os.path.join("src", "modules", OLD_PKG)
NEW_DIR     = os.path.join("src", "modules", NEW_PKG)

# files we rewrite text in (code + config + docs). logs/venv/pycache excluded.
TEXT_EXT    = {".py", ".md", ".json", ".toml", ".ini", ".cfg", ".txt", ".yaml", ".yml"}
SKIP_EXT    = {".log"}
SKIP_DIRS   = {"__pycache__", ".git", ".venv", "venv", "env", "node_modules", "site-packages", "temp"}
# ---------------------------------------------------------------------------

APPLY = "--apply" in sys.argv

def iter_files(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT: continue
            if ext not in TEXT_EXT: continue
            yield os.path.join(dp, fn)

def main():
    root = os.path.abspath(REPO_ROOT)
    changed, total_hits = [], 0
    for path in iter_files(root):
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except (UnicodeDecodeError, PermissionError):
            continue
        n = src.count(OLD_PKG)
        if not n:
            continue
        total_hits += n
        changed.append((path, n))
        if APPLY:
            with io.open(path, "w", encoding="utf-8", newline="") as f:
                f.write(src.replace(OLD_PKG, NEW_PKG))

    print(f"{'APPLIED' if APPLY else 'DRY RUN'} — rewrite '{OLD_PKG}' -> '{NEW_PKG}'")
    print(f"files touched: {len(changed)}   total occurrences: {total_hits}")
    for p, n in changed:
        print(f"  [{n:2d}] {os.path.relpath(p, root)}")

    old_abs, new_abs = os.path.join(root, OLD_DIR), os.path.join(root, NEW_DIR)
    if os.path.isdir(old_abs):
        print(f"\ndirectory rename: {OLD_DIR}  ->  {NEW_DIR}")
        if APPLY:
            os.rename(old_abs, new_abs)     # use `git mv` instead to keep history (see notes)
            print("  renamed.")
    else:
        print(f"\n[!] {OLD_DIR} not found (already renamed?)")

    if not APPLY:
        print("\nDry run only. Re-run with --apply to make changes.")

if __name__ == "__main__":
    main()
