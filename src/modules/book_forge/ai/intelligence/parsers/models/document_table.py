"""DocumentTable — a table extracted from a document.

Stored as a grid of cell strings plus an optional header row and caption.
``row_count`` / ``column_count`` are derived so they can't drift from the data.
Data model only — no behaviour.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field


class DocumentTable(BaseModel):
    # Row-major grid of cell text; each inner list is one row.
    rows: List[List[str]] = Field(default_factory=list)
    # Optional header row (column titles), separate from body rows.
    header: Optional[List[str]] = None
    caption: Optional[str] = None
    page_number: Optional[int] = None
    order: Optional[int] = None

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def row_count(self) -> int:
        return len(self.rows)

    @computed_field
    @property
    def column_count(self) -> int:
        if self.header:
            return len(self.header)
        return max((len(row) for row in self.rows), default=0)
