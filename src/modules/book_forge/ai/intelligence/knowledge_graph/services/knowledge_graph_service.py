"""Knowledge graph orchestration service.

The single entry point for turning a parsed document into a knowledge graph:

    ParsedDocument -> validate -> extract -> build -> validate graph -> persist
    -> KnowledgeGraph

The service owns orchestration only. Extraction, assembly, validation, and
persistence each live in their own collaborators (all injectable), so the service
never knows *how* entities are found or *where* the graph is stored.
"""
import time
from typing import Any, List, Optional

from src.core.logger import get_logger
from src.modules.book_forge.ai.intelligence.knowledge_graph.builders import (
    GraphBuilder,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions import (
    EntityExtractionException,
    KnowledgeGraphException,
    RelationshipExtractionException,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.extractors import (
    ConceptExtractor,
    EntityExtractor,
    RelationshipExtractor,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    KnowledgeGraph,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.repositories import (
    BaseGraphRepository,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.validators import (
    GraphValidator,
)

logger = get_logger(__name__)


class KnowledgeGraphService:
    """Builds (and optionally persists) a knowledge graph from a document."""

    def __init__(
        self,
        *,
        entity_extractor: Optional[EntityExtractor] = None,
        concept_extractor: Optional[ConceptExtractor] = None,
        relationship_extractor: Optional[RelationshipExtractor] = None,
        builder: Optional[GraphBuilder] = None,
        validator: Optional[GraphValidator] = None,
        repository: Optional[BaseGraphRepository] = None,
    ) -> None:
        self._entities = entity_extractor or EntityExtractor()
        self._concepts = concept_extractor or ConceptExtractor()
        self._relationships = relationship_extractor or RelationshipExtractor()
        self._builder = builder or GraphBuilder()
        self._validator = validator or GraphValidator()
        self._repository = repository

    def build_from_document(
        self,
        document: Any,
        *,
        graph_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        allow_cycles: bool = True,
        persist: bool = False,
    ) -> KnowledgeGraph:
        """Run the full pipeline and return the resulting ``KnowledgeGraph``.

        Persists via the repository when ``persist`` is true and a ``graph_id`` is
        given.
        """
        start = time.perf_counter()
        graph: Optional[KnowledgeGraph] = None
        error: Optional[BaseException] = None
        try:
            # 1) Validate the source document up front.
            self._validator.validate(KnowledgeGraph(), document=document)

            # 2) Extract entities, concepts, relationships from the text.
            text = self._collect_text(document)
            entities = self._extract_entities(text)
            concepts = self._extract_concepts(text)
            labels = [n.label for n in entities] + [n.label for n in concepts]
            relationships = self._extract_relationships(text, labels)

            # 3) Assemble the graph.
            graph = self._builder.build(
                entities=entities,
                concepts=concepts,
                relationships=relationships,
                metadata=self._metadata(document, metadata),
            )

            # 4) Validate the built graph.
            self._validator.validate(
                graph, document=document, allow_cycles=allow_cycles
            )

            # 5) Persist if requested.
            if persist and graph_id:
                self.save(graph_id, graph)

            return graph
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log(graph_id, graph, duration_ms, error, persisted=persist)

    # -- persistence delegation (service doesn't care about the backend) ---

    def save(self, graph_id: str, graph: KnowledgeGraph) -> str:
        """Persist ``graph`` under ``graph_id`` via the configured repository."""
        return self._require_repository().save(graph_id, graph)

    def load(self, graph_id: str) -> KnowledgeGraph:
        """Load a stored graph by id via the configured repository."""
        return self._require_repository().load(graph_id)

    def _require_repository(self) -> BaseGraphRepository:
        if self._repository is None:
            raise KnowledgeGraphException("No graph repository configured.")
        return self._repository

    # -- extraction (wrapped in domain errors) -----------------------------

    def _extract_entities(self, text: str):
        try:
            return self._entities.extract(text)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise EntityExtractionException(
                f"Entity extraction failed: {exc}", cause=exc
            )

    def _extract_concepts(self, text: str):
        try:
            return self._concepts.extract(text)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise EntityExtractionException(
                f"Concept extraction failed: {exc}", cause=exc
            )

    def _extract_relationships(self, text: str, labels: List[str]):
        try:
            return self._relationships.extract(text, node_labels=labels)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise RelationshipExtractionException(
                f"Relationship extraction failed: {exc}", cause=exc
            )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _collect_text(document: Any) -> str:
        """Gather all text from a document's flat paragraphs and section tree."""
        parts: List[str] = [p.text for p in getattr(document, "paragraphs", []) or []]

        def walk(sections) -> None:
            for section in sections or []:
                if getattr(section, "title", None):
                    parts.append(section.title)
                parts.extend(p.text for p in section.paragraphs)
                walk(section.subsections)

        walk(getattr(document, "sections", []))
        return "\n".join(parts)

    @staticmethod
    def _metadata(document: Any, extra: Optional[dict]) -> dict:
        meta: dict = {}
        title = getattr(document, "title", None)
        if title:
            meta["title"] = title
        doc_meta = getattr(document, "metadata", None)
        filename = getattr(doc_meta, "filename", None) if doc_meta else None
        if filename:
            meta["source"] = filename
        if extra:
            meta.update(extra)
        return meta

    def _log(
        self,
        graph_id: Optional[str],
        graph: Optional[KnowledgeGraph],
        duration_ms: float,
        error: Optional[BaseException],
        persisted: bool,
    ) -> None:
        success = error is None
        nodes = len(graph.nodes) if graph is not None else 0
        edges = len(graph.edges) if graph is not None else 0
        log = logger.info if success else logger.error
        log(
            "KnowledgeGraph build | graph_id=%s | nodes=%s edges=%s persisted=%s | "
            "duration_ms=%.1f | success=%s%s",
            graph_id,
            nodes,
            edges,
            persisted and graph_id is not None,
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
knowledge_graph_service = KnowledgeGraphService()
