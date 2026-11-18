"""
accessibility_score_agent.py
============================
AccessibilityScoreAgent — turns the findings of every OTHER agent into an
overall accessibility score plus a per-category breakdown, e.g.

    Overall 87%  |  Structure 95, Text 90, Images 60, Tables 100, Contrast 88,
                    Links 75, Metadata 80

This agent does not look at slides. It reads the accumulated ValidationIssues
the orchestrator collects from all prior agents and places in
``context["issues"]`` (a list of ValidationIssue objects OR plain dicts), then
scores them. It therefore MUST run last.

Scoring model
-------------
Each scored check retains a fraction of its points based on status + severity:

    PASS                      -> 1.00
    WARNING  LOW/MED/HIGH/CRIT -> 0.90 / 0.75 / 0.60 / 0.50
    FAIL     LOW/MED/HIGH/CRIT -> 0.60 / 0.35 / 0.15 / 0.00

INFO and internal-only checks (e.g. "insufficient data") are advisory and are
excluded from scoring, so an unverifiable item never silently lowers the score.

    category score = mean(retained fraction of that category's checks) * 100
    overall score  = mean(retained fraction of ALL scored checks) * 100

The orchestrator can call ``AccessibilityScoreAgent.compute_scores(issues)``
directly to embed the scores in the report, independent of the check framework.
"""
from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)

# Retained fraction of points per (status, severity).
_RETAIN = {
    ("WARNING", "LOW"): 0.90, ("WARNING", "MEDIUM"): 0.75,
    ("WARNING", "HIGH"): 0.60, ("WARNING", "CRITICAL"): 0.50,
    ("FAIL", "LOW"): 0.60, ("FAIL", "MEDIUM"): 0.35,
    ("FAIL", "HIGH"): 0.15, ("FAIL", "CRITICAL"): 0.00,
}


def _field(issue: Any, name: str):
    if isinstance(issue, dict):
        return issue.get(name)
    return getattr(issue, name, None)


def _band(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs work"
    return "Poor"


class AccessibilityScoreAgent(BasePPTAccessibilityValidatorAgent):
    """Aggregate every agent's findings into an accessibility score."""

    agent_code = "PPT_SCORE_AGENT"
    agent_name = "PPT Accessibility Score Agent"
    category = "Score"
    supported_checks = {"PPT-SCORE-001"}

    # ---------------------------------------------------------------- scoring
    @staticmethod
    def _retain(status: str, severity: str) -> float | None:
        """Retained fraction for one check, or None if it should not be scored."""
        status = (status or "").upper()
        severity = (severity or "MEDIUM").upper()
        if status == "PASS":
            return 1.0
        if status in ("INFO", ""):
            return None                      # advisory -> not scored
        return _RETAIN.get((status, severity), 0.5)

    @classmethod
    def compute_scores(cls, issues: list[Any]) -> dict[str, Any]:
        """Overall + per-category scores from a list of ValidationIssues/dicts."""
        cat_fracs: dict[str, list[float]] = {}
        all_fracs: list[float] = []
        counts = {"PASS": 0, "FAIL": 0, "WARNING": 0, "INFO": 0}

        for it in issues or []:
            if _field(it, "internal_check"):
                continue                     # skip internal/insufficient-data checks
            status = (_field(it, "status") or "").upper()
            if status in counts:
                counts[status] += 1
            frac = cls._retain(status, _field(it, "severity"))
            if frac is None:
                continue
            category = (_field(it, "category") or "General").strip() or "General"
            cat_fracs.setdefault(category, []).append(frac)
            all_fracs.append(frac)

        categories = {c: round(100.0 * sum(v) / len(v)) for c, v in cat_fracs.items() if v}
        overall = round(100.0 * sum(all_fracs) / len(all_fracs)) if all_fracs else 100
        return {
            "overall": overall,
            "band": _band(overall),
            "categories": dict(sorted(categories.items())),
            "counts": {k.lower(): v for k, v in counts.items()},
            "scored_checks": len(all_fracs),
        }

    # ---------------------------------------------------------------- framework
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        if check_code != "PPT-SCORE-001":
            return self._issue("INFO", "LOW", check_code,
                               f"Check {check_code} is not implemented yet",
                               "Implement the requested score check", internal=True)

        issues = context.get("issues")
        if not isinstance(issues, list):
            issues = context.get("all_issues") or []
        scores = self.compute_scores(issues)
        context["accessibility_score"] = scores       # expose for the report

        cat_str = ", ".join(f"{c} {s}" for c, s in scores["categories"].items())
        message = (f"Overall accessibility score: {scores['overall']}% "
                   f"({scores['band']})"
                   + (f" | {cat_str}" if cat_str else ""))
        # PASS if strong, WARNING if weak — but never FAIL (a score is a summary).
        status = "PASS" if scores["overall"] >= 75 else "WARNING"
        severity = "LOW" if scores["overall"] >= 75 else "MEDIUM"
        return self._issue(status, severity, "PPT-SCORE-001", message,
                           "Address the FAIL/WARNING findings above to raise the "
                           "score, focusing on the lowest-scoring categories.",
                           internal=False)

    def _issue(self, status, severity, rule_id, message, recommendation,
               internal=False) -> ValidationIssue:
        return ValidationIssue(
            agent_name=self.agent_name, rule_id=rule_id, category=self.category,
            severity=severity, page_no=None, message=message,
            recommendation=recommendation, auto_fixable=False,
            status=status, internal_check=internal,
        )
