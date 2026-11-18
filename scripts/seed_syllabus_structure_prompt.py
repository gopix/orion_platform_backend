"""Seed / update the ``syllabus_structure`` prompt.

Reads a syllabus into a unit -> chapter hierarchy. Its guidance answers "what
counts as a chapter for this book type?" and, once seeded, is editable through the
API: PUT /prompts/book-types/{category_id}?template=syllabus_structure

The scaffold and default guidance live in
``src/modules/book_forge/services/prompt_families.py`` so the API composes from the
same definition this script writes.

Run from the repo root:

    venv\\Scripts\\python scripts\\seed_syllabus_structure_prompt.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._seed_prompt_family import seed

if __name__ == "__main__":
    seed("syllabus_structure")
