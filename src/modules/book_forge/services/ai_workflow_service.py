"""AI workflow service — the entry point into the AI Orchestration layer.

This service is intentionally thin. It does NOT orchestrate AI (no Parser, no
Chunking, no Embeddings, no Pinecone). Its only job is to:

1. load the project and its documents,
2. build the initial ``ProcessingWorkflowState``,
3. invoke the Book Processing Orchestrator,
4. return the final processing result.

From there everything happens inside Orchestration:

    AIWorkflowService
        -> BookProcessingOrchestrator
        -> book_processing graph -> nodes -> agents -> AI services

Changing *what* runs (add OCR, parallel stages, review loop-backs) is a change to
the graph — this service never moves.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import SessionLocal
from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.prompts.services import build_prompt_service
from src.modules.book_forge.ai.intelligence.guardrails.exceptions import (
    PolicyViolationException,
)
from src.modules.book_forge.ai.orchestration.blueprint_context import BlueprintContext
from src.modules.book_forge.ai.orchestration.orchestrators import (
    blueprint_orchestrator,
    book_processing_orchestrator,
)
from src.modules.book_forge.ai.orchestration.workflow_state import (
    BlueprintState,
    ProcessingWorkflowState,
    WorkflowStatus,
)
from src.modules.book_forge.services import (
    audit_sheet_service,
    blueprint_service,
    document_service,
    project_service,
)

logger = get_logger(__name__)


def process_project(db: Session, 
    project_id: int,
    documents: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Start the Book Processing workflow for a project and return its result."""

    # 1) Load the project and its documents.
    project_service.get_project(db, project_id)
    if documents is None:
        documents = document_service.get_documents(db, project_id=project_id,
                                                     skip=0, limit=1000)

    # 2) Build the initial workflow state (data only — no AI logic here).
    state = ProcessingWorkflowState(project_id=project_id,
                                     documents=[_descriptor(document) for document in documents],
                                    )

    # 3) Hand off to the Orchestration layer.
    final_state = book_processing_orchestrator.execute(state)

    # 4) Return a summary of the final state.
    return _summarize(final_state)


def _descriptor(document: Any) -> Dict[str, Any]:
    """A lightweight, serialisable reference the workflow carries per document."""
    return {
        "id": getattr(document, "id", None),
        "project_id": getattr(document, "project_id", None),
        "filename": getattr(document, "original_filename", None),
        "file_path": getattr(document, "file_path", None),
    }


def _summarize(state: ProcessingWorkflowState) -> Dict[str, Any]:
    graph = state.knowledge_graph
    return {
        "run_id": state.run_id,
        "project_id": state.project_id,
        "status": state.status.value,
        "documents": len(state.documents),
        "parsed_documents": len(state.parsed_documents),
        "graph_nodes": len(graph.nodes) if graph else 0,
        "graph_edges": len(graph.edges) if graph else 0,
        "chunks": len(state.chunks),
        "embeddings": len(state.embeddings),
        "vector_ids": len(state.vector_ids),
        "skipped": state.skipped,
        "errors": state.errors,
    }


