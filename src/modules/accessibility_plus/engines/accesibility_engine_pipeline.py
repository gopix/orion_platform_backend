from __future__ import annotations

from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import or_

from src.core.database import SessionLocal
from src.core.logger import get_logger
from src.modules.accessibility_plus.engines.validator.accessibility_agent_framework import (
    BaseAccessibilityValidatorAgent,
)
from src.modules.accessibility_plus.models.agent_result import AgentResult
from src.modules.accessibility_plus.models.org_project_accessibility_model import (
    OrgProjectAccessibilityCheckModel,
)
from src.modules.accessibility_plus.models.validation_issue import ValidationIssue
from src.modules.accessibility_plus.models.validation_result import ValidationResult

logger = get_logger(__name__)


class AccessibilityEnginePipeline:
    """Fetch enabled checks for an org/project and execute them via mapped agents."""

    IMPLEMENTED_AGENT_SEQUENCE: list[str] = [
        "DOCUMENT_ACCESSIBILITY_AGENT",
        "STRUCTURE_HEADING_AGENT",
        "IMAGE_ACCESSIBILITY_AGENT",
        "TABLE_ACCESSIBILITY_AGENT",
        "READING_ORDER_AGENT",
        "VISUAL_ACCESSIBILITY_AGENT",
        "TREE_STRUCTURE_AGENT",
        "LINK_ACCESSIBILITY_AGENT",
        "ARTIFACT_ACCESSIBILITY_AGENT",
    ]

    PLACEHOLDER_AGENT_SEQUENCE: list[str] = []

    EXECUTION_SEQUENCE: list[str] = IMPLEMENTED_AGENT_SEQUENCE + PLACEHOLDER_AGENT_SEQUENCE

    AGENT_CLASS_MAP: dict[str, tuple[str, str]] = {
        "DOCUMENT_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.validator.document_accessibility_agent",
            "DocumentAccessibilityAgent",
        ),
        "METADATA_AGENT": (
            "src.modules.accessibility_plus.engines.validator.metadata_agent",
            "MetadataAgent",
        ),
        "IMAGE_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.validator.image_accessibility_agent",
            "ImageAccessibilityAgent",
        ),
        "STRUCTURE_HEADING_AGENT": (
            "src.modules.accessibility_plus.engines.validator.structure_heading_agent",
            "StructureHeadingAgent",
        ),
        "STRUCTURE_AUDIT_AGENT": (
            "src.modules.accessibility_plus.engines.validator.structure_heading_agent",
            "StructureHeadingAgent",
        ),
        "TABLE_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.validator.table_accessibility_agent",
            "TableAccessibilityAgent",
        ),
        "CONTENT_VALIDATION_AGENT": (
            "src.modules.accessibility_plus.engines.validator.content_quality_agent",
            "ContentQualityAgent",
        ),
        "READING_ORDER_AGENT": (
            "src.modules.accessibility_plus.engines.validator.reading_order_agent",
            "ReadingOrderAgent",
        ),
        "VISUAL_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.validator.visual_accessibility_agent",
            "VisualAccessibilityAgent",
        ),
        "TREE_STRUCTURE_AGENT": (
            "src.modules.accessibility_plus.engines.validator.tree_structure_agent",
            "TreeStructureAgent",
        ),
        "LINK_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.validator.link_accessibility_agent",
            "LinkAccessibilityAgent",
        ),
        "ARTIFACT_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.validator.artifact_accessibility_agent",
            "ArtifactAccessibilityAgent",
        ),
    }

    def __init__(self) -> None:
        self._agent_instances: dict[str, BaseAccessibilityValidatorAgent] = {}
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
        critical_count = sum(1 for issue in issues if issue.severity == "CRITICAL")
        high_count = sum(1 for issue in issues if issue.severity == "HIGH")
        medium_count = sum(1 for issue in issues if issue.severity == "MEDIUM")
        low_count = sum(1 for issue in issues if issue.severity == "LOW")

        auto_fixable_count = sum(1 for issue in issues if issue.auto_fixable)
        manual_review_count = sum(
            1 for issue in issues if issue.status == "FAIL" and not issue.auto_fixable
        )
        ai_review_count = sum(1 for issue in issues if issue.status in {"WARNING", "INFO"})

        if any(issue.status == "FAIL" for issue in issues):
            overall_status = "FAIL"
        elif any(issue.status == "WARNING" for issue in issues):
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
            total_issues=len(issues),
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            auto_fixable_count=auto_fixable_count,
            manual_review_count=manual_review_count,
            ai_review_count=ai_review_count,
            overall_status=overall_status,
            issues=issues,
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

    def _resolve_agent(self, agent_code: str) -> BaseAccessibilityValidatorAgent | None:
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
            if not isinstance(instance, BaseAccessibilityValidatorAgent):
                return None
            self._agent_instances[agent_code] = instance
            return instance
        except Exception:
            return None
