"""
report_builder.py
-----------------
Business logic for computing remediation report views and dashboard KPIs.

Kept here (engines layer) so the router stays thin — pure HTTP in, pure HTTP out.

Public API
----------
RemediationReportBuilder.compute_result_summary(issues, pipeline_summary)
RemediationReportBuilder.build_agent_results_view(initial_agent_results, revalidation_agent_results)
RemediationReportBuilder.compute_dashboard(job)
"""

from __future__ import annotations
from typing import Any


class RemediationReportBuilder:
    """
    Stateless helper — all methods are static.
    Instantiation is optional; class is used as a namespace.
    """

    # ── Severity weights for the accessibility score ──────────────────────────
    _SEVERITY_WEIGHT: dict[str, int] = {
        "CRITICAL": 4,
        "HIGH":     3,
        "MEDIUM":   2,
        "LOW":      1,
    }

    # ── Rules that directly map to PDF/UA conformance ─────────────────────────
    _PDFUA_RULES: set[str] = {
        "DOC_PDFUA_DECLARATION",   # /MarkInfo + XMP pdfuaid:part marker
        "DOC_IS_TAGGED",           # /MarkInfo Marked=true
        "DOC_HAS_LANGUAGE",        # /Lang entry on document or page
        "DOC_HAS_TITLE",           # /Title in document info dict
        "HDR-001",                 # At least one H1 heading
        "HDR-003",                 # Heading hierarchy is sequential
        "HDR-005",                 # H1-H6 have valid parent structure types
    }

    # ── WCAG risk level ordering ───────────────────────────────────────────────
    _WCAG_RISK_LEVEL: dict[str, int] = {
        "None": 0, "Low": 1, "Medium": 2, "High": 3,
    }

    # =========================================================================
    # compute_result_summary
    # =========================================================================

    @staticmethod
    def compute_result_summary(
        issues: dict,
        pipeline_summary: dict | None = None,
    ) -> dict[str, Any]:
        """
        Single source of truth for the remediation outcome.

        Merges issues-level outcome (which rules were fixed) with pipeline-level
        stats (timing, save_success, initial FAIL count) into one block.

        Field semantics
        ---------------
        issues_scanned     — total FAIL count before remediation
        auto_fixable_found — subset Orion was capable of fixing
        issues_fixed       — auto-fixable issues now PASS after revalidation
        issues_not_fixed   — auto-fixable issues still FAIL after revalidation
        issues_remaining   — ALL rules still FAIL after revalidation
        overall_status     — driven by issues_remaining (actual document state):
                               no_issues              — document was clean to start
                               fully_remediated       — zero FAILs remain
                               partially_remediated   — Orion fixed some; others remain
                               not_remediated         — Orion tried but nothing improved
                               manual_review_required — no auto-fixable; manual FAILs remain
        save_success       — whether the remediated PDF was saved
        total_duration_ms  — end-to-end pipeline duration
        """
        ps             = pipeline_summary or {}
        detected_list  = issues.get("detected", [])
        remaining_list = issues.get("remaining", [])
        failed_list    = issues.get("failed_to_fix", [])

        auto_fixable_ids = {
            d["rule_id"] for d in detected_list if d.get("auto_fixable") is True
        }
        remaining_ids = {r["rule_id"] for r in remaining_list}
        failed_ids    = {f["rule_id"] for f in failed_list}

        auto_fixable_found = len(auto_fixable_ids)
        issues_fixed       = len(auto_fixable_ids - remaining_ids - failed_ids)
        issues_not_fixed   = len(auto_fixable_ids & (remaining_ids | failed_ids))
        issues_remaining   = len(remaining_list)

        if auto_fixable_found == 0 and issues_remaining == 0:
            overall_status = "no_issues"
        elif auto_fixable_found == 0 and issues_remaining > 0:
            overall_status = "manual_review_required"
        elif issues_remaining == 0:
            overall_status = "fully_remediated"
        elif issues_fixed > 0:
            overall_status = "partially_remediated"
        else:
            overall_status = "not_remediated"

        return {
            "overall_status":     overall_status,
            "issues_scanned":     ps.get("initial_issues_found", len(detected_list)),
            "auto_fixable_found": auto_fixable_found,
            "issues_fixed":       issues_fixed,
            "issues_not_fixed":   issues_not_fixed,
            "issues_remaining":   issues_remaining,
            "save_success":       ps.get("save_success", True),
            "total_duration_ms":  ps.get("total_duration_ms", 0),
        }

    # =========================================================================
    # build_agent_results_view
    # =========================================================================

    @staticmethod
    def build_agent_results_view(
        initial_agent_results: list[dict],
        revalidation_agent_results: list[dict],
    ) -> list[dict]:
        """
        Produce a clean per-agent view using the POST-remediation state as the
        source of truth, enriched with the PRE-remediation state to show what
        changed.

        Each check carries a ``remediation_outcome`` field:
          fixed                  — was FAIL/WARNING, is now PASS
          failed_to_fix          — Orion attempted a fix but the check is still FAIL
          manual_review_required — not auto-fixable; user must fix it manually
          no_issue               — was already PASS before remediation

        ``recommendation`` is included only when the check is FAIL or WARNING.
        ``page_no`` is included only when it is not null.
        """
        # Build lookup: agent_name → rule_id → initial issue dict
        initial_by_agent: dict[str, dict[str, dict]] = {}
        for agent in initial_agent_results:
            name = agent.get("agent_name", "")
            initial_by_agent[name] = {
                issue["rule_id"]: issue for issue in agent.get("issues", [])
            }

        result: list[dict] = []
        for agent in revalidation_agent_results:
            agent_name     = agent.get("agent_name", "")
            initial_checks = initial_by_agent.get(agent_name, {})

            checks: list[dict] = []
            has_fail = has_warning = False

            for issue in agent.get("issues", []):
                rule_id       = issue["rule_id"]
                final_status  = issue["status"]
                initial       = initial_checks.get(rule_id, {})
                init_status   = initial.get("status", "PASS")
                init_auto_fix = initial.get("auto_fixable")  # True | None

                if init_status == "PASS":
                    outcome = "no_issue"
                elif final_status == "PASS":
                    outcome = "fixed"
                elif init_auto_fix is True:
                    outcome = "failed_to_fix"
                else:
                    outcome = "manual_review_required"

                if final_status == "FAIL":
                    has_fail = True
                elif final_status == "WARNING":
                    has_warning = True

                entry: dict[str, Any] = {
                    "rule_id":             rule_id,
                    "category":            issue.get("category"),
                    "severity":            issue.get("severity"),
                    "final_status":        final_status,
                    "message":             issue.get("message"),
                    "remediation_outcome": outcome,
                }
                if final_status != "PASS":
                    entry["recommendation"] = issue.get("recommendation")
                if issue.get("page_no") is not None:
                    entry["page_no"] = issue["page_no"]

                checks.append(entry)

            agent_status = "FAIL" if has_fail else ("WARNING" if has_warning else "PASS")
            result.append({
                "agent_name":   agent_name,
                "agent_status": agent_status,
                "checks":       checks,
            })

        return result

    # =========================================================================
    # compute_dashboard
    # =========================================================================

    @staticmethod
    def compute_dashboard(job: dict) -> dict[str, Any]:
        """
        Derive four headline KPIs from a completed job's revalidation result
        (i.e. the post-remediation final state).

        accessibility_score — weighted PASS ratio across all checks (0–100)
        pdfua_compliance    — % of PDF/UA-specific rules that PASS (0–100)
        wcag_risk           — None | Low | Medium | High
        critical_issues     — count of CRITICAL checks still FAIL or WARNING
        """
        revalidation = job.get("revalidation_result") or {}

        all_checks: list[dict] = []
        for agent in revalidation.get("agent_results", []):
            all_checks.extend(agent.get("issues", []))

        sw = RemediationReportBuilder._SEVERITY_WEIGHT

        # ── Accessibility Score ───────────────────────────────────────────────
        weighted_total = sum(sw.get(c.get("severity", "LOW"), 1) for c in all_checks)
        weighted_pass  = sum(
            sw.get(c.get("severity", "LOW"), 1)
            for c in all_checks if c.get("status") == "PASS"
        )
        score = round(weighted_pass / weighted_total * 100) if weighted_total else 100

        # ── PDF/UA Compliance ─────────────────────────────────────────────────
        pdfua_checks = [
            c for c in all_checks
            if c.get("rule_id") in RemediationReportBuilder._PDFUA_RULES
        ]
        pdfua_pass = sum(1 for c in pdfua_checks if c.get("status") == "PASS")
        pdfua_pct  = round(pdfua_pass / len(pdfua_checks) * 100) if pdfua_checks else 100

        # ── WCAG Risk ─────────────────────────────────────────────────────────
        fail_severities = {
            c.get("severity", "LOW")
            for c in all_checks if c.get("status") == "FAIL"
        }
        if "CRITICAL" in fail_severities:
            wcag_risk = "High"
        elif "HIGH" in fail_severities:
            wcag_risk = "Medium"
        elif "MEDIUM" in fail_severities or "LOW" in fail_severities:
            wcag_risk = "Low"
        else:
            wcag_risk = "None"

        # ── Critical Issues ───────────────────────────────────────────────────
        critical_issues = sum(
            1 for c in all_checks
            if c.get("severity") == "CRITICAL" and c.get("status") in ("FAIL", "WARNING")
        )

        return {
            "accessibility_score": {
                "value": score,
                "max":   100,
                "label": f"{score}%",
            },
            "pdfua_compliance": {
                "value": pdfua_pct,
                "label": f"{pdfua_pct}%",
            },
            "wcag_risk": {
                "value": wcag_risk,
                "level": RemediationReportBuilder._WCAG_RISK_LEVEL.get(wcag_risk, 0),
            },
            "critical_issues": {
                "value": critical_issues,
            },
        }
