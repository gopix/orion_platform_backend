"""Step 9: apply the catalog to analyzer output and classify it."""
from __future__ import annotations

from dataclasses import replace

from src.modules.accessibility_word.engine.word_validator.rule_catalog import (
    RuleCatalog,
    load_catalog,
)
from src.modules.accessibility_word.models.audit_models import AnalyzerResult, RuleEvaluation
from src.modules.accessibility_word.models.finding_models import Severity


class WordAccessibilityRuleEngine:
    def __init__(self, catalog: RuleCatalog | None = None):
        self.catalog = catalog or load_catalog()

    def evaluate(self, analysis_results: list[AnalyzerResult]) -> RuleEvaluation:
        """Removes disabled rules, then orders findings by severity."""
        filtered = [self._apply(result) for result in analysis_results]
        checks = [check for result in filtered for check in result.checks]
        findings = [finding for result in filtered for finding in result.findings]
        rank = {severity: index for index, severity in enumerate(Severity.ORDER)}
        findings.sort(key=lambda f: (rank[f.severity], f.rule_id))
        return RuleEvaluation(analyzer_results=filtered, checks=checks, findings=findings)

    def _apply(self, result: AnalyzerResult) -> AnalyzerResult:
        enabled = {r.rule_id for r in self.catalog.for_analyzer(result.analyzer) if r.enabled}
        return replace(
            result,
            checks=[c for c in result.checks if c.rule_id in enabled],
            findings=[f for f in result.findings if f.rule_id in enabled],
        )
