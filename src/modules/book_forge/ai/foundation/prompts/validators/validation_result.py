"""ValidationResult — the structured outcome of validation.

Validators return this instead of throwing on every failure, so the caller (the
service) can decide whether to stop or continue. ``is_valid`` is derived purely
from ``errors`` — warnings never invalidate a result.
"""
from typing import List

from pydantic import BaseModel, Field, computed_field


class ValidationResult(BaseModel):
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @computed_field  # serialized in model_dump()/JSON
    @property
    def is_valid(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Accumulate another result's errors and warnings into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self
