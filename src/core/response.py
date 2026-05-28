from typing import Any, List, Optional
from pydantic import BaseModel, Field


class APIResponse(BaseModel):
    response_code: int
    message: str
    data: Optional[Any] = None
    errors: List[Any] = Field(default_factory=list)


def build_response(
    response_code: int,
    message: str,
    data: Any = None,
    errors: List[Any] = None
):
    return APIResponse(
        response_code=response_code,
        message=message,
        data=data,
        errors=errors or []
    )