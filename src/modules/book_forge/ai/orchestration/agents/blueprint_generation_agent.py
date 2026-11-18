"""BlueprintGenerationAgent — write the blueprint from a signed-off structure.

The chapter list is NOT decided here. It arrives on the state as
``audit_chapters``: the structure extracted from the syllabus and then confirmed
by an SME through the audit sheet. This agent's only job is to write each
chapter's prose from source material retrieved for that specific chapter.

    signed-off chapters (authoritative)
        -> per-chapter retrieval  (embed the chapter title -> vector search)
        -> batched LLM calls      (versioned chapter_content prompt)
        -> summary / objectives / covered topics / key concepts per chapter

Why per-chapter retrieval. The previous implementation embedded ONE broad query
("create a blueprint of the book titled X") and handed the top-k results to the
model for the whole book. As the design notes predicted, a query that general does
not embed close to any particular syllabus chunk, so scores came back flat and the
model saw an arbitrary slice of the corpus — then filled the gaps from its own
general knowledge. That is what an SME reads as "generic, no real expertise".
With the chapter title as the query, retrieval is narrow and well ranked.

Two invariants are enforced in code, not asked of the model:

* **Titles are restored after generation.** Whatever the model returns, each
  chapter's title is overwritten with the SME-approved wording, and chapters are
  matched back by position. The model cannot rename, merge, drop or reorder.
* **Ungrounded chapters are reported.** A chapter whose retrieval found nothing is
  recorded in ``state.ungrounded_chapters`` instead of being quietly written from
  the model's priors — that is a knowledge gap for the "upload more sources" loop,
  not something to paper over.
"""
import json
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk
from src.modules.book_forge.ai.foundation.embeddings.models import EmbeddingRequest
from src.modules.book_forge.ai.foundation.embeddings.services import embedding_service
from src.modules.book_forge.ai.foundation.llm.models import (
    LLMMessage,
    LLMRequest,
    LLMRole,
)
from src.modules.book_forge.ai.foundation.llm.services.llm_service import llm_service
from src.modules.book_forge.ai.foundation.llm.utils.model_mapping import (
    provider_for_model,
)
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository
from src.modules.book_forge.ai.foundation.vector_store.models import VectorSearchRequest
from src.modules.book_forge.ai.foundation.vector_store.services import (
    vector_store_service,
)
from src.modules.book_forge.ai.intelligence.guardrails.models import GuardrailRequest
from src.modules.book_forge.ai.intelligence.guardrails.policies import (
    PromptInjectionPolicy,
)
from src.modules.book_forge.ai.intelligence.guardrails.services.guardrail_service import (
    GuardrailService,
)
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.blueprint_context import BlueprintContext
from src.modules.book_forge.ai.orchestration.workflow_state import BlueprintState

# Blueprint content is the publisher's OWN educational material and the output is a
# chapter outline, so PII scanning here only yields false positives (dates, year
# ranges, or a contact number inside an uploaded syllabus/PYQ) and would block
# legitimate book planning. We keep prompt-injection protection (against malicious
# retrieved content); output validation (toxicity, JSON shape) runs regardless.
_guardrail = GuardrailService(policies=[PromptInjectionPolicy()])

CONTENT_TEMPLATE = "chapter_content"

# How many chapters go into one LLM call. Small enough that each chapter keeps its
# own retrieved context in the prompt, large enough that a 113-chapter book is
# ~12 calls rather than 113.
CHAPTER_BATCH_SIZE = 8

# Chunks retrieved per chapter. Narrow by design: the query is a specific chapter
# title, so the top few hits are the relevant ones.
CHAPTER_TOP_K = 6

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 8000
_DEFAULT_TEMPERATURE = 0.3

# Guardrail rules that are genuine SAFETY concerns and MUST block generation.
# Everything else the guardrail can flag (notably ``valid_json`` / structural
# checks) is a *format* concern that repair + our own parse/validation recover
# from — those must NOT hard-fail a blueprint we can successfully parse. Some
# models (e.g. gpt-4o) wrap JSON in ```json fences, which trips ``valid_json`` on
# the raw text even though the payload is perfectly good once unwrapped.
_SAFETY_RULES = {
    "prompt_injection",
    "unsafe_instructions",
    "toxic_content",
    "PII",
    "pii",
}


