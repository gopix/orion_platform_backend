from dataclasses import dataclass, field

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue

@dataclass
class ValidationResult:

    document_name: str

    total_pages: int

    execution_time_ms: int

    # Total checks executed (PASS + FAIL + WARNING + INFO)
    total_checks: int

    # Actionable issues only: FAIL + WARNING (excludes PASS)
    total_issues: int

    # Failure counts by severity — FAIL status only
    critical_count: int

    high_count: int

    medium_count: int

    low_count: int

    # Advisory warnings (WARNING status)
    warning_count: int

    # Among FAIL issues only
    auto_fixable_count: int

    manual_review_count: int

    # WARNING issues flagged for review
    ai_review_count: int

    overall_status: str

    # Only actionable issues (FAIL + WARNING); PASS details are in agent_results
    issues: list[ValidationIssue]