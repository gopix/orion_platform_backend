"""Syllabus structure extraction — read the unit -> chapter hierarchy.

The blueprint's chapter list must come from what the syllabus *says*, not from
what a model infers out of retrieved prose. Getting this wrong is what produced a
blueprint whose "chapters" were actually the ten syllabus units.

    syllabus document(s)
        -> parser_service (structured document model)
        -> versioned, category-scoped structure prompt (Prompt Engine)
        -> LLM extracts an n-level tree of VERBATIM labels
        -> every label verified against the source text
        -> flattened chapter rows + ambiguity flags for the audit sheet

Two design points carry the weight:

**Verification, not parsing.** A regex per publisher does not survive the next
syllabus format; an unverified LLM invents chapters. So the LLM extracts and every
node it returns is then checked to appear verbatim in the source. Anything that
does not is surfaced as a flag for the SME rather than silently trusted or
silently dropped — the human sees exactly what we could not confirm.

**Depth is not assumed.** The tree is n-level and the prompt declares which level
is a book chapter, because a UPSC optional paper is Paper -> Section -> Unit ->
Chapter while a JEE chemistry syllabus adds a stream level. Hard-coding two levels
would re-create the original bug on the next book type.
"""
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.logger import get_logger
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
from src.modules.book_forge.ai.foundation.prompts.services import build_prompt_service
from src.modules.book_forge.ai.intelligence.guardrails.services.guardrail_service import (
    GuardrailService,
)
from src.modules.book_forge.ai.intelligence.parsers.models import ParsedDocument
from src.modules.book_forge.ai.intelligence.parsers.services import parser_service
# resolve_template_name gives the category fallback (structure_<category> ->
# structure). Reused rather than reimplemented so both prompt families resolve
# identically — RetrieveKnowledgeNode imports it the same way.
from src.modules.book_forge.ai.orchestration.agents.blueprint_generation_agent import (
    resolve_template_name,
)
from src.modules.book_forge.models.bookforge_document_model import (
    BookForgeDocumentModel,
)
from src.modules.book_forge.services import project_service

logger = get_logger(__name__)

STRUCTURE_TEMPLATE = "syllabus_structure"
# Documents must be tagged with this type at upload for the system to know which
# of a project's files is the syllabus.
SYLLABUS_DOCUMENT_TYPE = "syllabus"

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 8000
_DEFAULT_TEMPERATURE = 0.0  # structure extraction is not a creative task

# Retry once when the model returns labels that are not in the source: a second
# attempt naming the failures usually fixes it. Beyond that we hand the problem
# to the SME rather than looping on the model's expense.
_MAX_ATTEMPTS = 2

_guardrail = GuardrailService()


# --------------------------------------------------------------------------- #
# source documents
# --------------------------------------------------------------------------- #
def get_syllabus_documents(
    db: Session, project_id: int
) -> List[BookForgeDocumentModel]:
    """Return the project's syllabus documents, or 409 if none are tagged.

    Refusing here is deliberate: silently falling back to "every document" would
    feed the SME interview and previous-year questions into structure extraction,
    and the resulting chapter list would be a blend of the syllabus and whatever
    else was uploaded.
    """
    documents = (
        db.query(BookForgeDocumentModel)
        .filter(
            BookForgeDocumentModel.project_id == project_id,
            BookForgeDocumentModel.is_deleted.is_(False),
            # document_type is free text, so compare case-insensitively.
            func.lower(BookForgeDocumentModel.document_type)
            == SYLLABUS_DOCUMENT_TYPE,
        )
        .order_by(BookForgeDocumentModel.id.asc())
        .all()
    )
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No syllabus document found for this project. Upload the syllabus "
                f"with document_type='{SYLLABUS_DOCUMENT_TYPE}' before generating "
                "an audit sheet."
            ),
        )
    return documents


def _document_text(parsed: ParsedDocument) -> str:
    """Flatten a ParsedDocument back to plain text for extraction + verification.

    Section titles are emitted as their own lines so a heading-shaped syllabus
    keeps its outline, and paragraph text is preserved verbatim so the
    verbatim check has something faithful to match against.
    """
    lines: List[str] = []

    def walk(sections) -> None:
        for section in sections or []:
            if section.title:
                lines.append(section.title)
            for paragraph in section.paragraphs or []:
                if paragraph.text:
                    lines.append(paragraph.text)
            walk(section.subsections)

    if parsed.title:
        lines.append(parsed.title)
    walk(parsed.sections)
    for paragraph in parsed.paragraphs or []:
        if paragraph.text:
            lines.append(paragraph.text)
    # Tables sometimes carry a weightage/marks grid worth keeping in context.
    for table in parsed.tables or []:
        for row in getattr(table, "rows", None) or []:
            cells = [str(cell) for cell in row if cell]
            if cells:
                lines.append(" | ".join(cells))

    return "\n".join(lines)