def _strip_code_fences(text: str) -> str:
    """Remove a leading ```json / ``` fence and a trailing ``` if present."""
    if not text:
        return text
    stripped = text.strip()
    if stripped.startswith("```"):
        newline = stripped.find("\n")
        stripped = stripped[newline + 1 :] if newline != -1 else stripped[3:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def build_prompt_variables(state: BlueprintState) -> Dict[str, Any]:
    """Map the project metadata on the state to the prompt template variables.

    Shared by every blueprint-family prompt so they all see the same project
    context. ``target_audience`` doubles as the "standard" (e.g. class-8, class-10,
    graduate) that the prompt uses to calibrate depth, difficulty and question mix.
    """
    pm = state.project_metadata or {}
    return {
        "book_title": state.title or "",
        "book_subject": pm.get("book_subject") or "",
        "target_audience": state.target_audience or "",
        "book_description": state.description or "",
        "chapter_count": len(state.audit_chapters) or state.chapter_count or 8,
    }


def resolve_template_name(repo, base_name: str, category: Optional[str]) -> str:
    """Pick the category-specific template if it exists, else the generic base.

    e.g. category "history" -> "chapter_content_history" when that template
    exists, otherwise "chapter_content". This is how one pipeline serves many
    book types: category selects the template; the standard/audience calibrates it.
    """
    if category:
        slug = str(category).strip().lower().replace(" ", "_").replace("-", "_")
        if slug and repo.get_template_by_name(f"{base_name}_{slug}") is not None:
            return f"{base_name}_{slug}"
    return base_name


def _batches(items: List[Any], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


class BlueprintGenerationAgent(BaseAgent[BlueprintState]):
    """Write blueprint prose for an SME-approved chapter list."""

    name = "Blueprint Generation Agent"
    step = "generate_blueprint"

    def __init__(self, *, context: BlueprintContext) -> None:
        super().__init__()
        self._context = context

    # -- retrieval ---------------------------------------------------------
    def _retrieve_for_chapter(
        self, chapter: Dict[str, Any], state: BlueprintState
    ) -> List[Dict[str, Any]]:
        """Retrieve source material for ONE chapter.

        The query is the chapter title plus its unit, which is specific enough for
        similarity ranking to be meaningful — unlike a whole-book query.
        """
        query = chapter["title"]
        if chapter.get("unit"):
            query = f"{chapter['unit']}: {query}"
        try:
            response = embedding_service.embed(
                EmbeddingRequest(
                    chunks=[Chunk(chunk_index=0, text=query)],
                    model=settings.embedding_model,
                    provider=settings.embedding_provider,
                    project_id=state.project_id,
                )
            )
            results = vector_store_service.search(
                VectorSearchRequest(
                    query_vector=response.vectors[0].embedding,
                    top_k=CHAPTER_TOP_K,
                    collection=f"project_{state.project_id}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - a retrieval miss is not fatal
            # One chapter failing to retrieve must not abandon the other 112; it
            # is recorded as ungrounded and surfaced on the state.
            state.add_message(
                "system",
                f"Retrieval failed for chapter '{chapter['title']}': {exc}",
            )
            return []
        return [
            {
                "text": result.text,
                "score": result.score,
                "document_id": (result.metadata or {}).get("document_id"),
            }
            for result in results
        ]

    # -- generation --------------------------------------------------------
    def execute(self, state: BlueprintState) -> None:
        context = self._context

        chapters = state.audit_chapters
        if not chapters:
            state.fail(
                "No signed-off chapter structure on the state — an audit sheet "
                "must be submitted before a blueprint can be generated."
            )
            return

        repo = PromptRepository(context.db)
        category = (state.project_metadata or {}).get("category")
        template_name = resolve_template_name(repo, CONTENT_TEMPLATE, category)
        template = repo.get_template_by_name(template_name)
        if template is None:
            state.fail(
                f"Prompt template '{CONTENT_TEMPLATE}' is not seeded. Run "
                "scripts/seed_chapter_content_prompt.py first."
            )
            return
        version = repo.get_active_version(template.id)
        model = (version.model if version else None) or _DEFAULT_MODEL
        temperature = (
            version.temperature
            if version and version.temperature is not None
            else _DEFAULT_TEMPERATURE
        )
        max_tokens = (version.max_tokens if version else None) or _DEFAULT_MAX_TOKENS
        provider = provider_for_model(model)

        base_variables = build_prompt_variables(state)
        base_variables["sme_emphasis"] = (
            state.sme_emphasis or ""
        ).strip() or "(none provided)"

        # 1) Retrieve per chapter. Cheap relative to generation, and it is what
        #    makes the prose specific rather than plausible.
        for chapter in chapters:
            chapter["_chunks"] = self._retrieve_for_chapter(chapter, state)

        grounded = [c for c in chapters if c["_chunks"]]
        state.ungrounded_chapters = [
            c["title"] for c in chapters if not c["_chunks"]
        ]
        state.add_message(
            "system",
            f"Retrieved context for {len(grounded)}/{len(chapters)} chapter(s).",
        )

        # 2) Generate in batches, each chapter carrying its own context.
        written: List[Dict[str, Any]] = []
        for batch in _batches(chapters, CHAPTER_BATCH_SIZE):
            variables = dict(base_variables)
            variables["chapters_block"] = _format_chapter_requests(batch)
            rendered = context.prompt_service.render_prompt(
                template_name, variables
            ).rendered_text

            holder: Dict[str, str] = {}

            def _llm(prompt_text: str) -> str:
                result = llm_service.generate(
                    LLMRequest(
                        model=model,
                        messages=[
                            LLMMessage(role=LLMRole.USER, content=prompt_text)
                        ],
                        max_tokens=max_tokens,
                        temperature=temperature,
                        project_id=state.project_id,
                    ),
                    provider=provider,
                )
                content = _strip_code_fences(result.content)
                holder["raw"] = content
                return content

            guard = _guardrail.run(
                GuardrailRequest(
                    prompt=rendered,
                    operation="generate",
                    llm_provider=provider.value,
                ),
                llm=_llm,
                repair=True,
                raise_on_violation=False,
            )

            safety_rules = sorted(
                {v.rule for v in guard.violations if v.rule in _SAFETY_RULES}
            )
            if safety_rules:
                # Structured marker so the entry-point service can raise a
                # PolicyViolationException and surface a clear response.
                state.metadata["policy_violation"] = {
                    "rules": safety_rules,
                    "message": "Policy violated. Guardrail blocked",
                }
                state.fail(f"Policy violated. Guardrail blocked: {safety_rules}")
                return

            final_text = guard.modified_output or holder.get("raw")
            written.extend(_merge_batch(batch, final_text))

        state.chapters = written
        state.estimated_length = state.estimated_length or len(written) * 20
        state.add_message(
            "assistant",
            f"Wrote {len(written)} chapter(s) from the signed-off structure "
            f"(audit sheet v{state.audit_sheet_version}); "
            f"{len(state.ungrounded_chapters)} without source material.",
        )


def _format_chapter_requests(batch: List[Dict[str, Any]]) -> str:
    """Render one batch of chapters, each with its own retrieved context."""
    blocks: List[str] = []
    for index, chapter in enumerate(batch, start=1):
        chunks = chapter.get("_chunks") or []
        if chunks:
            context_text = "\n".join(
                f"  [source {n} · document {c.get('document_id')}] {c.get('text', '')}"
                for n, c in enumerate(chunks, start=1)
            )
        else:
            context_text = (
                "  (no source material was retrieved for this chapter — say so "
                "in 'grounding_note' and keep the summary strictly minimal)"
            )
        weight = chapter.get("sme_weight")
        notes = (chapter.get("sme_notes") or "").strip()
        blocks.append(
            f"--- REQUEST {index} ---\n"
            f"unit: {chapter.get('unit') or '(none)'}\n"
            f"chapter_title: {chapter['title']}\n"
            f"sme_weight: {weight if weight is not None else '(unweighted)'}\n"
            f"sme_notes: {notes or '(none)'}\n"
            f"source_material:\n{context_text}"
        )
    return "\n\n".join(blocks)


def _merge_batch(
    batch: List[Dict[str, Any]], text: Optional[str]
) -> List[Dict[str, Any]]:
    """Merge generated prose back onto the signed-off chapters.

    Chapters are matched BY POSITION and the approved title is written back over
    whatever the model returned, so a model that renames, reorders, merges or drops
    a chapter cannot corrupt the structure. A batch that fails to parse still
    yields its chapters — with empty prose and a note — rather than losing them.
    """
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except Exception:  # noqa: BLE001 - fall back to the repair processor
            parsed = _guardrail.repair_json(text)

    items: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        # Accept either {"chapters": [...]} or a bare list.
        candidate = parsed.get("chapters")
        items = candidate if isinstance(candidate, list) else []
    elif isinstance(parsed, list):
        items = parsed

    merged: List[Dict[str, Any]] = []
    for index, chapter in enumerate(batch):
        generated = items[index] if index < len(items) and isinstance(
            items[index], dict
        ) else {}
        merged.append(
            {
                # Structure fields come from the signed-off sheet, never the model.
                "chapter_number": chapter.get("chapter_number"),
                "title": chapter["title"],
                "unit": chapter.get("unit"),
                "unit_number": chapter.get("unit_number"),
                "section": chapter.get("section"),
                "weight": chapter.get("sme_weight"),
                # Prose fields come from the model.
                "summary": (generated.get("summary") or "").strip(),
                "learning_objectives": _string_list(
                    generated.get("learning_objectives")
                ),
                "covered_topics": _string_list(generated.get("covered_topics")),
                "key_concepts": _string_list(generated.get("key_concepts")),
                # Provenance: which sources this chapter was written from, and
                # whether it had any at all.
                "grounded": bool(chapter.get("_chunks")),
                "source_document_ids": sorted(
                    {
                        c.get("document_id")
                        for c in (chapter.get("_chunks") or [])
                        if c.get("document_id") is not None
                    }
                ),
                "grounding_note": (generated.get("grounding_note") or "").strip()
                or None,
            }
        )
    return merged


def _string_list(value: Any) -> List[str]:
    """Coerce a model-returned value into a clean list of non-empty strings."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
