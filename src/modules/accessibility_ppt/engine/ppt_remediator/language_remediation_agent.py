"""
language_remediation_agent.py
=============================
LanguageRemediationAgent — sets the presentation language so assistive tech
pronounces content correctly (WCAG 3.1.1), mutating context["presentation"] in
place.

Rules handled (supported_rules)
    PPT-META-005          No document language set
    PPT-PRESENTATION-003  Presentation language not defined

What it does
  * Sets the CORE document language (core_properties.language) — this is what
    the validator checks, and what a screen reader reads as the default.
  * Fills the run-level ``lang`` attribute on any text run that LACKS one, using
    the same default. Runs that already declare a language are left untouched, so
    intentionally tagged foreign-language passages ("mixed language") survive.

Language source (priority):
    context["language"]  ->  env ORION_PPT_DEFAULT_LANG  ->  "en-US"

It never guesses the actual language of the text (that needs language detection);
it only supplies a default where none is declared.
"""
from __future__ import annotations

import os
from typing import Any

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_DEFAULT_LANG = "en-US"


class LanguageRemediationAgent(BasePPTRemediationAgent):
    """Set the document + run-level language."""

    agent_name = "PPT Language Remediation Agent"
    supported_rules = {"PPT-META-005", "PPT-PRESENTATION-003"}

    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-META-005")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "set_language", error=str(exc))

        lang = (context.get("language")
                or os.environ.get("ORION_PPT_DEFAULT_LANG", "").strip()
                or _DEFAULT_LANG)

        changes: list[str] = []
        try:
            # 1) document-level language (what the validator checks)
            current = (prs.core_properties.language or "").strip()
            if current != lang:
                prs.core_properties.language = lang
                changes.append(f"set document language to '{lang}'"
                               + (f" (was '{current}')" if current else ""))

            # 2) fill run-level lang where missing (leave existing ones intact)
            filled = self._fill_run_languages(prs, lang)
            if filled:
                changes.append(f"set language on {filled} run(s) that lacked one")
        except Exception as exc:
            return self._result(rule_id, False, "set_language", error=str(exc))

        return self._result(rule_id, True, "set_language", changes_made=changes)

    # ------------------------------------------------------------- run langs
    def _fill_run_languages(self, prs, lang: str) -> int:
        count = 0
        for _si, shape in self._iter_shapes(prs):
            try:
                if not shape.has_text_frame:
                    continue
            except Exception:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    if not (run.text or "").strip():
                        continue
                    try:
                        rPr = run._r.get_or_add_rPr()
                        if not rPr.get("lang"):
                            rPr.set("lang", lang)
                            count += 1
                    except Exception:
                        continue
        return count
