#!/usr/bin/env python3
"""
Run this from C:\Orion\codebase\orion_backend\ to verify and fix the deployment.
Usage:  python verify_and_fix.py
"""
import sys, os, importlib, importlib.util, shutil
from pathlib import Path

ROOT = Path(__file__).parent
print(f"Project root: {ROOT}")
print(f"Python:       {sys.executable}")
print()

# ── 1. Check the .py files have the correct code ───────────────────────────
files = {
    "remediator":  ROOT / "src/modules/accessibility_plus/engines/remediator/document__remediator_agent.py",
    "pipeline":    ROOT / "src/modules/accessibility_plus/engines/accessibility_remediation_pipeline.py",
    "validator":   ROOT / "src/modules/accessibility_plus/engines/validator/document_accessibility_agent.py",
}

print("=== Checking .py source files ===")
ok = True
for name, path in files.items():
    if not path.exists():
        print(f"  MISSING: {path}")
        ok = False
        continue
    src = path.read_text(encoding="utf-8", errors="replace")
    checks = {
        "remediator": ("schedule_pdfua_fix", "_pdfua_fix_scheduled"),
        "pipeline":   ("DOC_PDFUA_DECLARATION", "_pdfua_fix_scheduled"),
        "validator":  ("Method 2", "pdfuaid:part"),
    }
    for term in checks[name]:
        found = term in src
        status = "OK " if found else "MISSING"
        if not found:
            ok = False
        print(f"  [{status}] {name}: '{term}'")

print()

# ── 2. Delete ALL __pycache__ under src/ ───────────────────────────────────
print("=== Clearing __pycache__ ===")
deleted = 0
for cache_dir in (ROOT / "src").rglob("__pycache__"):
    try:
        shutil.rmtree(cache_dir)
        print(f"  Deleted: {cache_dir}")
        deleted += 1
    except Exception as e:
        print(f"  FAILED to delete {cache_dir}: {e}")
if deleted == 0:
    print("  (no __pycache__ found — already clean)")
print()

# ── 3. Force-import the remediator and test _fix_pdfua ─────────────────────
print("=== Testing _fix_pdfua in remediator ===")

# Add project root to sys.path so imports work
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Remove any cached version
mod_key = "src.modules.accessibility_plus.engines.remediator.document__remediator_agent"
if mod_key in sys.modules:
    del sys.modules[mod_key]

try:
    spec = importlib.util.spec_from_file_location(mod_key, files["remediator"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    agent = mod.DocumentRemediatorAgent()

    # Mock pdf_doc that has SetMetadata but we'll see if it's even called
    class MockDoc:
        def SetMetadata(self, *a): raise RuntimeError("SetMetadata should NOT be called")
        def GetMetadata(self): return None
        def hasattr(self, n): return True

    ctx = {"pdf_doc": MockDoc()}
    result = agent._fix_pdfua("DOC_PDFUA_DECLARATION", ctx)

    print(f"  success:  {result.success}")
    print(f"  action:   {result.action}")
    print(f"  error:    {result.error}")
    print(f"  changes:  {result.changes_made}")
    print(f"  _pdfua_fix_scheduled in ctx: {ctx.get('_pdfua_fix_scheduled', False)}")

    if result.action == "schedule_pdfua_fix" and result.success and not result.error:
        print()
        print("  ✓ CORRECT: _fix_pdfua is scheduling, not calling SetMetadata")
    else:
        print()
        print("  ✗ WRONG: old code is still running")
        ok = False

except Exception as e:
    import traceback
    print(f"  ERROR importing/testing: {e}")
    traceback.print_exc()
    ok = False

print()
print("=== RESULT ===")
if ok:
    print("ALL CHECKS PASSED. Restart the server and run a fresh POST to /orion-remediate-pdf.")
else:
    print("CHECKS FAILED. Source files may still have old code.")
    print("Re-extract pdfua_final_fix_3files.zip into the project and re-run this script.")
