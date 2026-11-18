from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIEnvelope(BaseModel, Generic[T]):
    """Typed version of src.core.response.APIResponse (same JSON shape)."""

    response_code: int
    message: str
    data: Optional[T] = None
    errors: List[Any] = Field(default_factory=list)


class PagedData(BaseModel, Generic[T]):
    total: int
    skip: int
    limit: int
    items: List[T]
