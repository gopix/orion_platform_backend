"""SentenceExtractor — split text into sentences.

Future-proofing for semantic chunking: comparing the similarity of adjacent
sentences to find topic shifts needs the sentences first. Providing it now means
the semantic strategy (and anything else) can rely on it existing.

The splitter is a lightweight boundary heuristic (end punctuation followed by
whitespace), not a full NLP sentence tokenizer — abbreviations like "Dr." may
over-split. That is an acceptable trade for a pure, dependency-free helper.
Stateless and pure: no I/O, no configuration.
"""
import re
from typing import List

# Split after ., ! or ? when followed by whitespace (covers line breaks too).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class SentenceExtractor:
    """Extract sentences from a block of text."""

    @staticmethod
    def extract(text: str) -> List[str]:
        """Return the sentences of ``text`` in order.

        Each returned sentence has its internal whitespace (including stray line
        breaks) collapsed to single spaces.
        """
        if not text or not text.strip():
            return []
        sentences = _SENTENCE_SPLIT_RE.split(text)
        return [" ".join(s.split()) for s in sentences if s.strip()]
