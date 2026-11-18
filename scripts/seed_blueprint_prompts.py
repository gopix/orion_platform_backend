"""Seed the Prompt Engine with the blueprint prompt templates.

Creates two versioned, active templates used by the blueprint workflow:

  1. ``blueprint_query``      — rendered (no LLM) to produce the RETRIEVAL query
                                that gets embedded and searched against Pinecone.
  2. ``blueprint_generation`` — rendered then sent to the LLM (via guardrails) to
                                produce the structured blueprint JSON.

Idempotent: if a template with the same name already exists, it is skipped.
Run once (after creating the book_forge_prompt_* tables) from the repo root:

    python scripts/seed_blueprint_prompts.py

Change GENERATION_MODEL below to whatever model your Anthropic key supports if
you want a stronger model than Haiku for generation.
"""
import sys
from pathlib import Path

# Make the repo root importable when run as `python scripts/seed_blueprint_prompts.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.database import SessionLocal
from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptStatus,
    PromptTemplate,
    PromptVariable,
    PromptVersion,
    VariableType,
    VersionStatus,
)
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository

# Any "claude*" model routes to Anthropic (see llm/utils/model_mapping.py).
GENERATION_MODEL = "claude-haiku-4-5-20251001"
QUERY_MODEL = "claude-haiku-4-5-20251001"  # unused for rendering, set for record

# --- Template 1: the retrieval query (rendered only, never sent to an LLM) ----
BLUEPRINT_QUERY_TEXT = """\
Create a comprehensive blueprint for the book.
Title: {{ book_title }}
Subject: {{ book_subject }}
Target Audience: {{ target_audience }}
Description: {{ book_description }}
Expected Chapters: {{ chapter_count }}"""

# --- Template 2: the RAG generation prompt (rendered, then LLM via guardrails) -
BLUEPRINT_GENERATION_TEXT = """\
You are an expert book architect. Using ONLY the source material provided below,
design a chapter-by-chapter blueprint for the following book.

BOOK REQUIREMENTS
Title: {{ book_title }}
Subject: {{ book_subject }}
Target Audience: {{ target_audience }}
Description: {{ book_description }}
Desired number of chapters: {{ chapter_count }}

SOURCE MATERIAL (retrieved from the project's knowledge base)
{{ retrieved_context }}

INSTRUCTIONS
- Base the blueprint strictly on the source material above; do not invent topics
  that the source material does not support.
- Produce approximately {{ chapter_count }} chapters, ordered logically for the
  target audience, progressing from foundational to advanced.
- Each chapter's "covered_topics" must reference the specific source topics/units
  it maps to.
- Return ONLY valid JSON (no markdown, no prose) matching EXACTLY this shape:
{
  "title": "string",
  "description": "string",
  "target_audience": "string",
  "estimated_length": 0,
  "chapters": [
    {
      "chapter_number": 1,
      "title": "string",
      "summary": "string",
      "learning_objectives": ["string"],
      "covered_topics": ["string"]
    }
  ]
}"""

# Variables shared by both templates (query uses the first five).
_COMMON_VARS = [
    PromptVariable(name="book_title", type=VariableType.STRING, required=True),
    PromptVariable(name="book_subject", type=VariableType.STRING, required=False),
    PromptVariable(name="target_audience", type=VariableType.STRING, required=False),
    PromptVariable(name="book_description", type=VariableType.STRING, required=False),
    PromptVariable(name="chapter_count", type=VariableType.INTEGER, required=False),
]


def _seed_template(repo, *, name, category, description, template_text, model, variables):
    """Create template + v1 + variables and activate v1. Skips if name exists."""
    if repo.get_template_by_name(name) is not None:
        print(f"• '{name}' already exists — skipping.")
        return

    template = repo.create_template(
        PromptTemplate(
            name=name,
            category=category,
            description=description,
            status=PromptStatus.ACTIVE,
        )
    )
    repo.create_version(
        PromptVersion(
            template_id=template.id,
            version=1,
            template_text=template_text,
            model=model,
            temperature=0.3,
            max_tokens=4000,
            status=VersionStatus.DRAFT,
        )
    )
    repo.create_variables(template.id, variables)
    repo.activate_version(template.id, 1)
    print(f"✓ Seeded '{name}' (template_id={template.id}, version 1 active).")


def main() -> None:
    db = SessionLocal()
    try:
        repo = PromptRepository(db)

        _seed_template(
            repo,
            name="blueprint_query",
            category="blueprint",
            description="Retrieval query for book-blueprint RAG (rendered, embedded).",
            template_text=BLUEPRINT_QUERY_TEXT,
            model=QUERY_MODEL,
            variables=list(_COMMON_VARS),
        )

        _seed_template(
            repo,
            name="blueprint_generation",
            category="blueprint",
            description="RAG generation prompt producing the structured blueprint JSON.",
            template_text=BLUEPRINT_GENERATION_TEXT,
            model=GENERATION_MODEL,
            variables=list(_COMMON_VARS)
            + [
                PromptVariable(
                    name="retrieved_context",
                    type=VariableType.STRING,
                    required=True,
                    description="Concatenated retrieved chunks from the vector store.",
                )
            ],
        )

        print("\nDone. Blueprint prompt templates are seeded and active.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