def prepare_blueprint(
    db: Session,
    project_id: int,
    created_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Gate the run and reserve a blueprint row before generation starts.

    Called synchronously by the endpoint so the caller gets an immediate, honest
    answer: 409 if there is no SME-signed-off structure to generate from, or a
    reserved blueprint row (status ``generating``) whose id is the handle for
    polling. Generation itself happens in the background — see
    ``run_blueprint_job``.
    """
    project_service.get_project(db, project_id)
    # 409s when no audit sheet has been submitted. This is the gate that makes an
    # ungrounded blueprint reaching an SME structurally impossible.
    structure = audit_sheet_service.get_signed_off_structure(db, project_id)

    record = blueprint_service.create_blueprint(
        db,
        project_id=project_id,
        blueprint_json={
            "status": "generating",
            "audit_sheet_version": structure["audit_sheet_version"],
            "chapter_count": len(structure["chapters"]),
            "units": [],
        },
        status="generating",
        created_by=created_by,
    )
    return {
        "blueprint_id": record.id,
        "version": record.version,
        "audit_sheet_version": structure["audit_sheet_version"],
        "chapters_to_write": len(structure["chapters"]),
    }


def run_blueprint_job(
    project_id: int,
    blueprint_id: int,
    created_by: Optional[int] = None,
    sme_emphasis: Optional[str] = None,
) -> None:
    """Background entry point: write the blueprint into a reserved row.

    Opens its OWN session, because the request that scheduled this has already
    returned and closed its own. Terminal state is written to the blueprint row
    (``generated`` / ``failed``), which is what the GET endpoint polls — so job
    state survives a restart and works with more than one worker, unlike an
    in-memory job dict.
    """
    db = SessionLocal()
    try:
        project = project_service.get_project(db, project_id)
        structure = audit_sheet_service.get_signed_off_structure(db, project_id)

        state = BlueprintState(
            project_id=project_id,
            title=project.book_title,
            description=project.book_description,
            target_audience=project.target_audience,
            chapter_count=project.chapter_count,
            project_metadata=project.to_dict(),
            sme_emphasis=sme_emphasis,
            audit_chapters=structure["chapters"],
            audit_sheet_version=structure["audit_sheet_version"],
        )
        context = BlueprintContext(
            db=db,
            prompt_service=build_prompt_service(db),
            top_k=settings.blueprint_top_k,
            created_by=created_by,
        )
        final_state = blueprint_orchestrator.generate(state, context=context)

        violation = final_state.metadata.get("policy_violation")
        if violation:
            _fail_blueprint(
                db,
                blueprint_id,
                project_id,
                "Policy violated. Guardrail blocked: "
                + ", ".join(violation.get("rules", [])),
            )
            return

        if final_state.status == WorkflowStatus.FAILED or not final_state.chapters:
            _fail_blueprint(
                db,
                blueprint_id,
                project_id,
                "; ".join(final_state.errors) or "Generation produced no chapters",
            )
            return

        review = final_state.metadata.get("review", {})
        blueprint_json = {
            "title": final_state.title,
            "description": final_state.description,
            "target_audience": final_state.target_audience,
            "estimated_length": final_state.estimated_length,
            "audit_sheet_version": final_state.audit_sheet_version,
            # Units are Parts of the book; chapters live inside them. Grouped from
            # the signed-off structure, not re-derived by the model.
            "units": _group_into_units(final_state.chapters),
            # Reported, not hidden: chapters with no source material behind them.
            "ungrounded_chapters": final_state.ungrounded_chapters,
            "chapter_count": len(final_state.chapters),
        }
        blueprint = blueprint_service.get_blueprint(db, blueprint_id)
        if blueprint is not None:
            blueprint.blueprint_json = blueprint_json
            blueprint.title = final_state.title
            blueprint.description = final_state.description
            blueprint.status = "approved" if review.get("approved") else "generated"
            db.commit()

        project_service.set_status(db, project_id, "blueprint_ready")
        logger.info(
            "Blueprint written | project=%s blueprint=%s chapters=%s ungrounded=%s",
            project_id,
            blueprint_id,
            len(final_state.chapters),
            len(final_state.ungrounded_chapters),
        )
    except Exception as exc:  # noqa: BLE001 - a background job must not vanish
        logger.error(
            "Blueprint job failed | project=%s blueprint=%s: %s",
            project_id,
            blueprint_id,
            exc,
            exc_info=True,
        )
        try:
            _fail_blueprint(db, blueprint_id, project_id, str(exc))
        except Exception:  # noqa: BLE001 - best effort
            logger.error("Could not record blueprint failure", exc_info=True)
    finally:
        db.close()


def _fail_blueprint(
    db: Session, blueprint_id: int, project_id: int, error: str
) -> None:
    """Record a failed run on the blueprint row and the project status."""
    blueprint = blueprint_service.get_blueprint(db, blueprint_id)
    if blueprint is not None:
        payload = dict(blueprint.blueprint_json or {})
        payload["status"] = "failed"
        payload["error"] = error
        blueprint.blueprint_json = payload
        blueprint.status = "failed"
        db.commit()
    try:
        project_service.set_status(db, project_id, "failed")
    except Exception:  # noqa: BLE001 - status machine may refuse; the row is truth
        logger.warning("Could not set project %s to failed", project_id)


def _group_into_units(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group written chapters under their units, preserving first-seen order."""
    units: List[Dict[str, Any]] = []
    index: Dict[Any, Dict[str, Any]] = {}
    for chapter in chapters:
        key = (chapter.get("unit_number"), chapter.get("unit"))
        if key not in index:
            entry = {
                "unit_number": chapter.get("unit_number"),
                "unit_title": chapter.get("unit"),
                "section": chapter.get("section"),
                "chapters": [],
            }
            index[key] = entry
            units.append(entry)
        index[key]["chapters"].append(
            {k: v for k, v in chapter.items() if k not in ("unit", "unit_number", "section")}
        )
    return units


def _summarize_blueprint(state: BlueprintState, record) -> Dict[str, Any]:
    return {
        "run_id": state.run_id,
        "project_id": state.project_id,
        "status": state.status.value,
        "blueprint_id": record.id if record else None,
        "version": record.version if record else None,
        "blueprint_status": record.status if record else None,
        "title": state.title,
        "chapters": len(state.chapters),
        "retrieved_chunks": len(state.retrieved_chunks),
        "review": state.metadata.get("review"),
        "errors": state.errors,
    }
