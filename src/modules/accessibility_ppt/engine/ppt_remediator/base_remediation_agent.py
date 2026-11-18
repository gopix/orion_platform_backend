"""
base_remediation_agent.py
=========================
Base class + result type for PPT accessibility remediator agents, plus the
python-pptx helpers every agent needs.

A remediator agent:
  * declares the validator rule_ids it can fix via ``supported_rules``
  * implements ``remediate(issue, context) -> RemediationResult``

The ``context`` mirrors the validator context but additionally carries the LIVE
python-pptx Presentation that agents mutate in place:

    context["presentation"] : pptx.Presentation  (modified in place)
    context["pptx_path"]    : source path (str, optional)
    context["_cache"]       : shared cache dict (optional)

The caller (a PPT remediation pipeline / service) is responsible for saving the
Presentation after all agents have run.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator

from pptx.enum.shapes import MSO_SHAPE_TYPE


# ---------------------------------------------------------------------------
# Result type — same shape as the PDF RemediationResult so reports are uniform.
# ---------------------------------------------------------------------------
@dataclass
class RemediationResult:
    rule_id: str
    agent_name: str
    success: bool
    action: str
    changes_made: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------
class BasePPTRemediationAgent(ABC):
    """Abstract base every PPT remediator agent subclasses."""

    agent_name: str
    supported_rules: set[str] = set()

    @abstractmethod
    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        """Apply a fix for *issue* to context['presentation'] in place."""

    # ------------------------------------------------------------- results ---
    def _result(self, rule_id: str, success: bool, action: str,
                changes_made: list[str] | None = None,
                error: str | None = None) -> RemediationResult:
        return RemediationResult(
            rule_id=rule_id, agent_name=self.agent_name, success=success,
            action=action, changes_made=changes_made or [], error=error,
        )

    # ------------------------------------------------------- pptx helpers ----
    @staticmethod
    def _presentation(context: dict[str, Any]):
        prs = context.get("presentation")
        if prs is None:
            raise ValueError("context['presentation'] (python-pptx Presentation) "
                             "is required for PPT remediation")
        return prs

    @staticmethod
    def _iter_shapes(prs) -> Iterator[tuple[int, Any]]:
        """Yield (slide_index, shape) for every shape, recursing into groups."""
        def walk(shapes, si):
            for sh in shapes:
                yield si, sh
                try:
                    if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                        yield from walk(sh.shapes, si)
                except Exception:
                    pass
        for si, slide in enumerate(prs.slides):
            yield from walk(slide.shapes, si)

    @staticmethod
    def _cnvpr(shape):
        """The <p:cNvPr> element carrying name/descr/title for this shape."""
        try:
            els = shape._element.xpath(".//p:cNvPr")
            return els[0] if els else None
        except Exception:
            return None

    @classmethod
    def _get_alt(cls, shape) -> str:
        cn = cls._cnvpr(shape)
        if cn is None:
            return ""
        return (cn.get("descr") or "").strip()

    @classmethod
    def _set_alt(cls, shape, text: str) -> bool:
        """Set the shape's alt text (cNvPr @descr). Returns True on success."""
        cn = cls._cnvpr(shape)
        if cn is None:
            return False
        try:
            cn.set("descr", text or "")
            return True
        except Exception:
            return False

    @classmethod
    def _clear_alt(cls, shape) -> bool:
        cn = cls._cnvpr(shape)
        if cn is None:
            return False
        try:
            if "descr" in cn.attrib:
                del cn.attrib["descr"]
            return True
        except Exception:
            return False

    @classmethod
    def _is_decorative(cls, shape) -> bool:
        cn = cls._cnvpr(shape)
        if cn is None:
            return False
        try:
            for el in cn.iter():
                tag = el.tag.rsplit("}", 1)[-1].lower()
                if "decorative" in tag:
                    val = el.get("val")
                    return val is None or str(val) not in ("0", "false")
        except Exception:
            pass
        return False

    @staticmethod
    def _is_picture(shape) -> bool:
        try:
            return shape.shape_type in (MSO_SHAPE_TYPE.PICTURE,
                                        MSO_SHAPE_TYPE.LINKED_PICTURE)
        except Exception:
            return False
