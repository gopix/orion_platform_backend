"""Chunking utilities — stateless, pure helpers shared by every strategy.

Strategies depend on these; these depend on nothing but the data models. No
orchestration (factory/service), no strategy logic, no embeddings, no I/O.
"""
from src.modules.book_forge.ai.foundation.chunking.utils.chunk_statistics import (
    ChunkStatisticsCalculator,
)
from src.modules.book_forge.ai.foundation.chunking.utils.heading_detector import (
    Heading,
    HeadingDetector,
)
from src.modules.book_forge.ai.foundation.chunking.utils.paragraph_extractor import (
    ParagraphExtractor,
)
from src.modules.book_forge.ai.foundation.chunking.utils.sentence_extractor import (
    SentenceExtractor,
)
from src.modules.book_forge.ai.foundation.chunking.utils.text_normalizer import TextNormalizer
from src.modules.book_forge.ai.foundation.chunking.utils.token_estimator import (
    CHARS_PER_TOKEN,
    TokenEstimator,
)

__all__ = [
    "ChunkStatisticsCalculator",
    "Heading",
    "HeadingDetector",
    "ParagraphExtractor",
    "SentenceExtractor",
    "TextNormalizer",
    "TokenEstimator",
    "CHARS_PER_TOKEN",
]
