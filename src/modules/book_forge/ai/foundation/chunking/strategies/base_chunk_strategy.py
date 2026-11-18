"""BaseChunkStrategy — the contract every chunking strategy implements.

This is the Strategy pattern's abstract base. Each concrete strategy (fixed,
paragraph, heading, semantic, ...) implements the same ``chunk`` method, so the
engine can swap strategies freely and treat them interchangeably — it depends on
this interface, never on a concrete implementation. Contract only — no chunking
logic lives here.
"""
from abc import ABC, abstractmethod

from src.modules.book_forge.ai.foundation.chunking.models.chunk_request import ChunkRequest
from src.modules.book_forge.ai.foundation.chunking.models.chunk_result import ChunkResult


class BaseChunkStrategy(ABC):
    @abstractmethod
    def chunk(self, request: ChunkRequest) -> ChunkResult:
        """Split ``request.document`` into chunks and return the result.

        Concrete strategies read the document and its tuning parameters from the
        ``request`` and return a ``ChunkResult`` bundling the produced chunks
        with statistics and any warnings.
        """
        raise NotImplementedError
