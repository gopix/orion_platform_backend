"""
BaseRemediatorAgent - Abstract base class for all PDF accessibility remediator agents.

Each concrete remediator agent:
- Declares which rule_ids it handles via ``supported_rules``
- Implements ``remediate(issue, context) -> RemediationResult``

The ``context`` dict mirrors the validator context and always contains:
    - pdf_doc     : open PDFix PdfDoc object (modifications are in-place)
    - pdf_doc_path: original PDF file path (str)
    - _cache      : shared cache dict (remediators must invalidate relevant keys after edits)
    - document_name: human-readable document name (optional)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RemediationResult:
    """Outcome of a single remediation attempt."""

    rule_id: str
    """The validation rule that was remediated (e.g. 'DOC_HAS_LANGUAGE')."""

    agent_name: str
    """Name of the remediator agent that processed this rule."""

    success: bool
    """True when the fix was applied without errors."""

    action: str
    """Short snake_case label describing what was attempted (e.g. 'fix_language')."""

    changes_made: list[str] = field(default_factory=list)
    """Human-readable list of changes applied to the document."""

    error: str | None = None
    """Error message if the fix failed; None on success."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseRemediatorAgent(ABC):
    """Abstract base class that every remediator agent must subclass."""

    #: Short human-readable name shown in results.
    agent_name: str

    #: Set of ``rule_id`` strings this agent can fix.
    supported_rules: set[str] = set()

    @abstractmethod
    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        """
        Apply a fix for *issue* to the PDF document in *context*.

        The ``pdf_doc`` inside *context* is modified **in place**.  The caller
        (``RemediatorService`` / ``AccessibilityRemediationPipeline``) is
        responsible for calling ``pdf_doc.Save(...)`` after all remediations
        are complete.

        Args:
            issue:   Serialised ``ValidationIssue`` dict (as returned by
                     ``AccessibilityEnginePipeline.run``).
            context: Shared pipeline context dict.

        Returns:
            ``RemediationResult`` describing what happened.
        """

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def _result(
        self,
        rule_id: str,
        success: bool,
        action: str,
        changes_made: list[str] | None = None,
        error: str | None = None,
    ) -> RemediationResult:
        """Convenience factory that fills in ``agent_name`` automatically."""
        return RemediationResult(
            rule_id=rule_id,
            agent_name=self.agent_name,
            success=success,
            action=action,
            changes_made=changes_made or [],
            error=error,
        )

    @staticmethod
    def _invalidate_cache(context: dict[str, Any], *keys: str) -> None:
        """Remove one or more keys from the shared ``_cache`` dict."""
        cache = context.get("_cache", {})
        for key in keys:
            cache.pop(key, None)
