"""Seed / update the ``chapter_content`` prompt.

Writes each chapter's prose for a blueprint. It does NOT choose chapters: the
chapter list arrives already extracted from the syllabus and signed off by an SME
through the audit sheet.

Its guidance answers "how deep, what tone, what style of objective?" and, once
seeded, is editable through the API (this is the default template there):
PUT /prompts/book-types/{category_id}

The scaffold and default guidance live in
``src/modules/book_forge/services/prompt_families.py`` so the API composes from the
same definition this script writes.

Run from the repo root:

    venv\\Scripts\\python scripts\\seed_chapter_content_prompt.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._seed_prompt_family import seed

if __name__ == "__main__":
    seed("chapter_content")
