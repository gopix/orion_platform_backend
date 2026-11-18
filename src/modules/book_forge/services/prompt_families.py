"""Prompt families — the single source of truth for guidance-managed prompts.

A "family" is one prompt the pipeline actually calls, whose publisher-editable
part is a plain-English guidance block wrapped in a fixed scaffold:

    scaffold_top + GUIDANCE_HEADER + guidance + GUIDANCE_FOOTER + scaffold_bottom

Both the seed scripts (which create v1) and ``blueprint_prompt_admin`` (which lets
a publisher edit guidance through the API) compose templates from the definitions
here. That matters: when the scaffold lived in two places, the API could recompose
a template with a *different* scaffold than the seed script wrote, silently
changing behaviour. One definition, one scaffold.

Adding a new guidance-managed prompt is one entry in ``FAMILIES``.

Families in use
---------------
``syllabus_structure`` — read a syllabus into a unit -> chapter tree. Guidance
    answers "what counts as a chapter for this book type?".
``chapter_content``    — write each chapter's prose. Guidance answers "how deep,
    what tone, what style of objective?".

``blueprint_generation`` is deliberately NOT here. It was the single prompt that
used to choose chapters, weight them and write prose all at once; that job is now
split across the two families above, and nothing calls it.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.modules.book_forge.ai.foundation.prompts.models import VariableType

GUIDANCE_FOOTER = "[END OF BOOK-TYPE GUIDANCE]"


@dataclass(frozen=True)
class PromptFamily:
    """Everything needed to compose, seed and edit one prompt family."""

    #: Base template name; category variants are ``<template>_<category_slug>``.
    template: str
    #: One-line description used when the template row is created.
    description: str
    #: Header line that precedes the guidance block inside the composed template.
    guidance_header: str
    scaffold_top: str
    scaffold_bottom: str
    default_guidance: str
    #: (name, type, required) declared on the template.
    variables: List[Tuple[str, Any, bool]]
    #: Sample values so a publisher can preview the composed prompt with no LLM.
    sample_vars: Dict[str, Any]
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 8000

    def compose(self, guidance: Optional[str]) -> str:
        """Wrap plain guidance in this family's scaffold to form the template."""
        text = (guidance or "").strip() or self.default_guidance.strip()
        return (
            f"{self.scaffold_top}\n{self.guidance_header}\n{text}\n"
            f"{GUIDANCE_FOOTER}\n\n{self.scaffold_bottom}"
        )

    def extract(self, template_text: Optional[str]) -> str:
        """Pull the guidance back out of a composed template, or '' if absent."""
        text = template_text or ""
        if self.guidance_header in text and GUIDANCE_FOOTER in text:
            return (
                text.split(self.guidance_header, 1)[1]
                .split(GUIDANCE_FOOTER, 1)[0]
                .strip()
            )
        return ""


# --------------------------------------------------------------------------- #
# syllabus_structure — what counts as a chapter
# --------------------------------------------------------------------------- #
_STRUCTURE_TOP = """\
You are reading an official syllabus and extracting its structure EXACTLY as
written. You are not designing a book and not summarising: you are transcribing a
hierarchy that already exists in the document.

BOOK CONTEXT (for disambiguation only — never a source of structure)
Title: {{ book_title }}
Subject: {{ book_subject }}
Audience / standard: {{ target_audience }}
"""

