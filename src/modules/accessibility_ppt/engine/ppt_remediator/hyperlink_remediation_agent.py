"""
hyperlink_remediation_agent.py
==============================
HyperlinkRemediationAgent — fixes hyperlink accessibility issues found by the PPT
HyperlinkAgent, mutating context["presentation"] in place.

Rules handled (supported_rules)
    PPT-LINK-002  Raw URL as link text  -> replace with a readable label from URL
    PPT-LINK-003  "Click here"/empty    -> replace with a readable label from URL
    PPT-LINK-004  Missing ScreenTip     -> add a tooltip describing the destination

NOT handled (reported, not auto-fixable):
    PPT-LINK-001  Broken/malformed URL — the correct destination is unknown, so
                  this is left for manual correction (never silently removed).

Labels are derived deterministically from the URL (last meaningful path segment,
else host), so no network or model call is needed. The hyperlink address itself
is never changed — only the visible text and the ScreenTip.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, unquote

from pptx.oxml.ns import qn

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_GENERIC = {
    "click here", "click", "here", "link", "this link", "this", "read more",
    "more", "learn more", "see more", "go", "go here", "download", "click this",
    "click to read", "read", "info", "details", "this page", "website", "url",
}
_URL_LIKE = re.compile(r"^\s*(https?://|www\.|ftp://)", re.I)


def _label_from_url(url: str) -> str:
    """A short, human-readable label derived from a URL (no network)."""
    u = (url or "").strip()
    if not u:
        return "link"
    p = urlparse(u)
    if p.scheme.lower() == "mailto":
        return f"Email {p.path}" if p.path else "Email link"
    host = re.sub(r"^www\.", "", (p.netloc or ""), flags=re.I)
    segs = [s for s in (p.path or "").split("/") if s]
    if segs:
        last = unquote(segs[-1])
        last = re.sub(r"\.[a-z0-9]{1,5}$", "", last, flags=re.I)   # drop extension
        last = re.sub(r"[-_]+", " ", last).strip()
        if last:
            label = last.title()
            return f"{label} ({host})" if host else label
    return host or u


def _tooltip_from_url(url: str) -> str:
    p = urlparse((url or "").strip())
    if p.scheme.lower() == "mailto":
        return f"Email {p.path}" if p.path else "Email link"
    host = re.sub(r"^www\.", "", (p.netloc or ""), flags=re.I)
    return f"Opens {host}" if host else "Opens link"


class HyperlinkRemediationAgent(BasePPTRemediationAgent):
    """Give hyperlinks descriptive text and ScreenTips."""

    agent_name = "PPT Hyperlink Remediation Agent"
    supported_rules = {"PPT-LINK-002", "PPT-LINK-003", "PPT-LINK-004"}

    # ---------------------------------------------------------------- dispatch
    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-LINK-003")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "hyperlink", error=str(exc))
        try:
            if rule_id == "PPT-LINK-004":
                return self._fix_tooltips(prs, rule_id)
            return self._fix_link_text(prs, rule_id)   # 002 & 003
        except Exception as exc:
            return self._result(rule_id, False, "hyperlink", error=str(exc))

    # ------------------------------------------------------------- iteration
    def _iter_link_runs(self, prs):
        """Yield (slide_index, run) for every run carrying a hyperlink address."""
        for si, shape in self._iter_shapes(prs):
            try:
                if not shape.has_text_frame:
                    continue
            except Exception:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    try:
                        if run.hyperlink and run.hyperlink.address:
                            yield si, run
                    except Exception:
                        continue

    @staticmethod
    def _hlink_click(run):
        rPr = run._r.find(qn("a:rPr"))
        if rPr is None:
            return None
        return rPr.find(qn("a:hlinkClick"))

    @classmethod
    def _get_tooltip(cls, run) -> str:
        hl = cls._hlink_click(run)
        return (hl.get("tooltip") or "").strip() if hl is not None else ""

    @classmethod
    def _set_tooltip(cls, run, text: str) -> bool:
        hl = cls._hlink_click(run)
        if hl is None:
            return False
        hl.set("tooltip", text)
        return True

    # --------------------------------------------------------- 002/003 text
    def _fix_link_text(self, prs, rule_id) -> RemediationResult:
        changes = []
        for si, run in self._iter_link_runs(prs):
            text = (run.text or "").strip()
            url = run.hyperlink.address or ""
            is_raw = bool(_URL_LIKE.match(text)) or (text and text == url.strip())
            is_generic = (not text) or (text.casefold() in _GENERIC)
            if not (is_raw or is_generic):
                continue
            label = _label_from_url(url)
            if label and label != text:
                old = text or "(empty)"
                run.text = label
                changes.append(f"slide {si + 1}: link text '{old[:30]}' -> '{label[:40]}'")
        return self._result(rule_id, True, "descriptive_link_text",
                            changes_made=changes)

    # ------------------------------------------------------------- 004 tips
    def _fix_tooltips(self, prs, rule_id) -> RemediationResult:
        changes = []
        skipped = 0
        for si, run in self._iter_link_runs(prs):
            if self._get_tooltip(run):
                continue
            tip = _tooltip_from_url(run.hyperlink.address or "")
            if self._set_tooltip(run, tip):
                changes.append(f"slide {si + 1}: added ScreenTip '{tip}'")
            else:
                skipped += 1
        err = (f"{skipped} link(s) had no hlinkClick element to tag"
               if skipped else None)
        return self._result(rule_id, True, "add_link_tooltip",
                            changes_made=changes, error=err)
