"""Step 8: manage screen-reader evidence.

Static DOCX analysis cannot establish screen-reader compatibility, so a rule stays
NOT_TESTED until a complete record of real testing exists for this exact file.

Evidence record:
    {"tool": "NVDA", "tool_version": "2026.1", "tester": "A. Tester",
     "tested_at": "2026-11-03", "result": "PASS" | "FAIL",
     "document_sha256": "<sha256 of the tested file>", "notes": "optional"}
"""
from __future__ import annotations

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer, Item
from src.modules.accessibility_word.models.finding_models import CheckStatus


_REQUIRED_FIELDS = ("tool", "tool_version", "tester", "tested_at", "result", "document_sha256")
_RULES = {"NVDA": "SRV-001", "JAWS": "SRV-002"}


class ScreenReaderValidator(BaseAnalyzer):
    name = "ScreenReaderValidator"
    category = "SCREEN_READER_COMPATIBILITY"

    def check_srv_screen_readers(self, ctx, rec):
        for tool, rule_id in _RULES.items():
            self._evaluate_tool(ctx, rec, tool, rule_id)

    @staticmethod
    def _rejection(record, ctx) -> str | None:
        missing = [name for name in _REQUIRED_FIELDS if not record.get(name)]
        if missing:
            return f"missing {', '.join(missing)}"
        if str(record["result"]).upper() not in (CheckStatus.PASS, CheckStatus.FAIL):
            return f"unknown result {record['result']}"
        if record["document_sha256"].lower() != ctx.sha256:
            return "it was recorded for a different version of the file"
        return None

    def _evaluate_tool(self, ctx, rec, tool, rule_id):
        records = [r for r in ctx.screen_reader_evidence
                   if str(r.get("tool", "")).strip().upper() == tool]
        accepted, rejected = [], []
        for record in records:
            reason = self._rejection(record, ctx)
            if reason:
                rejected.append(reason)
            else:
                accepted.append(record)

        if not accepted:
            detail = f"No {tool} testing evidence is available."
            if rejected:
                detail = f"{tool} evidence was rejected: {'; '.join(rejected)}."
            rec.record(rule_id, CheckStatus.NOT_TESTED,
                       [Item(f"Not tested with {tool}", "Whole document")], detail)
            return

        latest = max(accepted, key=lambda r: str(r["tested_at"]))
        detail = (f"{tool} {latest['tool_version']} tested by {latest['tester']} "
                  f"on {latest['tested_at']}.")
        if str(latest["result"]).upper() == CheckStatus.PASS:
            rec.record(rule_id, CheckStatus.PASS, detail=detail)
        else:
            issue = latest.get("notes") or f"{tool} testing reported problems"
            rec.record(rule_id, CheckStatus.FAIL, [Item(issue, "Whole document")], detail)
