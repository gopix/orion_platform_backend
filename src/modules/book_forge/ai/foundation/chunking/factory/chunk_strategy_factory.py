"""Factory responsible for constructing chunking strategies.

Owns the strategy registry and knows how to build a concrete strategy from a
``ChunkStrategy`` selector. This mirrors the LLM module's ``LLMProviderFactory``:
it keeps strategy *creation* out of the service, so ``ChunkingService`` never
grows a ``if strategy == HEADING: ... elif ...`` ladder and never imports a
concrete strategy. Adding a future strategy (Markdown, HTML, TableAware, Code,
...) means registering it here — the service is untouched.
"""
from typing import Dict, List, Type, Union

from src.modules.book_forge.ai.foundation.chunking.exceptions import (
    InvalidChunkStrategyException,
)
from src.modules.book_forge.ai.foundation.chunking.models.chunk_request import ChunkStrategy
from src.modules.book_forge.ai.foundation.chunking.strategies import (
    BaseChunkStrategy,
    FixedChunkStrategy,
    HeadingChunkStrategy,
    ParagraphChunkStrategy,
    SemanticChunkStrategy,
)


class ChunkStrategyFactory:
    """Builds strategy instances from a ``ChunkStrategy`` selector."""

    _REGISTRY: Dict[ChunkStrategy, Type[BaseChunkStrategy]] = {
        ChunkStrategy.HEADING: HeadingChunkStrategy,
        ChunkStrategy.PARAGRAPH: ParagraphChunkStrategy,
        ChunkStrategy.FIXED: FixedChunkStrategy,
        ChunkStrategy.SEMANTIC: SemanticChunkStrategy,
    }

    @classmethod
    def get_strategy(cls, strategy: Union[ChunkStrategy, str]) -> BaseChunkStrategy:
        """Instantiate the strategy for ``strategy`` (enum or string).

        Raises ``InvalidChunkStrategyException`` if the value isn't a known
        strategy or has no registered implementation — an unresolvable strategy
        is a configuration error, not something to paper over by returning None.
        """
        try:
            key = ChunkStrategy.coerce(strategy)
        except ValueError as exc:
            # Not even a valid enum value (e.g. "AI_MAGIC").
            raise InvalidChunkStrategyException(
                strategy, supported=cls._supported_values(), cause=exc
            )

        strategy_cls = cls._REGISTRY.get(key)
        if strategy_cls is None:
            # Valid enum member but declared-without-implementation.
            raise InvalidChunkStrategyException(
                key.value, supported=cls._supported_values()
            )
        return strategy_cls()

    @classmethod
    def _supported_values(cls) -> List[str]:
        return [member.value for member in cls._REGISTRY]

    @classmethod
    def register(
        cls, strategy: Union[ChunkStrategy, str], strategy_cls: Type[BaseChunkStrategy]
    ) -> None:
        """Register or override the implementation for a strategy."""
        cls._REGISTRY[ChunkStrategy.coerce(strategy)] = strategy_cls

    @classmethod
    def available(cls) -> List[ChunkStrategy]:
        """Return the strategies this factory can build."""
        return list(cls._REGISTRY)
