"""Orchestrates Word remediation.

    validate original -> open DOCX once -> run each remediator -> save copy -> validate copy

The before/after validation is the source of truth: a rule is reported as fixed only when
the validator passes it on the saved copy, never because a remediator says it acted.
The input file is never modified.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from docx import Document

from src.modules.accessibility_word.engine.word_remediator.base_remediator import (
    BaseRemediator,
    FixStatus,
    RemediationContext,
    RemediationOptions,
    RemediatorResult,
)
from src.modules.accessibility_word.engine.word_remediator.heading_remediator import (
    HeadingRemediator,
)
from src.modules.accessibility_word.engine.word_remediator.image_remediator import ImageRemediator
from src.modules.accessibility_word.engine.word_remediator.metadata_remediator import (
    MetadataRemediator,
)
from src.modules.accessibility_word.engine.word_remediator.table_remediator import TableRemediator
from src.modules.accessibility_word.engine.word_validator.metadata_analyzer import _LANGUAGE_TAG
from src.modules.accessibility_word.engine.word_validator.word_validation_orchestrator import (
    WordValidationOrchestrator,
)
from src.modules.accessibility_word.models.finding_models import CheckStatus

logger = logging.getLogger(__name__)


class RemediationOutcome:
    FIXED = "fixed"
    PARTIALLY_FIXED = "partially_fixed"
    FAILED_TO_FIX = "failed_to_fix"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    NO_ISSUE = "no_issue"
    REGRESSED = "regressed"
    NOT_EVALUATED = "not_evaluated"


class WordRemediationOrchestrator:

    def __init__(self,
                 remediators: list[BaseRemediator] | None = None,
                 validator: WordValidationOrchestrator | None = None,
                 options: RemediationOptions | None = None):
        
        self.options = options or RemediationOptions()
        
        if not _LANGUAGE_TAG.match(self.options.default_language):
            raise ValueError(f"Invalid default language: {self.options.default_language}")
        
        self.validator = validator or WordValidationOrchestrator()
        
        self.remediators = remediators if remediators is not None else [
            MetadataRemediator(),
            HeadingRemediator(),
            TableRemediator(),
            ImageRemediator(),
        ]

    def remediate(self, 
                  file_path: str, 
                  output_path: str | None = None,
                  document_name: str | None = None, 
                  organization_id: int | None = None,
                  project_id: str | None = None) -> dict[str, Any]:
        
        started = time.perf_counter()
        
        source = Path(file_path)
        name = document_name or source.name
        target = Path(output_path) if output_path else source.with_name(f"{source.stem}_remediated.docx")
        
        if target.resolve() == source.resolve():
            raise ValueError("output_path must differ from the input file")

        report: dict[str, Any] = {
            "status": "failed", "document_name": name, "organization_id": organization_id,
            "project_id": project_id, "remediated_path": None, "errors": [],
        }

        try:
            before = self.validator.validate(str(source), organization_id=organization_id,
                                             project_id=project_id, document_name=name)
        except ValueError as exc:
            report["errors"].append(f"The document cannot be remediated: {exc}")
            return report

        failing = {rule_id for rule_id, check in _checks(before).items()
                   if check["status"] == CheckStatus.FAIL}
        try:
            document = Document(str(source))
        except Exception as exc:
            report["errors"].append(f"The document could not be opened for editing: {exc}")
            return report

        ctx = RemediationContext(document, name, failing, self.options)
        remediator_results = [self._run(remediator, ctx) for remediator in self.remediators]

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            ctx.document.save(str(target))
            after = self.validator.validate(str(target), organization_id=organization_id,
                                            project_id=project_id, document_name=name)
        except Exception as exc:
            logger.exception("Saving or re-validating the remediated copy failed")
            target.unlink(missing_ok=True)
            report["errors"].append(f"The remediated copy could not be produced: {exc}")
            return report

        results = self._compare(before, after, remediator_results)
        errors = [e for r in remediator_results for e in r.errors]
        by_outcome = lambda *o: [r for r in results if r["remediation_outcome"] in o]
        fixed = by_outcome(RemediationOutcome.FIXED)

        failed = by_outcome(RemediationOutcome.FAILED_TO_FIX,
                            RemediationOutcome.PARTIALLY_FIXED,
                            RemediationOutcome.REGRESSED)

        report.update({
            "status": "completed_with_errors" if errors else "completed",
            "remediated_path": str(target),
            "errors": errors,
            "summary": {
                "score_before": before["accessibility_score"]["score"],
                "score_after": after["accessibility_score"]["score"],
                "issues_before": before["summary"]["failed"],
                "issues_fixed": len(fixed),
                "issues_failed": len(failed),
                "issues_remaining": after["summary"]["failed"],
                "manual_review_required": len(by_outcome(RemediationOutcome.MANUAL_REVIEW_REQUIRED)),
                "regressions": len(by_outcome(RemediationOutcome.REGRESSED)),
                "changes_to_review": sum(a["review_recommended"] for r in results for a in r["actions"]),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
            "issues_fixed": fixed,
            "issues_failed": failed,
            "remediation_results": results,
            "remediator_results": [r.to_dict() for r in remediator_results],
            "validation_before": before,
            "validation_after": after,
        })
        return report

    @staticmethod
    def _run(remediator: BaseRemediator, 
             ctx: RemediationContext) -> RemediatorResult:
        
        """The last line of isolation: a crashing remediator leaves the document as it found it."""
        
        if not remediator.handles(ctx.failing_rules):
            return RemediatorResult(remediator=remediator.name)
        snapshot = ctx.snapshot()
        try:
            return remediator.remediate(ctx)
        except Exception as exc:
            logger.exception("%s crashed", remediator.name)
            ctx.restore(snapshot)
            return RemediatorResult(
                remediator=remediator.name, status="failed",
                errors=[f"{type(exc).__name__}: {exc}"],
                fixes={rule_id: {"status": FixStatus.ERROR, "reason": str(exc), "actions": 0}
                       for rule_id in remediator.fixes if rule_id in ctx.failing_rules})

    @staticmethod
    def _compare(before: dict,
                 after: dict,
                 remediator_results: list[RemediatorResult]) -> list[dict]:
        
        checks_before, checks_after = _checks(before), _checks(after)
        fix_info: dict[str, dict] = {}
        actions: dict[str, list] = {}
        for result in remediator_results:
            for rule_id, info in result.fixes.items():
                # Two rules can share one fix; an applied status wins over no_change.
                if rule_id not in fix_info or info["status"] == FixStatus.APPLIED:
                    fix_info[rule_id] = {**info, "remediator": result.remediator}
            for action in result.actions:
                actions.setdefault(action.rule_id, []).append(action.to_dict())

        results = []
        for rule_id, b in checks_before.items():
            a = checks_after.get(rule_id, {"status": CheckStatus.NOT_EVALUATED, "affected_count": 0})
            info = fix_info.get(rule_id, {})
            results.append({
                "rule_id": rule_id,
                "title": b["title"],
                "severity": b["severity"],
                "category": b["category"],
                "status_before": b["status"],
                "status_after": a["status"],
                "affected_before": b["affected_count"],
                "affected_after": a["affected_count"],
                "remediation_outcome": _outcome(b, a, info.get("status")),
                "remediator": info.get("remediator"),
                "fix_status": info.get("status"),
                "reason": info.get("reason"),
                "actions": actions.get(rule_id, []),
            })
        return results


def _checks(report: dict) -> dict[str, dict]:
    return {check["rule_id"]: {**check, "category": category}
            for category, result in report["findings_by_category"].items()
            for check in result["checks"]}


def _outcome(before: dict,
             after: dict,
             fix_status: str | None) -> str:
    
    b, a = before["status"], after["status"]
    
    resolved = (CheckStatus.PASS, CheckStatus.NOT_APPLICABLE)
    
    if CheckStatus.NOT_EVALUATED in (b, a):
        return RemediationOutcome.NOT_EVALUATED
    
    if b == CheckStatus.FAIL:
        if a in resolved:
            return RemediationOutcome.FIXED
        if a != CheckStatus.FAIL:
            return RemediationOutcome.MANUAL_REVIEW_REQUIRED
        if fix_status == FixStatus.APPLIED:
            return RemediationOutcome.PARTIALLY_FIXED \
                if after["affected_count"] < before["affected_count"] else RemediationOutcome.FAILED_TO_FIX
        if fix_status == FixStatus.ERROR:
            return RemediationOutcome.FAILED_TO_FIX
        return RemediationOutcome.MANUAL_REVIEW_REQUIRED
    
    if a == CheckStatus.FAIL:
        return RemediationOutcome.REGRESSED
    
    if a in CheckStatus.MANUAL_PENDING:
        return RemediationOutcome.MANUAL_REVIEW_REQUIRED
    return RemediationOutcome.NO_ISSUE