def read_source_text(
    documents: List[BookForgeDocumentModel],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse each syllabus document and return the combined text plus provenance.

    A document that cannot be parsed is recorded and skipped rather than failing
    the whole run — one bad file should not block a project with three good ones.
    """
    parts: List[str] = []
    sources: List[Dict[str, Any]] = []
    for document in documents:
        entry: Dict[str, Any] = {
            "document_id": document.id,
            "filename": document.original_filename,
        }
        try:
            parsed = parser_service.parse(
                document.file_path, filename=document.original_filename
            )
            text = _document_text(parsed)
            entry.update({"characters": len(text), "parsed": True})
            parts.append(text)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
            logger.warning(
                "Could not parse syllabus document %s (%s): %s",
                document.id,
                document.original_filename,
                exc,
            )
            entry.update({"parsed": False, "error": str(exc)})
        sources.append(entry)

    combined = "\n\n".join(parts).strip()
    if not combined:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The syllabus document(s) could not be parsed into any text. "
                "A scanned PDF needs OCR before it can be used."
            ),
        )
    return combined, sources


# --------------------------------------------------------------------------- #
# verbatim verification
# --------------------------------------------------------------------------- #
_QUOTE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
}


def normalize_for_match(text: str) -> str:
    """Fold a string so verbatim matching survives cosmetic differences.

    Syllabus PDFs use curly quotes and en-dashes that a model routinely returns as
    ASCII; without folding these, a perfectly correct label fails verification.
    Casing and whitespace runs are also collapsed. Nothing is *removed*, so a
    genuinely invented label still fails.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text)
    for source_char, target in _QUOTE_MAP.items():
        folded = folded.replace(source_char, target)
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip().lower()


def verify_labels(
    labels: List[str], source_text: str
) -> Tuple[List[str], List[str]]:
    """Split ``labels`` into (found verbatim, not found) against the source."""
    haystack = normalize_for_match(source_text)
    found, missing = [], []
    for label in labels:
        needle = normalize_for_match(label)
        if needle and needle in haystack:
            found.append(label)
        else:
            missing.append(label)
    return found, missing


# --------------------------------------------------------------------------- #
# tree flattening
# --------------------------------------------------------------------------- #
def flatten_tree(
    nodes: List[Dict[str, Any]], chapter_level: str
) -> List[Dict[str, Any]]:
    """Walk an n-level node tree and emit one row per chapter-level node.

    ``unit`` is the nearest ancestor above the chapter and ``section`` the one
    above that, so a 3-level tree (unit -> chapter) and a 4-level tree
    (section -> unit -> chapter) both flatten correctly without the caller
    declaring which shape it has.
    """
    rows: List[Dict[str, Any]] = []
    target = (chapter_level or "chapter").strip().lower()
    # Per-unit chapter numbering, keyed by the unit label.
    counters: Dict[str, int] = {}

    def walk(node: Dict[str, Any], ancestors: List[Dict[str, Any]]) -> None:
        if not isinstance(node, dict):
            return
        level = str(node.get("level") or "").strip().lower()
        label = (node.get("label") or "").strip()
        children = node.get("children") or []

        if level == target and label:
            unit = ancestors[-1] if ancestors else None
            section = ancestors[-2] if len(ancestors) >= 2 else None
            unit_label = (unit or {}).get("label") or ""
            counters[unit_label] = counters.get(unit_label, 0) + 1
            rows.append(
                {
                    "section": (section or {}).get("label"),
                    "unit_number": (unit or {}).get("ordinal")
                    or _unit_ordinal(unit_label, rows),
                    "unit": unit_label,
                    "chapter_number": counters[unit_label],
                    "chapter": label,
                    "pyq_hits": 0,
                    "pyq_years": None,
                }
            )
            # A chapter-level node is a leaf for our purposes; deeper nodes
            # (sub-topics) are not separate chapters.
            return

        for child in children:
            walk(child, ancestors + [node] if label else ancestors)

    for node in nodes or []:
        walk(node, [])
    return rows


def _unit_ordinal(unit_label: str, rows: List[Dict[str, Any]]) -> int:
    """Assign a 1-based unit number in first-seen order when none was supplied."""
    seen: List[str] = []
    for row in rows:
        if row["unit"] not in seen:
            seen.append(row["unit"])
    if unit_label not in seen:
        seen.append(unit_label)
    return seen.index(unit_label) + 1


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def _parse_json(text: str) -> Any:
    """Parse JSON, falling back to the guardrail repair processor.

    Same two-step as BlueprintGenerationAgent: some models wrap JSON in a
    Markdown fence, which ``repair_json`` unwraps.
    """
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001 - fall through to repair
        return _guardrail.repair_json(text)


