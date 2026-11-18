"""BlueprintState — state for the book-structure (blueprint) phase.

The blueprint agent turns gathered requirements into a book outline: title,
description, and a list of chapters (each with its own summary/objectives).
"""
from typing import Any, Dict, List, Optional

from pydantic import Field

from src.modules.book_forge.ai.orchestration.workflow_state.base_workflow_state import (
    BaseWorkflowState,
)


class BlueprintState(BaseWorkflowState):
    # --- Inputs (seeded from the project row by the entry point) --------------
    title: Optional[str] = None
    description: Optional[str] = None
    target_audience: Optional[str] = None
    # Desired number of chapters (project.chapter_count); steers generation.
    chapter_count: Optional[int] = None
    # Arbitrary project metadata used to build the query/prompt (subject,
    # category, language, publisher, edition, expected_pages, ...).
    project_metadata: Dict[str, Any] = Field(default_factory=dict)
    # Optional SME emphasis/priority note — the authoritative weighting signal
    # (e.g. "emphasize Climatology; go light on Regional Planning").
    sme_emphasis: Optional[str] = None

    # --- RAG working fields ---------------------------------------------------
    # The system-generated retrieval query (templated from project metadata).
    query: Optional[str] = None
    # The chunks retrieved from the vector store, as plain dicts
    # ({text, score, document_id, chunk_index, ...}). The raw embedding vector is
    # deliberately NOT stored — query text + retrieved context are the useful,
    # traceable artifacts.
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_metadata: Dict[str, Any] = Field(default_factory=dict)

    # --- Output: the generated blueprint --------------------------------------
    # Chapter outline: [{"chapter_number", "title", "summary",
    #                    "learning_objectives": [...], "covered_topics": [...]}, ...].
    # The SME-signed-off chapter list loaded from the submitted audit sheet.
    # AUTHORITATIVE: generation writes prose for these chapters and may not add,
    # drop, rename or reorder them.
    audit_chapters: List[Dict[str, Any]] = Field(default_factory=list)
    audit_sheet_version: Optional[int] = None
    # Chapters for which retrieval found no source material — reported rather
    # than quietly written from the model's own general knowledge.
    ungrounded_chapters: List[str] = Field(default_factory=list)

    chapters: List[Dict[str, Any]] = Field(default_factory=list)
    estimated_length: Optional[int] = None
