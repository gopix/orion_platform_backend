"""
ImageRemediatorAgent - Remediates image accessibility issues in PDF documents.

Handles the following auto-fixable rules from ImageAccessibilityAgent:

    IMG-001  Missing alt text
             → Sets a location-based placeholder: "Figure on page N"
               for every Figure element whose GetAlt() returns None.

    IMG-002  Non-descriptive / empty alt text
             → Replaces generic placeholders ("image", "photo", "picture",
               "figure", "image1", "img", or empty string) with a richer
               placeholder: "Figure on page N – description required".

Strategy:
    A single depth-first traversal of the PDF structure tree collects every
    "Figure" element that needs fixing and applies ``SetAlt()`` in-place.
    The ``images_by_pdf`` validator cache is invalidated so re-validation
    performs a fresh traversal.

Note on alt-text quality:
    These placeholders are intentionally conservative – they ensure the
    technical requirement (non-None, non-empty alt attribute) is met while
    flagging that a human or AI description pass is still needed.
    A downstream AI enrichment step (not part of this agent) should replace
    placeholders with meaningful descriptions.
"""

from __future__ import annotations

from typing import Any, Callable

from src.core.logger import get_logger

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)

# Generic placeholder strings that IMG-002 considers non-descriptive (lower-cased)
_GENERIC_ALT_VALUES: frozenset[str] = frozenset(
    {"", "image", "photo", "picture", "figure", "image1", "img"}
)


class ImageRemediatorAgent(BaseRemediatorAgent):
    """Remediates image alt-text issues using PDFix structure-tree traversal."""

    agent_name = "Image Remediator Agent"

    supported_rules: set[str] = {
        "IMG-001",  # Missing alt text (GetAlt() is None)
        "IMG-002",  # Non-descriptive / empty alt text
    }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        rule_id = issue.get("rule_id", "")
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_alt_text", error="pdf_doc not in context")

        handlers: dict[str, Callable] = {
            "IMG-001": self._fix_missing_alt,
            "IMG-002": self._fix_poor_alt,
        }
        handler = handlers.get(rule_id)
        if handler is None:
            return self._result(
                rule_id, False, "no_handler",
                error=f"ImageRemediatorAgent: unsupported rule '{rule_id}'",
            )
        return handler(rule_id, context, pdf_doc)

    # ------------------------------------------------------------------
    # IMG-001 – Missing alt text
    # ------------------------------------------------------------------

    def _fix_missing_alt(
        self,
        rule_id: str,
        context: dict[str, Any],
        pdf_doc: Any,
    ) -> RemediationResult:
        """Add placeholder alt text to Figure elements whose ``GetAlt()`` is None."""
        return self._apply_alt_fix(
            rule_id=rule_id,
            context=context,
            pdf_doc=pdf_doc,
            action="fix_missing_alt",
            should_fix=lambda alt: alt is None,
            make_alt=lambda page: f"Figure on page {page}",
        )

    # ------------------------------------------------------------------
    # IMG-002 – Poor / empty alt text
    # ------------------------------------------------------------------

    def _fix_poor_alt(
        self,
        rule_id: str,
        context: dict[str, Any],
        pdf_doc: Any,
    ) -> RemediationResult:
        """Replace generic placeholder alt text with a more informative default."""
        return self._apply_alt_fix(
            rule_id=rule_id,
            context=context,
            pdf_doc=pdf_doc,
            action="fix_poor_alt",
            should_fix=lambda alt: alt is not None and (alt or "").strip().lower() in _GENERIC_ALT_VALUES,
            make_alt=lambda page: f"Figure on page {page} – description required",
        )

    # ------------------------------------------------------------------
    # Shared traversal logic
    # ------------------------------------------------------------------

    def _apply_alt_fix(
        self,
        rule_id: str,
        context: dict[str, Any],
        pdf_doc: Any,
        action: str,
        should_fix: Callable[[str | None], bool],
        make_alt: Callable[[int], str],
    ) -> RemediationResult:
        changes: list[str] = []
        try:
            struct_tree = pdf_doc.GetStructTree()
            if not struct_tree:
                return self._result(
                    rule_id, False, action,
                    error="No structure tree found – cannot set alt text. "
                          "Run DOC_IS_TAGGED remediation first.",
                )

            _traverse_and_fix_alt(struct_tree, should_fix, make_alt, changes)

            # Invalidate the image cache so re-validation re-reads fixed alt text
            self._invalidate_cache(context, "images_by_pdf")

            if not changes:
                return self._result(
                    rule_id, True, action,
                    changes_made=["No Figure elements matched the fix condition – no changes made"],
                )
            return self._result(rule_id, True, action, changes_made=changes)

        except Exception as exc:
            logger.exception("%s remediation failed", rule_id)
            return self._result(rule_id, False, action, changes_made=changes, error=str(exc))


# ---------------------------------------------------------------------------
# Module-level traversal helper (keeps the class lean)
# ---------------------------------------------------------------------------

def _traverse_and_fix_alt(
    node: Any,
    should_fix: Callable[[str | None], bool],
    make_alt: Callable[[int], str],
    changes: list[str],
    depth: int = 0,
) -> None:
    """
    Depth-first traversal of a PDFix structure tree node.

    Visits every ``Figure`` element; when ``should_fix(current_alt)`` is True,
    calls ``SetAlt(make_alt(page_number))`` and records the change.
    Recurses into all children regardless of type.
    """
    try:
        num_children: int = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
    except Exception:
        return

    for i in range(num_children):
        try:
            child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
        except Exception:
            continue
        if child is None:
            continue

        try:
            el_type: str = child.GetType() if hasattr(child, "GetType") else ""
        except Exception:
            el_type = ""

        if el_type == "Figure":
            try:
                current_alt: str | None = child.GetAlt() if hasattr(child, "GetAlt") else None
                if should_fix(current_alt):
                    try:
                        page_num: int = (
                            (child.GetPageNumber() or 0) + 1
                            if hasattr(child, "GetPageNumber")
                            else 0
                        )
                    except Exception:
                        page_num = 0

                    new_alt = make_alt(page_num)
                    if hasattr(child, "SetAlt"):
                        child.SetAlt(new_alt)
                        changes.append(
                            f"Figure (page {page_num}): "
                            f"alt '{current_alt!r}' → '{new_alt}'"
                        )
            except Exception:
                pass  # Best-effort; continue with next element

        # Always recurse
        if hasattr(child, "GetNumChildren"):
            _traverse_and_fix_alt(child, should_fix, make_alt, changes, depth + 1)
