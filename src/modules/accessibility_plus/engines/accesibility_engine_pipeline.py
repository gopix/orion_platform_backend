from __future__ import annotations

from importlib import import_module
from typing import Any

from sqlalchemy import or_

from src.core.database import SessionLocal
from src.modules.accessibility_plus.engines.accessibility_agent_framework import BaseAccessibilityAgent
from src.modules.accessibility_plus.models.org_project_accessibility_model import OrgProjectAccessibilityCheckModel


class AccessibilityEnginePipeline:
    """Fetch enabled checks for an org/project and execute them via mapped agents."""

    AGENT_CLASS_MAP: dict[str, tuple[str, str]] = {
        "METADATA_AGENT": (
            "src.modules.accessibility_plus.engines.metadata_agent",
            "MetadataAgent",
        ),
        "IMAGE_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.image_accessibility_agent",
            "ImageAccessibilityAgent",
        ),
        "STRUCTURE_AUDIT_AGENT": (
            "src.modules.accessibility_plus.engines.strcture_audit_agent",
            "StructureAuditAgent",
        ),
        "TABLE_ACCESSIBILITY_AGENT": (
            "src.modules.accessibility_plus.engines.table_accessibility_agent",
            "TableAccessibilityAgent",
        ),
        "OCR_ANALYSIS_AGENT": (
            "src.modules.accessibility_plus.engines.ocr_analysis_agent",
            "OCRAnalysisAgent",
        ),
        "CONTENT_VALIDATION_AGENT": (
            "src.modules.accessibility_plus.engines.content_validation_agent",
            "ContentValidationAgent",
        ),
        "FONT_ANALYSIS_AGENT": (
            "src.modules.accessibility_plus.engines.font_analysis_agent",
            "FontAnalysisAgent",
        ),
    }

    def __init__(self) -> None:
        self._agent_instances: dict[str, BaseAccessibilityAgent] = {}

    def run(
        self,
        organization_id: int,
        context: dict[str, Any],
        project_id: str | None = None,
        include_org_level_fallback: bool = True,
    ) -> dict[str, Any]:
        checks = self._fetch_enabled_checks(
            organization_id=organization_id,
            project_id=project_id,
            include_org_level_fallback=include_org_level_fallback,
        )

        grouped_checks = self._group_by_agent(checks)

        results: list[dict[str, Any]] = []
        for agent_code, agent_checks in grouped_checks.items():
            agent = self._resolve_agent(agent_code)
            if not agent:
                for check in agent_checks:
                    results.append(
                        {
                            "agent_code": agent_code,
                            "check_code": check.check_code,
                            "passed": False,
                            "message": f"Agent {agent_code} is not available yet",
                            "value": None,
                            "check_config": check.to_dict(),
                        }
                    )
                continue

            for check in agent_checks:
                try:
                    check_result = agent.run_check(check.check_code, context)
                    results.append(
                        {
                            "agent_code": agent_code,
                            "check_code": check.check_code,
                            "passed": bool(check_result.get("passed", False)),
                            "message": check_result.get("message"),
                            "value": check_result.get("value"),
                            "check_config": check.to_dict(),
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "agent_code": agent_code,
                            "check_code": check.check_code,
                            "passed": False,
                            "message": f"Execution failed: {str(exc)}",
                            "value": None,
                            "check_config": check.to_dict(),
                        }
                    )

        return {
            "organization_id": organization_id,
            "project_id": project_id,
            "total_checks": len(checks),
            "executed_checks": len(results),
            "results": results,
        }

    def _fetch_enabled_checks(
        self,
        organization_id: int,
        project_id: str | None,
        include_org_level_fallback: bool,
    ) -> list[OrgProjectAccessibilityCheckModel]:
        session = SessionLocal()
        try:
            query = session.query(OrgProjectAccessibilityCheckModel).filter(
                OrgProjectAccessibilityCheckModel.organization_id == organization_id,
                OrgProjectAccessibilityCheckModel.is_active.is_(True),
            )

            if project_id is None:
                query = query.filter(OrgProjectAccessibilityCheckModel.project_id.is_(None))
            elif include_org_level_fallback:
                query = query.filter(
                    or_(
                        OrgProjectAccessibilityCheckModel.project_id == project_id,
                        OrgProjectAccessibilityCheckModel.project_id.is_(None),
                    )
                )
            else:
                query = query.filter(OrgProjectAccessibilityCheckModel.project_id == project_id)

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

    def _resolve_agent(self, agent_code: str) -> BaseAccessibilityAgent | None:
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
            if not isinstance(instance, BaseAccessibilityAgent):
                return None
            self._agent_instances[agent_code] = instance
            return instance
        except Exception:
            return None
