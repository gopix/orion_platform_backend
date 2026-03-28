from typing import Any, List, Optional
from pydantic import BaseModel, Field


class APIResponse(BaseModel):
    status_code: int
    message: str
    data: Optional[Any] = None
    errors: List[Any] = Field(default_factory=list)


def build_response(
    status_code: int,
    message: str,
    data: Any = None,
    errors: List[Any] = None
):
    return APIResponse(
        status_code=status_code,
        message=message,
        data=data,
        errors=errors or []
    )