def extract_structure(db: Session, project_id: int) -> Dict[str, Any]:
    """Extract the verified chapter structure for a project's syllabus.

    Returns ``{"chapters": [...], "flags": [...], "source": {...}}`` ready for the
    audit sheet. Raises 409 when no syllabus is tagged, 422 when it cannot be read.
    """
    project = project_service.get_project(db, project_id)
    documents = get_syllabus_documents(db, project_id)
    source_text, sources = read_source_text(documents)

    repository = PromptRepository(db)
    prompt_service = build_prompt_service(db)
    category = (project.to_dict() or {}).get("category")
    template_name = resolve_template_name(repository, STRUCTURE_TEMPLATE, category)

    template = repository.get_template_by_name(template_name)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Prompt template '{STRUCTURE_TEMPLATE}' is not seeded. Run "
                "scripts/seed_syllabus_structure_prompt.py first."
            ),
        )
    version = repository.get_active_version(template.id)
    model = (version.model if version else None) or _DEFAULT_MODEL
    temperature = (
        version.temperature if version and version.temperature is not None
        else _DEFAULT_TEMPERATURE
    )
    max_tokens = (version.max_tokens if version else None) or _DEFAULT_MAX_TOKENS
    provider = provider_for_model(model)

    flags: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    retry_note = ""

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        variables = {
            "book_title": project.book_title or "",
            "book_subject": (project.to_dict() or {}).get("book_subject") or "",
            "target_audience": project.target_audience or "",
            "syllabus_text": source_text,
            "correction_note": retry_note,
        }
        rendered = prompt_service.render_prompt(
            template_name, variables
        ).rendered_text

        result = llm_service.generate(
            LLMRequest(
                model=model,
                messages=[LLMMessage(role=LLMRole.USER, content=rendered)],
                max_tokens=max_tokens,
                temperature=temperature,
                project_id=project_id,
            ),
            provider=provider,
        )
        payload = _parse_json(result.content)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("nodes"), list
        ):
            if attempt < _MAX_ATTEMPTS:
                retry_note = (
                    "Your previous reply was not a JSON object with a 'nodes' "
                    "array. Return ONLY the JSON object described above."
                )
                continue
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Structure extraction did not return a usable node tree.",
            )

        chapter_level = payload.get("chapter_level") or "chapter"
        rows = flatten_tree(payload["nodes"], chapter_level)
        if not rows:
            if attempt < _MAX_ATTEMPTS:
                retry_note = (
                    f"Your previous reply contained no nodes at level "
                    f"'{chapter_level}'. Every chapter must be a node at that level."
                )
                continue
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Structure extraction produced no chapters. Check the "
                    "syllabus document and the structure prompt's guidance."
                ),
            )

        _, missing = verify_labels([row["chapter"] for row in rows], source_text)
        if not missing:
            flags = _ambiguity_flags(payload)
            break

        if attempt < _MAX_ATTEMPTS:
            sample = "; ".join(missing[:10])
            retry_note = (
                "These labels from your previous reply do NOT appear verbatim in "
                f"the syllabus text: {sample}. Copy chapter labels EXACTLY as they "
                "are written in the source. Do not paraphrase, expand or invent."
            )
            logger.info(
                "Structure extraction attempt %s: %s/%s labels unverified, retrying",
                attempt,
                len(missing),
                len(rows),
            )
            continue

        # Second attempt still has unverified labels. Keep them, but flag every
        # one so the SME sees precisely what we could not confirm — dropping them
        # silently would hide a hallucination, trusting them silently would ship it.
        flags = _ambiguity_flags(payload)
        for label in missing:
            flags.append(
                {
                    "unit": next(
                        (r["unit"] for r in rows if r["chapter"] == label), ""
                    ),
                    "reason": "not_found_verbatim_in_syllabus",
                    "segment": label,
                }
            )
        logger.warning(
            "Structure extraction for project %s kept %s unverified label(s)",
            project_id,
            len(missing),
        )

    units = []
    for row in rows:
        if row["unit"] not in units:
            units.append(row["unit"])

    logger.info(
        "Syllabus structure extracted | project=%s documents=%s units=%s "
        "chapters=%s unverified=%s model=%s",
        project_id,
        len(documents),
        len(units),
        len(rows),
        len([f for f in flags if f["reason"] == "not_found_verbatim_in_syllabus"]),
        model,
    )

    return {
        "chapters": rows,
        "flags": flags,
        "source": {
            "documents": sources,
            "characters": len(source_text),
            "units": len(units),
            "chapters": len(rows),
            "template": template_name,
            "model": model,
            "unverified": len(
                [f for f in flags if f["reason"] == "not_found_verbatim_in_syllabus"]
            ),
        },
    }


def _ambiguity_flags(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise the model's self-reported ambiguities into flag rows."""
    flags: List[Dict[str, Any]] = []
    for item in payload.get("ambiguities") or []:
        if not isinstance(item, dict):
            continue
        flags.append(
            {
                "unit": item.get("context") or item.get("unit") or "",
                "reason": item.get("issue") or "ambiguous_separator",
                "segment": item.get("text") or "",
            }
        )
    return flags
