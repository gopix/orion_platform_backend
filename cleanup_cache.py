"""
Complete cache cleanup and restart script for Windows
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

print("=" * 80)
print("AGGRESSIVE CACHE CLEANUP FOR PYTHON & FASTAPI")
print("=" * 80)

# Find and remove all __pycache__ directories
print("\n1. Removing all __pycache__ directories...")
for root, dirs, files in os.walk("."):
    if "__pycache__" in dirs:
        pycache_path = os.path.join(root, "__pycache__")
        print(f"   Removing: {pycache_path}")
        shutil.rmtree(pycache_path, ignore_errors=True)

# Find and remove all .pyc files
print("\n2. Removing all .pyc files...")
for root, dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".pyc"):
            pyc_path = os.path.join(root, file)
            print(f"   Removing: {pyc_path}")
            os.remove(pyc_path)

# Remove .pytest_cache if exists
print("\n3. Removing .pytest_cache...")
if os.path.exists(".pytest_cache"):
    shutil.rmtree(".pytest_cache", ignore_errors=True)
    print("   Removed .pytest_cache")

print("\n" + "=" * 80)
print("CACHE CLEANUP COMPLETE!")
print("=" * 80)
print("\nNow restart your FastAPI server:")
print("  1. Stop current server (Ctrl+C)")
print("  2. Run: python main.py")
print("     OR: uvicorn main:app --reload")
print("=" * 80)
