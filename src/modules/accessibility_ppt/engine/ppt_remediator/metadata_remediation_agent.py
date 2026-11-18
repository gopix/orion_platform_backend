"""
metadata_remediation_agent.py
=============================
MetadataRemediationAgent — fills missing document properties, mutating
context["presentation"].core_properties in place.

Rules handled (supported_rules)
    PPT-META-001  Missing / default title -> derive a real title
    PPT-META-002  Missing subject         -> set subject
    PPT-META-003  Missing author          -> set author (only from a real source)
    PPT-META-004  Missing keywords        -> set keywords (derived from titles)

Language (PPT-META-005) is intentionally NOT handled here: the dedicated
LanguageRemediationAgent owns it, since it also sets per-run language and
preserves intentionally mixed-language runs.

Value sources (priority), per property:
    context[<prop>]  ->  env ORION_PPT_DEFAULT_<PROP>  ->  a derived value
Derivations (deterministic, no model/network):
    title    : first non-empty slide title -> document file stem -> "Untitled Presentation"
    subject  : the derived title (the deck's topic)
    keywords : significant words gathered from the slide titles
    author   : NOT derived — set only from context/env/last_modified_by, else
               left blank and reported (fabricating a name would be misleading).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_DEFAULT_TITLES = {
    "powerpoint presentation", "presentation", "untitled",
    "untitled presentation", "slide 1", "deck",
}
_STOP = {
    "the", "and", "for", "with", "your", "our", "are", "this", "that", "from",
    "into", "about", "using", "how", "what", "why", "when", "who", "a", "an",
    "of", "to", "in", "on", "is", "it", "as", "by", "or", "be",
}


class MetadataRemediationAgent(BasePPTRemediationAgent):
    """Fill missing title / subject / author / keywords."""

    agent_name = "PPT Metadata Remediation Agent"
    supported_rules = {"PPT-META-001", "PPT-META-002", "PPT-META-003", "PPT-META-004"}

    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-META-001")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "metadata", error=str(exc))
        try:
            handler = {
                "PPT-META-001": self._fix_title,
                "PPT-META-002": self._fix_subject,
                "PPT-META-003": self._fix_author,
                "PPT-META-004": self._fix_keywords,
            }.get(rule_id, self._fix_title)
            return handler(prs, context, rule_id)
        except Exception as exc:
            return self._result(rule_id, False, "metadata", error=str(exc))

    # ---------------------------------------------------------------- sources
    @staticmethod
    def _override(context, prop) -> str:
        v = context.get(prop)
        if isinstance(v, str) and v.strip():
            return v.strip()
        env = os.environ.get(f"ORION_PPT_DEFAULT_{prop.upper()}", "")
        return env.strip()

    def _derive_title(self, prs, context) -> str:
        for slide in prs.slides:
            try:
                t = slide.shapes.title
                if t is not None and (t.text or "").strip():
                    return t.text.strip()
            except Exception:
                continue
        name = context.get("document_name") or context.get("pptx_path")
        if isinstance(name, str) and name.strip():
            stem = Path(name).stem.replace("_", " ").replace("-", " ").strip()
            if stem:
                return stem[:1].upper() + stem[1:]
        return "Untitled Presentation"

    def _derive_keywords(self, prs) -> str:
        words: list[str] = []
        seen = set()
        for slide in prs.slides:
            try:
                t = slide.shapes.title
                text = (t.text if t is not None else "") or ""
            except Exception:
                text = ""
            for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text):
                lw = w.lower()
                if lw in _STOP or lw in seen:
                    continue
                seen.add(lw)
                words.append(lw)
        return ", ".join(words[:8])

    # ---------------------------------------------------------------- 001 title
    def _fix_title(self, prs, context, rule_id) -> RemediationResult:
        cp = prs.core_properties
        cur = (cp.title or "").strip()
        if cur and cur.casefold() not in _DEFAULT_TITLES:
            return self._result(rule_id, True, "set_title", changes_made=[])
        title = self._override(context, "title") or self._derive_title(prs, context)
        cp.title = title
        return self._result(rule_id, True, "set_title",
                            changes_made=[f"set title to '{title}'"
                                          + (f" (was '{cur}')" if cur else "")])

    # ---------------------------------------------------------------- 002 subj
    def _fix_subject(self, prs, context, rule_id) -> RemediationResult:
        cp = prs.core_properties
        if (cp.subject or "").strip():
            return self._result(rule_id, True, "set_subject", changes_made=[])
        subject = self._override(context, "subject") or self._derive_title(prs, context)
        cp.subject = subject
        return self._result(rule_id, True, "set_subject",
                            changes_made=[f"set subject to '{subject}'"])

    # ---------------------------------------------------------------- 003 auth
    def _fix_author(self, prs, context, rule_id) -> RemediationResult:
        cp = prs.core_properties
        if (cp.author or "").strip():
            return self._result(rule_id, True, "set_author", changes_made=[])
        author = (self._override(context, "author")
                  or (cp.last_modified_by or "").strip())
        if not author:
            return self._result(rule_id, True, "set_author", changes_made=[],
                                error="no author source (context/env/last_modified_by "
                                      "all empty) — set author manually")
        cp.author = author
        return self._result(rule_id, True, "set_author",
                            changes_made=[f"set author to '{author}'"])

    # ---------------------------------------------------------------- 004 kw
    def _fix_keywords(self, prs, context, rule_id) -> RemediationResult:
        cp = prs.core_properties
        if (cp.keywords or "").strip():
            return self._result(rule_id, True, "set_keywords", changes_made=[])
        keywords = self._override(context, "keywords") or self._derive_keywords(prs)
        if not keywords:
            return self._result(rule_id, True, "set_keywords", changes_made=[],
                                error="no keywords source and no slide titles to "
                                      "derive from — set keywords manually")
        cp.keywords = keywords
        return self._result(rule_id, True, "set_keywords",
                            changes_made=[f"set keywords to '{keywords}'"])
