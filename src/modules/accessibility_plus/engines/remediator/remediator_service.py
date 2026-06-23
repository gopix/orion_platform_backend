"""
RemediatorService - Central routing service for the accessibility remediation pipeline.

Responsibilities:
- Lazily loads all remediator agents at startup.
- Builds a ``rule_id → agent`` lookup table from each agent's ``supported_rules``.
- Dispatches ``remediate(issue, context)`` calls to the correct agent.
- Surfaces a clean ``RemediationResult`` on any unexpected error.

Usage::

    service = RemediatorService()
    result = service.remediate(issue_dict, context)
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from src.core.logger import get_logger

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class RemediatorService:
    """Routes validation issues to the appropriate remediator agent."""

    # (module_path, ClassName) for every concrete agent
    _AGENT_REGISTRY: list[tuple[str, str]] = [
        (
            "src.modules.accessibility_plus.engines.remediator.document__remediator_agent",
            "DocumentRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.image_remediator_agent",
            "ImageRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.structure_remediator_agent",
            "StructureRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.table_remediator_agent",
            "TableRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.visual_remediator_agent",
            "VisualRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.reading_order_remediator_agent",
            "ReadingOrderRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.tree_structure_remediator_agent",
            "TreeStructureRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.link_remediator_agent",
            "LinkRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.artifact_remediator_agent",
            "ArtifactRemediatorAgent",
        ),
        (
            "src.modules.accessibility_plus.engines.remediator.heading_remediator_agent",
            "HeadingRemediatorAgent",
        ),
    ]

    def __init__(self) -> None:
        # rule_id → agent instance
        self._rule_map: dict[str, BaseRemediatorAgent] = {}
        self._load_agents()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        """
        Dispatch *issue* to the correct remediator agent.

        Args:
            issue:   Serialised ``ValidationIssue`` dict.
            context: Shared pipeline context (contains ``pdf_doc``, caches, …).

        Returns:
            ``RemediationResult`` – success or failure, never raises.
        """
        rule_id = issue.get("rule_id") or ""
        agent = self._rule_map.get(rule_id)

        if agent is None:
            logger.warning("RemediatorService: no agent registered for rule_id=%s", rule_id)
            return RemediationResult(
                rule_id=rule_id,
                agent_name="RemediatorService",
                success=False,
                action="no_handler",
                error=f"No remediator registered for rule_id='{rule_id}'",
            )

        logger.info(
            "Remediating | rule_id=%s agent=%s",
            rule_id,
            getattr(agent, "agent_name", type(agent).__name__),
        )
        try:
            result = agent.remediate(issue, context)
            logger.info(
                "Remediation done | rule_id=%s success=%s changes=%s",
                rule_id,
                result.success,
                len(result.changes_made),
            )
            return result
        except Exception as exc:
            logger.exception("Unexpected error during remediation | rule_id=%s", rule_id)
            return RemediationResult(
                rule_id=rule_id,
                agent_name=getattr(agent, "agent_name", type(agent).__name__),
                success=False,
                action="unexpected_error",
                error=str(exc),
            )

    @property
    def supported_rules(self) -> set[str]:
        """All rule_ids that at least one registered agent can fix."""
        return set(self._rule_map.keys())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_agents(self) -> None:
        for module_path, class_name in self._AGENT_REGISTRY:
            try:
                module = import_module(module_path)
                agent_cls = getattr(module, class_name)
                agent: BaseRemediatorAgent = agent_cls()

                rules = getattr(agent, "supported_rules", set())
                for rule_id in rules:
                    if rule_id in self._rule_map:
                        logger.warning(
                            "RemediatorService: rule_id '%s' already registered by %s; "
                            "overwriting with %s",
                            rule_id,
                            type(self._rule_map[rule_id]).__name__,
                            class_name,
                        )
                    self._rule_map[rule_id] = agent

                logger.debug(
                    "Loaded remediator agent | class=%s rules=%s",
                    class_name,
                    sorted(rules),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load remediator agent | class=%s error=%s",
                    class_name,
                    exc,
                )


# Module-level singleton (matches existing pattern in codebase)
remediation_service = RemediatorService()
