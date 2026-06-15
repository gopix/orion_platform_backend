from dataclasses import dataclass, field

from src.modules.accessibility_plus.models.validation_issue import ValidationIssue

@dataclass
class ValidationResult:

    document_name: str

    total_pages: int

    execution_time_ms: int

    total_issues: int

    critical_count: int

    high_count: int

    medium_count: int

    low_count: int

    auto_fixable_count: int

    manual_review_count: int

    ai_review_count: int

    overall_status: str

    issues: list[ValidationIssue]