"""Step 11: the consolidated audit report."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.modules.accessibility_word.engine.word_validator.rule_catalog import (
    RuleCatalog,
    load_catalog,
)
from src.modules.accessibility_word.models.audit_models import RuleEvaluation
from src.modules.accessibility_word.models.document_context import DocumentContext
from src.modules.accessibility_word.models.finding_models import (
    AnalyzerStatus,
    CheckStatus,
    Severity,
)

REPORT_VERSION = "1.0"
_SAMPLE_LOCATIONS = 5


class WordAccessibilityReportGenerator:
    def __init__(self, catalog: RuleCatalog | None = None):
        self.catalog = catalog or load_catalog()

    def generate(self, document_context: DocumentContext, evaluation: RuleEvaluation,
                 scoring_result: dict[str, Any]) -> dict[str, Any]:
        analyzers = evaluation.analyzer_results
        degraded = [a for a in analyzers if a.status != AnalyzerStatus.COMPLETED]
        score = {k: v for k, v in scoring_result.items() if k != "summary"}
        return {
            "report_version": REPORT_VERSION,
            "rules_version": self.catalog.version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "completed_with_errors" if degraded else "completed",
            "document_name": document_context.file_name,
            "document": self._document(document_context),
            "accessibility_score": score,
            "summary": scoring_result["summary"],
            "analyzer_status": [
                {"analyzer": a.analyzer, "status": a.status, "errors": a.errors,
                 "duration_ms": a.duration_ms} for a in analyzers],
            "findings_by_category": {a.category: a.to_dict() for a in analyzers},
            "severity_distribution": self._severity_distribution(evaluation),
            "manual_validation_pending": self._manual_pending(evaluation),
            "remediation_recommendations": self._recommendations(evaluation),
        }

    @staticmethod
    def _document(ctx: DocumentContext) -> dict[str, Any]:
        meta = ctx.metadata
        return {
            "name": ctx.file_name,
            "size_bytes": ctx.file_size,
            "sha256": ctx.sha256,
            "title": meta.title,
            "author": meta.author,
            "language": meta.default_language,
            "application": meta.application,
            "pages_reported": meta.pages_reported,
            "word_count": ctx.word_count,
            "paragraphs": len(ctx.paragraphs),
            "headings": len(ctx.headings),
            "tables": len(ctx.tables),
            "images": len(ctx.images),
            "text_boxes": len(ctx.text_boxes),
            "hyperlinks": len(ctx.hyperlinks),
            "parse_warnings": ctx.failed_parts,
        }

    @staticmethod
    def _severity_distribution(evaluation: RuleEvaluation) -> dict[str, dict[str, int]]:
        """Failed checks and their exact occurrences, including any capped from the findings list."""
        distribution = {s: {"failed_checks": 0, "occurrences": 0} for s in Severity.ORDER}
        for check in evaluation.checks:
            if check.status == CheckStatus.FAIL:
                distribution[check.severity]["failed_checks"] += 1
                distribution[check.severity]["occurrences"] += check.affected_count
        return distribution

    @staticmethod
    def _manual_pending(evaluation: RuleEvaluation) -> list[dict[str, Any]]:
        return [check.to_dict() for check in evaluation.checks
                if check.status in CheckStatus.MANUAL_PENDING]

    def _recommendations(self, evaluation: RuleEvaluation) -> list[dict[str, Any]]:
        rank = {severity: index for index, severity in enumerate(Severity.ORDER)}
        failed = sorted((c for c in evaluation.checks if c.status == CheckStatus.FAIL),
                        key=lambda c: (rank[c.severity], -c.affected_count, c.rule_id))
        result = []
        for check in failed:
            rule = self.catalog.get(check.rule_id)
            occurrences = [f for f in evaluation.findings if f.rule_id == check.rule_id]
            result.append({
                "rule_id": check.rule_id,
                "title": check.title,
                "severity": check.severity,
                "wcag": list(rule.wcag),
                "affected_count": check.affected_count,
                "recommendation": rule.recommendation,
                "sample_locations": [f.location for f in occurrences[:_SAMPLE_LOCATIONS]],
            })
        return result