_STRUCTURE_BOTTOM = """\
ABSOLUTE RULES
1. Every "label" you output MUST appear VERBATIM in the syllabus text below.
   Copy the exact wording. Do not paraphrase, expand abbreviations, fix spelling,
   change capitalisation, re-order words, or add explanation.
2. Extract every level the document actually has. Do not invent levels, and do
   not collapse two real levels into one.
3. Set "chapter_level" to the level name that corresponds to one chapter of the
   finished book.
4. Preserve document order.
5. Where the document's own punctuation makes a boundary genuinely unclear (for
   example a full stop used where semicolons separate every other topic), still
   make your best split AND record it in "ambiguities".
6. Return ONLY the JSON object below. No markdown, no prose, no code fences.

{{ correction_note }}

OUTPUT SHAPE — return exactly this structure:
{
  "levels": ["section", "unit", "chapter"],
  "chapter_level": "chapter",
  "nodes": [
    {
      "level": "section",
      "label": "string, verbatim from the syllabus",
      "ordinal": 1,
      "children": [
        {
          "level": "unit",
          "label": "string, verbatim",
          "ordinal": 1,
          "children": [
            { "level": "chapter", "label": "string, verbatim" }
          ]
        }
      ]
    }
  ],
  "ambiguities": [
    {
      "context": "the unit the ambiguity is in",
      "issue": "short machine-ish reason, e.g. period_used_as_separator",
      "text": "the exact source text that was ambiguous"
    }
  ]
}

SYLLABUS TEXT
{{ syllabus_text }}
"""

_STRUCTURE_GUIDANCE = """\
- A UNIT is a broad area, usually introduced by a number or a bold heading, and
  usually followed by a list of the topics it contains.
- A CHAPTER is one of those individual topics. Chapters are what a reader would
  expect as a single chapter of a book: one teachable subject.
- Topics separated by semicolons, commas-then-capitals, full stops, bullets, or
  their own numbering (1.1, 1.2) beneath a unit heading are CHAPTERS, not one
  chapter. A run of topics on one line is still many chapters.
- Do NOT promote a unit to a chapter. If a unit heading is followed by a list of
  topics, the unit is a container and the topics are the chapters.
- Do NOT merge several topics into one chapter, and do NOT split a single topic
  into several.
- Some syllabi have an extra grouping above units (a paper, a part, a subject
  stream such as Physical / Organic / Inorganic). Represent it as its own level.
"""

SYLLABUS_STRUCTURE = PromptFamily(
    template="syllabus_structure",
    description=(
        "Extract a syllabus into an n-level unit -> chapter tree with verbatim labels."
    ),
    guidance_header=(
        "BOOK-TYPE GUIDANCE (what counts as a unit vs a chapter for this book type):"
    ),
    scaffold_top=_STRUCTURE_TOP,
    scaffold_bottom=_STRUCTURE_BOTTOM,
    default_guidance=_STRUCTURE_GUIDANCE,
    variables=[
        ("book_title", VariableType.STRING, False),
        ("book_subject", VariableType.STRING, False),
        ("target_audience", VariableType.STRING, False),
        ("syllabus_text", VariableType.STRING, True),
        ("correction_note", VariableType.STRING, False),
    ],
    sample_vars={
        "book_title": "Sample Book",
        "book_subject": "Sample Subject",
        "target_audience": "Class 10",
        "syllabus_text": "1. Sample Unit: first topic; second topic; third topic.",
        "correction_note": "",
    },
    # Extraction is a reading task: same syllabus must give the same tree.
    temperature=0.0,
)


# --------------------------------------------------------------------------- #
# chapter_content — how each chapter is written
# --------------------------------------------------------------------------- #
_CONTENT_TOP = """\
You are an experienced subject-matter author writing the chapter plan for a book.

The chapter list has ALREADY been decided: it was read from the official syllabus
and confirmed by a subject-matter expert. Your job is to write each chapter's
content description from the source material supplied with it.

BOOK CONTEXT
Title: {{ book_title }}
Subject: {{ book_subject }}
Audience / standard: {{ target_audience }}
Description: {{ book_description }}
Total chapters in this book: {{ chapter_count }}
Overall SME emphasis: {{ sme_emphasis }}
"""

