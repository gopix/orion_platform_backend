from __future__ import annotations

from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import or_

from src.core.database import SessionLocal
from src.core.logger import get_logger
from src.modules.accessibility_pdf.engines.validator.accessibility_agent_framework import (
    BaseAccessibilityValidatorAgent,
)
from src.modules.accessibility_pdf.models.agent_result import AgentResult
from src.modules.accessibility_pdf.models.org_project_accessibility_model import (
    OrgProjectAccessibilityCheckModel,
)
from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_pdf.models.validation_result import ValidationResult
from src.modules.accessibility_ppt.engine.ppt_loader import load_ppt_context
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)
from src.modules.accessibility_ppt.engine.ppt_validator.accessibility_score_agent import (
    AccessibilityScoreAgent,
)

logger = get_logger(__name__)

# The score agent is not part of the normal sequence: it aggregates every other
# agent's findings and therefore runs LAST, after all issues are collected.
SCORE_AGENT_CODE = "PPT_SCORE_AGENT"


class PPTValidationOrchestrator:
    """Orchestrates PPT accessibility validation.

    Loads a .pptx into a normalized context (ppt_loader), runs every
    ppt_validator agent's supported checks over it, then runs the score agent
    last to aggregate an overall + per-category score. Reuses the shared
    ValidationIssue / AgentResult / ValidationResult shapes so PPT and PDF
    reports are structurally identical.
    """

    # Agents run in this order (score agent excluded — it runs last, separately).
    IMPLEMENTED_AGENT_SEQUENCE: list[str] = [
        "PPT_METADATA_AGENT",
        "PPT_HEADING_AGENT",
        "PPT_SLIDE_STRUCTURE_AGENT",
        "PPT_PRESENTATION_AGENT",
        "PPT_READING_ORDER_AGENT",
        "PPT_TEXT_AGENT",
        "PPT_IMAGE_AGENT",
        "PPT_TABLE_AGENT",
        "PPT_COLOR_CONTRAST_AGENT",
        "PPT_HYPERLINK_AGENT",
    ]

    PLACEHOLDER_AGENT_SEQUENCE: list[str] = []

    EXECUTION_SEQUENCE: list[str] = IMPLEMENTED_AGENT_SEQUENCE + PLACEHOLDER_AGENT_SEQUENCE

    _PPT_VALIDATOR = "src.modules.accessibility_ppt.engine.ppt_validator"

    AGENT_CLASS_MAP: dict[str, tuple[str, str]] = {
        "PPT_METADATA_AGENT": (f"{_PPT_VALIDATOR}.metadata_agent", "MetadataAgent"),
        "PPT_HEADING_AGENT": (f"{_PPT_VALIDATOR}.heading_agent", "HeadingAgent"),
        "PPT_SLIDE_STRUCTURE_AGENT": (
            f"{_PPT_VALIDATOR}.slide_strcture_agent", "SlideStructureAgent"),
        "PPT_PRESENTATION_AGENT": (
            f"{_PPT_VALIDATOR}.presentation_agent", "PresentationAgent"),
        "PPT_READING_ORDER_AGENT": (
            f"{_PPT_VALIDATOR}.reading_order_agent", "ReadingOrderAgent"),
        "PPT_TEXT_AGENT": (f"{_PPT_VALIDATOR}.text_agent", "TextAgent"),
        "PPT_IMAGE_AGENT": (f"{_PPT_VALIDATOR}.image_agent", "ImageAgent"),
        "PPT_TABLE_AGENT": (f"{_PPT_VALIDATOR}.table_agent", "TableAgent"),
        "PPT_COLOR_CONTRAST_AGENT": (
            f"{_PPT_VALIDATOR}.color_contrast_agent", "ColorContrastAgent"),
        "PPT_HYPERLINK_AGENT": (
            f"{_PPT_VALIDATOR}.hyperlink_agent", "HyperlinkAgent"),
        SCORE_AGENT_CODE: (
            f"{_PPT_VALIDATOR}.accessibility_score_agent", "AccessibilityScoreAgent"),
    }

    def __init__(self) -> None:
        self._agent_instances: dict[str, BasePPTAccessibilityValidatorAgent] = {}
        self._last_execution_time_ms: int = 0

    def run(
        self,
        organization_id: int | None,
        context: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        start_time = perf_counter()
        try:
            context.setdefault("_cache", {})

            logger.info(
                "Pipeline run started | org_id=%s project_id=%s document=%s",
                organization_id,
                project_id,
                context.get("document_name") or context.get("pdf_doc_path") or "unknown_document",
            )

            agent_results: list[AgentResult] = []
            all_issues: list[ValidationIssue] = []
            executed_agents: list[str] = []
            unavailable_agents: list[str] = []
            placeholder_agents: list[str] = []
            planned_checks_count = 0

            logger.info(
                "Pipeline execution plan | agents=%s",
                self.EXECUTION_SEQUENCE,
            )

            for agent_code in self.EXECUTION_SEQUENCE:
                if agent_code in self.PLACEHOLDER_AGENT_SEQUENCE:
                    placeholder_agents.append(agent_code)
                    placeholder_issue = ValidationIssue(
                        agent_name=agent_code,
                        rule_id=f"{agent_code}_PENDING",
                        category="General",
                        severity="LOW",
                        page_no=None,
                        message=f"Agent {agent_code} is pending implementation",
                        recommendation="Implement and wire this agent in the validator package",
                        auto_fixable=False,
                        status="INFO",
                    )
                    agent_results.append(
                        AgentResult(
                            agent_name=agent_code,
                            success=False,
                            issue_count=1,
                            issues=[placeholder_issue],
                        )
                    )
                    all_issues.append(placeholder_issue)
                    logger.info("Agent placeholder used | agent=%s", agent_code)
                    continue

                agent = self._resolve_agent(agent_code)
                if not agent:
                    unavailable_agents.append(agent_code)
                    logger.warning(
                        "Agent unavailable | agent=%s",
                        agent_code,
                    )
                    unavailable_issue = ValidationIssue(
                        agent_name=agent_code,
                        rule_id=f"{agent_code}_UNAVAILABLE",
                        category="General",
                        severity="MEDIUM",
                        page_no=None,
                        message=f"Agent {agent_code} is not available yet",
                        recommendation="Configure or implement the mapped agent class",
                        auto_fixable=False,
                        status="INFO",
                    )

                    agent_results.append(
                        AgentResult(
                            agent_name=agent_code,
                            success=False,
                            issue_count=1,
                            issues=[unavailable_issue],
                        )
                    )
                    all_issues.append(unavailable_issue)
                    continue

                executed_agents.append(agent_code)
                check_codes = sorted(getattr(agent, "supported_checks", []))
                planned_checks_count += len(check_codes)

                if not check_codes:
                    no_check_issue = ValidationIssue(
                        agent_name=getattr(agent, "agent_name", agent_code),
                        rule_id=f"{agent_code}_NO_SUPPORTED_CHECKS",
                        category=getattr(agent, "category", "General"),
                        severity="LOW",
                        page_no=None,
                        message=f"Agent {agent_code} has no supported checks configured",
                        recommendation="Define supported_checks in the agent implementation",
                        auto_fixable=False,
                        status="INFO",
                    )
                    agent_results.append(
                        AgentResult(
                            agent_name=getattr(agent, "agent_name", agent_code),
                            success=False,
                            issue_count=1,
                            issues=[no_check_issue],
                        )
                    )
                    all_issues.append(no_check_issue)
                    continue

                issues: list[ValidationIssue] = []
                for check_code in check_codes:
                    try:
                        check_result = agent.run_check(check_code, context)
                        issue = self._normalize_issue(
                            check_result=check_result,
                            check_code=check_code,
                            agent_code=agent_code,
                            category=getattr(agent, "category", "General"),
                        )
                        issues.append(issue)
                    except Exception as exc:
                        issues.append(
                            ValidationIssue(
                                agent_name=getattr(agent, "agent_name", agent_code),
                                rule_id=check_code,
                                category=getattr(agent, "category", "General"),
                                severity="HIGH",
                                page_no=None,
                                message=f"Execution failed: {str(exc)}",
                                recommendation="Review agent runtime error and rerun",
                                auto_fixable=False,
                                status="FAIL",
                            )
                        )

                visible_issues = [issue for issue in issues if not issue.internal_check]

                logger.info(
                    "Agent executed | agent=%s checks=%s issues=%s fails=%s warnings=%s",
                    getattr(agent, "agent_name", agent_code),
                    len(check_codes),
                    len(visible_issues),
                    sum(1 for issue in visible_issues if issue.status == "FAIL"),
                    sum(1 for issue in visible_issues if issue.status == "WARNING"),
                )

                agent_results.append(
                    AgentResult(
                        agent_name=getattr(agent, "agent_name", agent_code),
                        success=not any(issue.status == "FAIL" for issue in visible_issues),
                        issue_count=len(visible_issues),
                        issues=visible_issues,
                    )
                )
                all_issues.extend(visible_issues)

            # ---- score agent runs LAST, aggregating every prior finding ------
            context["issues"] = all_issues
            score_agent = self._resolve_agent(SCORE_AGENT_CODE)
            if score_agent is not None:
                try:
                    score_issue = score_agent.run_check("PPT-SCORE-001", context)
                    agent_results.append(
                        AgentResult(
                            agent_name=getattr(score_agent, "agent_name", SCORE_AGENT_CODE),
                            success=True,
                            issue_count=1,
                            issues=[score_issue],
                        )
                    )
                    # NOTE: the score summary is a REPORT of the checks, not a
                    # check itself, so it is intentionally NOT added to
                    # all_issues — keeping total_checks aligned with the real
                    # checks (and with the score agent's own scored_checks).
                    executed_agents.append(SCORE_AGENT_CODE)
                except Exception as exc:
                    logger.warning("Score agent failed | agent=%s error=%s",
                                   SCORE_AGENT_CODE, exc)

            execution_time_ms = int((perf_counter() - start_time) * 1000)

            validation_result = self._build_validation_result(
                context=context,
                issues=all_issues,
                execution_time_ms=execution_time_ms,
            )
            response = asdict(validation_result)
            response["agent_results"] = [asdict(agent_result) for agent_result in agent_results]
            response["agent_execution"] = {
                "configured_checks_count": planned_checks_count,
                "configured_agent_codes": self.EXECUTION_SEQUENCE,
                "executed_agent_codes": executed_agents,
                "placeholder_agent_codes": placeholder_agents,
                "unavailable_agent_codes": unavailable_agents,
                "available_agent_codes": sorted(self.AGENT_CLASS_MAP.keys()),
                "note": "Pipeline executed in fixed agent sequence (implemented + placeholders)",
            }
            response["organization_id"] = organization_id
            response["project_id"] = project_id
            response["accessibility_score"] = context.get("accessibility_score")
            logger.info(
                "Pipeline run finished | org_id=%s project_id=%s total_issues=%s agents_executed=%s duration_ms=%s",
                organization_id,
                project_id,
                response.get("total_issues", 0),
                len(executed_agents),
                execution_time_ms,
            )
            return response
        finally:
            self._last_execution_time_ms = int((perf_counter() - start_time) * 1000)

    @staticmethod
    def _normalize_issue(
        check_result: ValidationIssue | dict[str, Any],
        check_code: str,
        agent_code: str,
        category: str,
    ) -> ValidationIssue:
        if isinstance(check_result, ValidationIssue):
            return check_result

        if not isinstance(check_result, dict):
            return ValidationIssue(
                agent_name=(agent_code or "UNKNOWN_AGENT"),
                rule_id=check_code,
                category=category or "General",
                severity="MEDIUM",
                page_no=None,
                message="Invalid check result format returned by agent",
                recommendation="Update agent to return ValidationIssue",
                auto_fixable=False,
                status="FAIL",
            )

        passed = bool(check_result.get("passed", False))
        severity = str(check_result.get("severity") or "MEDIUM").upper()
        message = check_result.get("message") or "Check executed"
        return ValidationIssue(
            agent_name=check_result.get("agent_name") or (agent_code or "UNKNOWN_AGENT"),
            rule_id=check_code,
            category=check_result.get("category") or category or "General",
            severity=severity,
            page_no=check_result.get("page_no"),
            message=message,
            recommendation=check_result.get("recommendation") or "Review check result",
            auto_fixable=bool(check_result.get("auto_fixable", False)),
            status="PASS" if passed else ("WARNING" if severity == "LOW" else "FAIL"),
            internal_check=bool(check_result.get("internal_check", False)),
        )

    @staticmethod
    def _build_validation_result(
        context: dict[str, Any],
        issues: list[ValidationIssue],
        execution_time_ms: int,
    ) -> ValidationResult:
        # Partition by status
        fail_issues    = [i for i in issues if i.status == "FAIL"]
        warning_issues = [i for i in issues if i.status == "WARNING"]
        # Actionable = issues the caller needs to act on (excludes PASS/INFO)
        actionable_issues = fail_issues + warning_issues

        # Severity breakdown — FAIL issues only (a CRITICAL-severity PASS is not a critical problem)
        critical_count = sum(1 for i in fail_issues if i.severity == "CRITICAL")
        high_count     = sum(1 for i in fail_issues if i.severity == "HIGH")
        medium_count   = sum(1 for i in fail_issues if i.severity == "MEDIUM")
        low_count      = sum(1 for i in fail_issues if i.severity == "LOW")
        warning_count  = len(warning_issues)

        # Fixability — FAIL issues only
        auto_fixable_count  = sum(1 for i in fail_issues if i.auto_fixable)
        manual_review_count = sum(1 for i in fail_issues if not i.auto_fixable)
        # WARNING issues are flagged for human/AI review
        ai_review_count     = warning_count

        if fail_issues:
            overall_status = "FAIL"
        elif warning_issues:
            overall_status = "WARNING"
        else:
            overall_status = "PASS"

        pdf_doc_path = context.get("pdf_doc_path")
        document_name = context.get("document_name")
        if not document_name and isinstance(pdf_doc_path, str) and pdf_doc_path:
            document_name = Path(pdf_doc_path).name

        total_pages = context.get("total_pages", 0)
        if not isinstance(total_pages, int):
            total_pages = 0

        return ValidationResult(
            document_name=document_name or "unknown_document",
            total_pages=total_pages,
            execution_time_ms=execution_time_ms,
            total_checks=len(issues),           # All checks run (PASS + FAIL + WARNING + INFO)
            total_issues=len(actionable_issues), # Actionable only (FAIL + WARNING)
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            warning_count=warning_count,
            auto_fixable_count=auto_fixable_count,
            manual_review_count=manual_review_count,
            ai_review_count=ai_review_count,
            overall_status=overall_status,
            issues=actionable_issues,           # FAIL + WARNING only; PASS detail is in agent_results
        )

    def _fetch_enabled_checks(
        self,
        organization_id: int | None,
        project_id: str | None,
    ) -> list[OrgProjectAccessibilityCheckModel]:
        session = SessionLocal()
        try:
            query = session.query(OrgProjectAccessibilityCheckModel).filter(
                OrgProjectAccessibilityCheckModel.is_active.is_(True),
            )

            if organization_id is not None:
                query = query.filter(OrgProjectAccessibilityCheckModel.organization_id == organization_id)

            if project_id is None:
                query = query.filter(OrgProjectAccessibilityCheckModel.project_id.is_(None))
            else:
                query = query.filter(
                    or_(
                        OrgProjectAccessibilityCheckModel.project_id == project_id,
                        OrgProjectAccessibilityCheckModel.project_id.is_(None),
                    )
                )

            return (
                query.order_by(
                    OrgProjectAccessibilityCheckModel.agent_code.asc(),
                    OrgProjectAccessibilityCheckModel.check_code.asc(),
                ).all()
            )
        finally:
            session.close()

    def _group_by_agent(
        self, checks: list[OrgProjectAccessibilityCheckModel]
    ) -> dict[str, list[OrgProjectAccessibilityCheckModel]]:
        grouped: dict[str, list[OrgProjectAccessibilityCheckModel]] = {}
        for check in checks:
            agent_code = (check.agent_code or "").strip()
            if not agent_code:
                agent_code = "UNASSIGNED_AGENT"
            grouped.setdefault(agent_code, []).append(check)
        return grouped

    def _resolve_agent(self, agent_code: str) -> BasePPTAccessibilityValidatorAgent | None:
        if agent_code in self._agent_instances:
            return self._agent_instances[agent_code]

        mapping = self.AGENT_CLASS_MAP.get(agent_code)
        if not mapping:
            return None

        module_path, class_name = mapping
        try:
            module = import_module(module_path)
            agent_cls = getattr(module, class_name)
            instance = agent_cls()
            # Accept PPT agents (and, defensively, the PDF base) so the shared
            # run loop can drive either family.
            if not isinstance(instance, (BasePPTAccessibilityValidatorAgent,
                                         BaseAccessibilityValidatorAgent)):
                return None
            self._agent_instances[agent_code] = instance
            return instance
        except Exception:
            return None

    # ------------------------------------------------------------------ public
    def validate(
        self,
        pptx_path: str,
        organization_id: int | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Load a .pptx and run the full PPT validation, returning the report.

        Convenience entry point: builds the normalized context with ppt_loader,
        then delegates to run(). The returned dict includes 'accessibility_score'
        (overall + per-category) alongside the standard ValidationResult fields.
        """
        context = load_ppt_context(pptx_path)
        # ValidationResult reports "total_pages"; for a deck that's the slide count.
        context.setdefault("total_pages", context.get("total_slides", 0))
        return self.run(organization_id=organization_id, context=context,
                        project_id=project_id)


# Backwards-compatible alias: the remediation pipeline imports the old name.
AccessibilityEnginePipeline = PPTValidationOrchestrator
