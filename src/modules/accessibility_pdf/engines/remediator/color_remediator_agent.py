"""
ColorRemediatorAgent - Remediates text colour-contrast issues (WCAG 1.4.3).

Handles the auto-fixable rules from ColorAccessibilityAgent:

    COLOR-001  Normal-size text below 4.5:1 contrast
    COLOR-002  Large text below 3:1 contrast

Design note:
    Contrast remediation cannot be performed on the open PDFix ``pdf_doc``:
    it requires rewriting colour operators (``rg`` / ``g``) inside the page
    content streams, which contrast_fixer.py does with pikepdf on the SAVED
    file.  This agent therefore follows the "scheduled fix" pattern (same as
    DOC_PDFUA_DECLARATION / LINK-001 / HDR-001): it returns
    ``action="schedule_contrast_fix"`` and flags the context so
    ``_save_remediated_pdf`` records the actual outcome of the
    ``fix_text_contrast`` post-processing step in ``scheduled_outcomes``.

    contrast_fixer darkens failing colours to >= 4.5:1 against the worst-case
    light background, which satisfies both the 4.5:1 (COLOR-001) and 3:1
    (COLOR-002) thresholds in a single pass.
"""

from __future__ import annotations

from typing import Any

from src.core.logger import get_logger

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class ColorRemediatorAgent(BaseRemediatorAgent):
    """Schedules colour-contrast remediation via the contrast_fixer post-processor."""

    agent_name = "Color Remediator Agent"

    supported_rules: set[str] = {
        "COLOR-001",  # Normal text contrast < 4.5:1
        "COLOR-002",  # Large text contrast < 3:1
    }

    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        rule_id = issue.get("rule_id", "")
        if rule_id not in self.supported_rules:
            return self._result(
                rule_id, False, "no_handler",
                error=f"ColorRemediatorAgent: unsupported rule '{rule_id}'",
            )

        # Flag the pipeline so _save_remediated_pdf reconciles the outcome of
        # the fix_text_contrast subprocess/post-processing step for this rule.
        context["_contrast_fix_scheduled"] = True

        # Hand the validator's light-text-colour whitelist to the pipeline so
        # contrast_fixer can darken light TEXT colours it would otherwise
        # skip as presumed backgrounds.
        try:
            color_cache = context.get("_cache", {}).get("color_accessibility", {})
            for entry in color_cache.values():
                whitelist = entry.get("light_text_colors") or []
                if whitelist:
                    existing = context.setdefault("_contrast_known_text_colors", [])
                    for col in whitelist:
                        if col not in existing:
                            existing.append(col)
        except Exception:  # pragma: no cover - defensive
            logger.warning("ColorRemediatorAgent: could not extract text-colour whitelist")

        # Invalidate the validator cache so re-validation recomputes contrast.
        self._invalidate_cache(context, "color_accessibility")

        target = "4.5:1" if rule_id == "COLOR-001" else "3:1"
        logger.info("ColorRemediatorAgent: scheduled contrast fix for %s", rule_id)
        return self._result(
            rule_id,
            success=True,
            action="schedule_contrast_fix",
            changes_made=[
                f"Contrast fix scheduled: text colours failing the {target} WCAG 1.4.3 "
                "threshold will be darkened to at least 4.5:1 against the worst-case "
                "light background during post-processing (contrast_fixer)."
            ],
        )
