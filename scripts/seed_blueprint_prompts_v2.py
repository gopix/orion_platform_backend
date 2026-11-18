"""Seed / update the ``blueprint_generation`` prompt (author-ready + calibrated).

This prompt enriches each chapter with author-development detail (key concepts,
difficulty, focus areas, and a per-chapter assessment plan whose question counts
are scaled by exam weightage), AND calibrates depth / difficulty / question mix to
the project's ``target_audience`` (the "standard" — e.g. class-8, class-10,
graduate).

Upsert-by-content: if the active version already matches this text, it does
nothing; otherwise it creates the NEXT version with this text and activates it
(the Prompt Engine archives the previous one, so you keep history + rollback).

Run from the repo root:

    venv\\Scripts\\python scripts\\seed_blueprint_prompts_v2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.database import SessionLocal
from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptVariable,
    PromptVersion,
    VariableType,
    VersionStatus,
)
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository

TEMPLATE_NAME = "blueprint_generation"
GENERATION_MODEL = "gpt-4o-mini"  # match a provider/model you have funded

BLUEPRINT_GENERATION = """\
You are an expert book architect and assessment designer. Using ONLY the source
material provided below, design a detailed, author-ready chapter blueprint for the
following book.

BOOK REQUIREMENTS
Title: {{ book_title }}
Subject: {{ book_subject }}
Target Audience / Standard: {{ target_audience }}
Description: {{ book_description }}
Desired number of chapters: {{ chapter_count }}
Target questions per chapter (average): {{ questions_per_chapter }}

SOURCE MATERIAL (retrieved from the project's knowledge base)
{{ retrieved_context }}

CALIBRATE TO THE STANDARD
- The target audience "{{ target_audience }}" is the STANDARD. Calibrate depth,
  vocabulary, difficulty, and the question mix to it:
  - Lower standards (e.g. class 8-10): simpler explanations, more easy questions and
    fill-in-the-blanks; few or no advanced numericals or competitive previous-year
    questions.
  - Higher standards (e.g. class 12 / competitive / graduate): more hard questions,
    numericals, assertion-reason, multiple-correct, and previous-year questions.
- Every chapter's "by_difficulty" split and "by_type" emphasis MUST reflect this
  standard.

INSTRUCTIONS
- Base the blueprint strictly on the source material; do NOT invent topics it does
  not support. {{ chapter_count }} is the MAXIMUM number of chapters, not a target:
  produce only as many chapters as the syllabus genuinely justifies (roughly one per
  distinct syllabus unit/topic), which may be FEWER than {{ chapter_count }}. Never
  invent, split, or pad topics merely to reach {{ chapter_count }}; the chapter
  count must be justified by the syllabus.
- For each chapter, give author-ready detail: the key concepts to explain, the
  difficulty level, and focus areas where learners commonly struggle (use the SME
  interview / source guidance where available).
- WEIGHTAGE: assign each chapter a "weight" from 1 (light) to 5 (heavy) that its
  assessment scales from. Decide the weight using the FIRST applicable signal, in
  this priority order:
    1. SME EMPHASIS (authoritative): if an SME emphasis note is given below, follow
       it - emphasized topics/chapters get higher weight, de-emphasized ones lower.
    2. PREVIOUS-YEAR QUESTIONS (PYQ): if the source contains PYQ, derive the weight
       from how often each chapter's topics recur across the years.
    3. EXPLICIT WEIGHTAGE/MARKS TABLE: if the source has one, scale by it.
    4. EVEN: if none of the above are available (e.g. a school syllabus with no PYQ
       and no SME input), give every chapter an equal weight.
  If BOTH SME emphasis and PYQ are present, use both, with SME emphasis taking
  precedence. Then set each chapter's TOTAL number of questions in PROPORTION to its
  weight - as a guide, total_questions is approximately
  {{ questions_per_chapter }} * weight / 3 (so a weight-5 chapter has roughly 2.5x
  the questions of a weight-2 chapter). {{ questions_per_chapter }} is only the
  AVERAGE across chapters, NOT a per-chapter target: individual totals MUST differ
  with weight - it is WRONG to give every chapter the same total (unless rule 4
  EVEN applies). The six by_type counts MUST sum to each chapter's total_questions.

SME EMPHASIS: {{ sme_emphasis }}
- "by_type" MUST use exactly these keys: mcq_single_correct, multiple_correct,
  numerical_value, assertion_reason, fill_in_the_blanks, previous_year_questions.
- "by_difficulty" MUST use exactly these keys: easy, medium, hard.
- "total_questions" MUST equal the sum of the by_type counts.
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
      "covered_topics": ["string"],
      "learning_objectives": ["string"],
      "key_concepts": ["string"],
      "difficulty_level": "foundational | intermediate | advanced",
      "weight": 3,
      "focus_areas": ["string"],
      "assessment_plan": {
        "by_type": {
          "mcq_single_correct": 0,
          "multiple_correct": 0,
          "numerical_value": 0,
          "assertion_reason": 0,
          "fill_in_the_blanks": 0,
          "previous_year_questions": 0
        },
        "by_difficulty": { "easy": 0, "medium": 0, "hard": 0 },
        "total_questions": 0
      }
    }
  ]
}"""


def main() -> None:
    db = SessionLocal()
    try:
        repo = PromptRepository(db)

        template = repo.get_template_by_name(TEMPLATE_NAME)
        if template is None:
            print(
                f"Template '{TEMPLATE_NAME}' not found. Run seed_blueprint_prompts.py "
                "first to create the base template (v1)."
            )
            return

        # Ensure the questions_per_chapter variable is declared (template-scoped).
        existing_vars = {v.name for v in repo.get_variables(template.id)}
        if "questions_per_chapter" not in existing_vars:
            repo.create_variables(
                template.id,
                [
                    PromptVariable(
                        name="questions_per_chapter",
                        type=VariableType.INTEGER,
                        required=False,
                        description="Average question budget per chapter.",
                    )
                ],
            )
            print("• Declared new variable 'questions_per_chapter'.")

        # Upsert-by-content: no-op if the active version already matches.
        active = repo.get_active_version(template.id)
        if active and (active.template_text or "").strip() == BLUEPRINT_GENERATION.strip():
            print("Active generation prompt already up to date — nothing to do.")
            return

        versions = repo.get_versions(template.id)
        next_version = max((v.version for v in versions), default=1) + 1
        repo.create_version(
            PromptVersion(
                template_id=template.id,
                version=next_version,
                template_text=BLUEPRINT_GENERATION,
                model=GENERATION_MODEL,
                temperature=0.3,
                max_tokens=8000,
                status=VersionStatus.DRAFT,
            )
        )
        repo.activate_version(template.id, next_version)
        print(
            f"✓ Seeded and activated blueprint_generation v{next_version} "
            "(author-ready + standard-calibrated)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