_CONTENT_BOTTOM = """\
ABSOLUTE RULES
1. Write for EXACTLY the chapters given below, in the order given. Do not add a
   chapter, drop one, merge two, split one, rename one, or reorder them.
2. Return one object per REQUEST, in the same order. If there are 8 requests,
   return 8 objects.
3. Ground what you write in that chapter's own "source_material". Do not import
   facts about a chapter from your general knowledge when the source is silent.
4. Where a chapter has NO source material, keep the summary minimal and factual,
   do not invent specifics, and say what is missing in "grounding_note".
5. Do not repeat the chapter title back as the summary.
6. Return ONLY valid JSON matching the shape below. No markdown, no prose, no
   code fences.

OUTPUT SHAPE — return exactly this:
{
  "chapters": [
    {
      "summary": "3-5 sentences describing the chapter's scope",
      "learning_objectives": ["observable objective", "..."],
      "covered_topics": ["specific sub-topic", "..."],
      "key_concepts": ["named idea, law, model or term", "..."],
      "grounding_note": "only when source material was missing or thin; else \\"\\""
    }
  ]
}

CHAPTERS TO WRITE
{{ chapters_block }}
"""

_CONTENT_GUIDANCE = """\
- Write for the stated audience/standard. Calibrate vocabulary and depth to it:
  a school-level book explains from first principles; a competitive-exam book
  assumes the fundamentals and focuses on application and discrimination between
  close concepts.
- The summary is a scope statement, not marketing. Say what the chapter covers and
  where its boundaries are, in 3-5 sentences.
- Learning objectives must be observable. Prefer "explain", "compare", "derive",
  "classify", "evaluate" over "understand" or "know about".
- covered_topics are the specific sub-topics inside this chapter. Take them from
  the source material where possible, not from general knowledge.
- key_concepts are the named ideas, laws, models or terms a reader must come away
  holding.
- Let sme_weight set the depth: a weight-5 chapter deserves a fuller treatment and
  more objectives than a weight-2 chapter. An unweighted chapter gets a neutral,
  moderate treatment.
- Honour sme_notes. If the SME left a note on a chapter, it overrides your own
  reading of the source material.
"""

CHAPTER_CONTENT = PromptFamily(
    template="chapter_content",
    description=(
        "Write per-chapter blueprint prose for an SME-approved chapter list, "
        "grounded in per-chapter retrieval."
    ),
    guidance_header="BOOK-TYPE GUIDANCE (depth, tone and emphasis for this book type):",
    scaffold_top=_CONTENT_TOP,
    scaffold_bottom=_CONTENT_BOTTOM,
    default_guidance=_CONTENT_GUIDANCE,
    variables=[
        ("book_title", VariableType.STRING, False),
        ("book_subject", VariableType.STRING, False),
        ("target_audience", VariableType.STRING, False),
        ("book_description", VariableType.STRING, False),
        ("chapter_count", VariableType.INTEGER, False),
        ("sme_emphasis", VariableType.STRING, False),
        ("chapters_block", VariableType.STRING, True),
    ],
    sample_vars={
        "book_title": "Sample Book",
        "book_subject": "Sample Subject",
        "target_audience": "Class 10",
        "book_description": "A sample description.",
        "chapter_count": 8,
        "sme_emphasis": "(none provided)",
        "chapters_block": (
            "--- REQUEST 1 ---\n"
            "unit: Sample Unit\n"
            "chapter_title: Sample Chapter\n"
            "sme_weight: 3\n"
            "sme_notes: (none)\n"
            "source_material:\n  [source 1 · document 1] sample retrieved text"
        ),
    },
    temperature=0.3,
)


#: Every guidance-managed family, keyed by base template name. The FIRST entry is
#: the default a caller gets when it does not name one — the prose prompt, because
#: that is what a publisher edits day to day.
FAMILIES: Dict[str, PromptFamily] = {
    CHAPTER_CONTENT.template: CHAPTER_CONTENT,
    SYLLABUS_STRUCTURE.template: SYLLABUS_STRUCTURE,
}

DEFAULT_FAMILY = CHAPTER_CONTENT.template


def get_family(template: Optional[str] = None) -> PromptFamily:
    """Resolve a family by base template name, defaulting to the prose prompt.

    Raises ``KeyError`` for an unknown name so the caller can turn it into a 400
    listing the valid options, rather than silently editing the wrong prompt —
    which is precisely the failure this module exists to prevent.
    """
    name = (template or DEFAULT_FAMILY).strip()
    if name not in FAMILIES:
        raise KeyError(name)
    return FAMILIES[name]


def family_names() -> List[str]:
    return list(FAMILIES)
