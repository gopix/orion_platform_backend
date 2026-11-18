"""
Structure Heading Agent
-----------------------
Validates heading structure accessibility (H1-H6 structure elements) in
the PDF StructTree.

Check codes
-----------
HDR-001  At least one H1 heading is present (auto-fixable if missing)
HDR-002  Exactly one H1 heading exists (cannot auto-fix — human choice)
HDR-003  Heading levels are sequential — no level-skipping
HDR-004  Heading elements have accessible text metadata (ActualText / /T)
HDR-005  All heading elements have valid parent structure element types
         (PAC Matterhorn "Invalid use of Hn structure element") — auto-fixable

Implementation uses pikepdf to walk the PDF StructTree directly, so it
works regardless of the PDFix SDK's AddTags()/struct-tree state.
"""
from __future__ import annotations
from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent
from src.modules.accessibility_pdf.engines.title_tag import (
    TITLE_EQUIVALENT_LEVEL,
    TITLE_TAG,
)
from src.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

# "/Title" is in this set because it role-maps to /H1 (see engines/title_tag.py).
# HDR-001 ("at least one H1") and HDR-002 ("exactly one H1") are evaluated after
# role resolution, so a document whose only level-1 element is <Title> is
# correct — omitting it here would fail HDR-001 on a properly remediated file.
_HEADING_TAGS: set[str] = {"/H", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6", TITLE_TAG}

# PDF/UA 6.4.2 — only these element types are valid parents of H / Hn.
_VALID_HEADING_PARENTS: set[str] = {
    "/Document", "/Sect", "/Part", "/Art", "/Div",
    "/BlockQuote", "/Caption", "/TOC", "/TOCI",
    "/Index", "/Private",
}


# ---------------------------------------------------------------------------
# struct-tree analysis (module-level, pikepdf-based)
# ---------------------------------------------------------------------------

def _walk(struct_root, visitor) -> None:
    """Call visitor(node) for every pikepdf.Dictionary node in the struct tree."""
    import pikepdf

    def _recurse(node):
        try:
            if not isinstance(node, pikepdf.Dictionary):
                return
            visitor(node)
            k = node.get("/K")
            if k is None:
                return
            if isinstance(k, pikepdf.Array):
                for child in k:
                    try:
                        obj = (child if isinstance(child, pikepdf.Dictionary)
                               else child.get_object())
                        _recurse(obj)
                    except Exception:
                        pass
            elif isinstance(k, pikepdf.Dictionary):
                _recurse(k)
        except Exception:
            pass

    k_root = struct_root.get("/K")
    if isinstance(k_root, pikepdf.Array):
        for child in k_root:
            try:
                obj = (child if isinstance(child, pikepdf.Dictionary)
                       else child.get_object())
                _recurse(obj)
            except Exception:
                pass
    elif isinstance(k_root, pikepdf.Dictionary):
        _recurse(k_root)


def _gather_heading_info(pdf_path: str) -> dict:
    """
    Walk the struct tree and return a dict with all heading-related counts
    needed by the HDR-001..HDR-005 checks.

    Keys returned:
        h1_count              : int
        heading_levels        : set[int]   (1-6; level derived from /S tag)
        total_headings        : int
        headings_without_text : int        (no ActualText and no /T)
        invalid_parent_count  : int
        invalid_parent_examples : list[str]
    """
    try:
        import pikepdf
    except ImportError:
        logger.warning("structure_heading_agent: pikepdf not available")
        return {}

    result: dict = {
        "h1_count":               0,
        "heading_levels":         set(),
        "total_headings":         0,
        "headings_without_text":  0,
        "invalid_parent_count":   0,
        "invalid_parent_examples": [],
    }

    try:
        with pikepdf.open(pdf_path) as pdf:
            struct_root = pdf.Root.get("/StructTreeRoot")
            if struct_root is None:
                return result

            def _visit(node):
                tag = str(node.get("/S", ""))
                if tag not in _HEADING_TAGS:
                    return

                result["total_headings"] += 1

                # Derive heading level
                if tag == "/H":
                    result["heading_levels"].add(1)
                elif tag == TITLE_TAG:
                    # <Title> resolves to /H1 through the RoleMap, so it both
                    # satisfies HDR-001 and counts toward HDR-002's single-H1
                    # rule.  int("itle") would raise here, so it needs its own
                    # branch rather than falling through to the parser below.
                    result["heading_levels"].add(TITLE_EQUIVALENT_LEVEL)
                    result["h1_count"] += 1
                else:
                    try:
                        lvl = int(tag[2:])   # "/H2" → 2
                        result["heading_levels"].add(lvl)
                        if lvl == 1:
                            result["h1_count"] += 1
                    except (ValueError, IndexError):
                        pass

                # Accessible text check — /ActualText or /T must be non-empty
                has_text = False
                try:
                    at = node.get("/ActualText")
                    if at is not None and str(at).strip():
                        has_text = True
                except Exception:
                    pass
                if not has_text:
                    try:
                        t = node.get("/T")
                        if t is not None and str(t).strip():
                            has_text = True
                    except Exception:
                        pass
                if not has_text:
                    result["headings_without_text"] += 1

                # Parent type validity
                try:
                    p_ref = node.get("/P")
                    if p_ref is not None:
                        p_obj = (p_ref.get_object()
                                 if hasattr(p_ref, "get_object") else p_ref)
                        if isinstance(p_obj, pikepdf.Dictionary):
                            p_type = str(p_obj.get("/S", ""))
                            if p_type and p_type not in _VALID_HEADING_PARENTS:
                                result["invalid_parent_count"] += 1
                                if len(result["invalid_parent_examples"]) < 3:
                                    result["invalid_parent_examples"].append(
                                        f"{tag} inside '{p_type}'"
                                    )
                except Exception:
                    pass

            _walk(struct_root, _visit)

    except Exception as exc:
        logger.error("_gather_heading_info: %s", exc)

    return result


# ---------------------------------------------------------------------------
# agent class
# ---------------------------------------------------------------------------

class StructureHeadingAgent(BaseAccessibilityValidatorAgent):
    """Validates PDF heading structure for PDF/UA accessibility compliance."""

    agent_code = "STRUCTURE_HEADING_AGENT"
    agent_name = "Structure Heading Agent"
    category   = "Document Structure"

    supported_checks = {"HDR-001", "HDR-002", "HDR-003", "HDR-004", "HDR-005"}

    # ── helper ──────────────────────────────────────────────────────────────

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool | None = None,
        internal_check: bool = False,
    ) -> ValidationIssue:
        return ValidationIssue(
            agent_name=StructureHeadingAgent.agent_name,
            rule_id=rule_id,
            category=StructureHeadingAgent.category,
            severity=severity.value,
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
            internal_check=internal_check,
        )

    # ── dispatch ─────────────────────────────────────────────────────────────

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        if check_code not in self.supported_checks:
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Check code {check_code!r} is not supported by StructureHeadingAgent",
                recommendation=f"Use one of: {sorted(self.supported_checks)}",
                status=ValidationStatus.FAIL,
            )

        pdf_path: str = context.get("pdf_doc_path", "")
        if not pdf_path:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message="pdf_doc_path not set in context — cannot check heading structure",
                recommendation="Ensure pdf_doc_path is passed in the agent context",
                status=ValidationStatus.FAIL,
            )

        try:
            info = _gather_heading_info(pdf_path)
        except Exception as exc:
            logger.error("StructureHeadingAgent %s: %s", check_code, exc)
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Heading structure check failed: {exc}",
                recommendation="Check PDF integrity and pikepdf installation",
                status=ValidationStatus.FAIL,
            )

        dispatch = {
            "HDR-001": self._check_hdr001,
            "HDR-002": self._check_hdr002,
            "HDR-003": self._check_hdr003,
            "HDR-004": self._check_hdr004,
            "HDR-005": self._check_hdr005,
        }
        return dispatch[check_code](check_code, info)

    # ── individual checks ────────────────────────────────────────────────────

    @staticmethod
    def _check_hdr001(rule_id: str, info: dict) -> ValidationIssue:
        """HDR-001: At least one H1 heading must be present."""
        h1 = info.get("h1_count", 0)
        ok = h1 >= 1
        return StructureHeadingAgent._issue(
            rule_id=rule_id,
            severity=Severity.CRITICAL,
            message=(
                f"Document contains {h1} H1 heading(s)"
                if ok else
                "Document does not contain any H1 heading"
            ),
            recommendation=(
                "H1 heading is present"
                if ok else
                "Add an H1 heading to identify the primary document title"
            ),
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            auto_fixable=None if ok else True,
        )

    @staticmethod
    def _check_hdr002(rule_id: str, info: dict) -> ValidationIssue:
        """HDR-002: Exactly one H1 heading should exist."""
        h1 = info.get("h1_count", 0)
        ok = h1 == 1
        return StructureHeadingAgent._issue(
            rule_id=rule_id,
            severity=Severity.MEDIUM,
            message=(
                "Document contains exactly 1 H1 heading"
                if ok else
                f"Document contains {h1} H1 headings (expected exactly 1)"
            ),
            recommendation=(
                "H1 count is correct"
                if ok else
                "Ensure only one H1 heading acts as the document's primary title"
            ),
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            # Cannot auto-fix: a human must decide which heading is the title
            auto_fixable=None,
        )

    @staticmethod
    def _check_hdr003(rule_id: str, info: dict) -> ValidationIssue:
        """HDR-003: Heading levels must be sequential (no skipping)."""
        levels = sorted(info.get("heading_levels", set()))
        skipped: list[str] = []
        for i in range(len(levels) - 1):
            gap = levels[i + 1] - levels[i]
            if gap > 1:
                for missing_lvl in range(levels[i] + 1, levels[i + 1]):
                    skipped.append(f"H{missing_lvl}")
        ok = not skipped
        return StructureHeadingAgent._issue(
            rule_id=rule_id,
            severity=Severity.HIGH,
            message=(
                "Heading levels follow proper hierarchy without skipping"
                if ok else
                f"Heading hierarchy skips levels — missing: {', '.join(skipped)}"
            ),
            recommendation=(
                "Heading hierarchy is sequential"
                if ok else
                f"Add intermediate heading levels; {', '.join(skipped)} "
                "are absent from the document"
            ),
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            auto_fixable=None,
        )

    @staticmethod
    def _check_hdr004(rule_id: str, info: dict) -> ValidationIssue:
        """HDR-004: Headings should carry accessible text metadata."""
        total   = info.get("total_headings", 0)
        no_text = info.get("headings_without_text", 0)
        ok = no_text == 0
        return StructureHeadingAgent._issue(
            rule_id=rule_id,
            severity=Severity.MEDIUM,
            message=(
                f"All {total} heading(s) have accessible text metadata"
                if ok else
                f"{no_text} of {total} headings have no accessible text metadata "
                "(ActualText / /T attribute)"
            ),
            recommendation=(
                "Heading text metadata is present"
                if ok else
                "Verify heading text appears visually in the document; "
                "consider adding /ActualText to heading structure elements"
            ),
            status=ValidationStatus.PASS if ok else ValidationStatus.WARNING,
            auto_fixable=None,
        )

    @staticmethod
    def _check_hdr005(rule_id: str, info: dict) -> ValidationIssue:
        """
        HDR-005: All heading elements must have valid parent structure element types.
        Maps to PAC Matterhorn 'Invalid use of an H1 structure element'.
        """
        bad      = info.get("invalid_parent_count", 0)
        examples = info.get("invalid_parent_examples", [])
        ok       = bad == 0
        detail   = f": {'; '.join(examples)}" if examples else ""
        return StructureHeadingAgent._issue(
            rule_id=rule_id,
            severity=Severity.HIGH,
            message=(
                "All heading elements have valid parent structure element types"
                if ok else
                f"{bad} heading element(s) placed inside an invalid parent type{detail} "
                "— PAC Matterhorn 'Invalid use of Hn structure element'"
            ),
            recommendation=(
                "Heading parent types are valid"
                if ok else
                "Re-parent heading elements so they are direct children of "
                "Document, Sect, Div, Part, Art, or BlockQuote elements"
            ),
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            auto_fixable=None if ok else True,
        )
