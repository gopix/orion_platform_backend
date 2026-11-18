"""MetadataBuilder — build the metadata payload stored alongside each vector.

Every vector should carry consistent metadata so it can be filtered and traced
later (which project/document/chunk it came from, where in the book it sits)::

    {
        "project_id": 101,
        "document_id": 25,
        "chunk_id": 8,
        "chapter": "Chapter 3",
        "section": "3.2",
        "page": 17,
    }

Centralising construction here means the payload is shaped the same way
everywhere, instead of being assembled ad hoc at each call site. ``None`` values
are omitted by default — many vector databases reject null metadata values.
Stateless and pure: no I/O, no configuration.
"""
from typing import Any, Dict, Optional


class MetadataBuilder:
    """Construct consistent per-vector metadata payloads."""

    @staticmethod
    def build(
        *,
        project_id: Optional[int] = None,
        document_id: Optional[int] = None,
        chunk_id: Optional[int] = None,
        chapter: Optional[str] = None,
        section: Optional[str] = None,
        page: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
        include_none: bool = False,
    ) -> Dict[str, Any]:
        """Assemble a metadata dict from explicit fields.

        ``extra`` is merged in for caller-specific keys. By default keys whose
        value is ``None`` are dropped; set ``include_none=True`` to keep them.
        """
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "document_id": document_id,
            "chunk_id": chunk_id,
            "chapter": chapter,
            "section": section,
            "page": page,
        }
        if extra:
            payload.update(extra)
        if include_none:
            return payload
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def from_chunk(
        chunk: Any,
        *,
        project_id: Optional[int] = None,
        document_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
        include_none: bool = False,
    ) -> Dict[str, Any]:
        """Build metadata from a ``Chunk`` (heading -> chapter, etc.).

        Explicit ``project_id`` / ``document_id`` win over the chunk's own values.
        """
        page = chunk.page_number
        if page is None and getattr(chunk, "metadata", None) is not None:
            page = getattr(chunk.metadata, "page_number", None)

        return MetadataBuilder.build(
            project_id=project_id if project_id is not None else chunk.project_id,
            document_id=document_id if document_id is not None else chunk.document_id,
            chunk_id=chunk.id,
            chapter=chunk.heading,
            section=chunk.section,
            page=page,
            extra=extra,
            include_none=include_none,
        )

    @staticmethod
    def from_vector(
        vector: Any,
        *,
        project_id: Optional[int] = None,
        document_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
        include_none: bool = False,
    ) -> Dict[str, Any]:
        """Build metadata from an ``EmbeddingVector`` at store time.

        Reads the locating context the provider copied into ``vector.metadata``
        (heading/section/page_number).
        """
        meta = vector.metadata or {}
        return MetadataBuilder.build(
            project_id=project_id,
            document_id=document_id,
            chunk_id=vector.chunk_id,
            chapter=meta.get("heading"),
            section=meta.get("section"),
            page=meta.get("page_number"),
            extra=extra,
            include_none=include_none,
        )
