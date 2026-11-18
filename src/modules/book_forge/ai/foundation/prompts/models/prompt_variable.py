"""PromptVariable — a declared input to a prompt.

Storing variables (rather than discovering them at runtime) makes UI generation
and validation straightforward.
"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class VariableType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"


class PromptVariable(BaseModel):
    id: Optional[int] = None
    template_id: Optional[int] = None
    name: str
    type: VariableType = VariableType.STRING
    required: bool = True
    default_value: Optional[Any] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}
