"""
reading_order_remediation_agent.py
==================================
ReadingOrderRemediationAgent — reorders shapes into a logical reading order
(heading -> text -> table -> image -> other), mutating context["presentation"]
in place.

Rules handled (supported_rules)
    PPT-READING-001  Object order (title-to-body sequence)
    PPT-READING-002  Screen-reader reading order
    PPT-READING-003  Decorative objects ahead of content
    PPT-READING-004  Z-order consistency

CRITICAL nuance
---------------
In PPTX the reading order a screen reader announces IS the order of shapes in the
slide's <p:spTree> — which is also the z-order (later = painted on top). So
reordering to fix reading order also changes what paints on top. To avoid silent
VISUAL regressions, this agent only reorders slides whose shapes DO NOT overlap
(there, z-order has no visible effect). Slides with overlapping shapes are left
untouched and reported for manual reordering.

Within a safe slide, shapes are ordered by category, then top-to-bottom /
left-to-right:  title(0) -> text/body(1) -> table/chart(2) -> image(3) ->
other(4) -> decorative(5, last).
"""
from __future__ import annotations

from typing import Any

from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_OVERLAP_FRAC = 0.10          # ignore <10% incidental overlaps


class ReadingOrderRemediationAgent(BasePPTRemediationAgent):
    """Reorder shapes into a logical reading order (safe slides only)."""

    agent_name = "PPT Reading Order Remediation Agent"
    supported_rules = {"PPT-READING-001", "PPT-READING-002",
                       "PPT-READING-003", "PPT-READING-004"}

    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-READING-001")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "reading_order", error=str(exc))
        try:
            return self._reorder(prs, rule_id)
        except Exception as exc:
            return self._result(rule_id, False, "reading_order", error=str(exc))

    # ------------------------------------------------------------- category
    def _category(self, shape, title_el) -> int:
        try:
            if self._is_decorative(shape):
                return 5
        except Exception:
            pass
        if title_el is not None and shape._element is title_el:
            return 0
        try:
            if shape.is_placeholder:
                from pptx.enum.shapes import PP_PLACEHOLDER
                t = shape.placeholder_format.type
                if t in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE,
                         PP_PLACEHOLDER.VERTICAL_TITLE):
                    return 0
        except Exception:
            pass
        try:
            if shape.has_table:
                return 2
            if shape.shape_type == MSO_SHAPE_TYPE.CHART:
                return 2
            if shape.shape_type in (MSO_SHAPE_TYPE.PICTURE,
                                    MSO_SHAPE_TYPE.LINKED_PICTURE):
                return 3
            if shape.has_text_frame and (shape.text_frame.text or "").strip():
                return 1
        except Exception:
            pass
        return 4

    # --------------------------------------------------------------- geometry
    @staticmethod
    def _box(shape):
        try:
            l, t, w, h = shape.left, shape.top, shape.width, shape.height
            if None in (l, t, w, h):
                return None
            return (int(l), int(t), int(w), int(h))
        except Exception:
            return None

    @staticmethod
    def _overlap(a, b) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        iy = max(0, min(ay + ah, by + bh) - max(ay, by))
        inter = ix * iy
        if inter <= 0:
            return False
        smaller = max(1, min(aw * ah, bw * bh))
        return inter / smaller > _OVERLAP_FRAC

    # --------------------------------------------------------------- reorder
    def _reorder(self, prs, rule_id) -> RemediationResult:
        changes: list[str] = []
        skipped_overlap: list[int] = []
        skipped_geom: list[int] = []

        for si, slide in enumerate(prs.slides):
            shapes = list(slide.shapes)
            if len(shapes) < 2:
                continue

            boxes = [self._box(s) for s in shapes]
            if any(b is None for b in boxes):
                skipped_geom.append(si + 1)
                continue
            # overlap guard: any real overlap -> unsafe to reorder
            overlap = any(self._overlap(boxes[i], boxes[j])
                          for i in range(len(shapes))
                          for j in range(i + 1, len(shapes)))
            if overlap:
                skipped_overlap.append(si + 1)
                continue

            title_el = None
            try:
                if slide.shapes.title is not None:
                    title_el = slide.shapes.title._element
            except Exception:
                title_el = None

            keyed = []
            for idx, (s, b) in enumerate(zip(shapes, boxes)):
                keyed.append(((self._category(s, title_el), b[1], b[0], idx), s))
            ordered = [s for _k, s in sorted(keyed, key=lambda x: x[0])]

            if [s._element for s in ordered] == [s._element for s in shapes]:
                continue                       # already in order

            self._apply_order(slide, ordered)
            changes.append(f"slide {si + 1}: reordered {len(shapes)} shapes to "
                           "heading -> text -> table -> image")

        notes = []
        if skipped_overlap:
            notes.append(f"slide(s) {', '.join(map(str, skipped_overlap))} have "
                         "overlapping shapes — left as-is to avoid visual change "
                         "(reorder manually if the reading order is wrong)")
        if skipped_geom:
            notes.append(f"slide(s) {', '.join(map(str, skipped_geom))} have shapes "
                         "without positions — skipped")
        return self._result(rule_id, True, "reorder_reading_order",
                            changes_made=changes,
                            error="; ".join(notes) if notes else None)

    @staticmethod
    def _apply_order(slide, ordered_shapes) -> None:
        """Rearrange the shape elements in <p:spTree> into ordered_shapes order,
        keeping nvGrpSpPr/grpSpPr first and any extLst last."""
        spTree = slide.shapes._spTree
        elems = [s._element for s in ordered_shapes]
        ext = spTree.find(qn("p:extLst"))
        for el in elems:
            spTree.remove(el)
        for el in elems:
            if ext is not None:
                ext.addprevious(el)
            else:
                spTree.append(el)
