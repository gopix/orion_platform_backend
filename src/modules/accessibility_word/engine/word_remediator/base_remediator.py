"""Shared remediation context, result shape and per-fix error isolation."""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from docx import Document

logger = logging.getLogger(__name__)

# Called with (image_bytes, info) and returns alt text or None. Plug in an AI service here.
AltTextProvider = Callable[[bytes, dict[str, Any]], "str | None"]


@dataclass
class RemediationOptions:
    default_language: str = "en-US"
    default_author: str | None = None
    alt_text_provider: AltTextProvider | None = None
    max_caption_chars: int = 200


class FixStatus:
    APPLIED = "applied"      # the document was changed
    NO_CHANGE = "no_change"  # the fix ran and found nothing it could safely change
    SKIPPED = "skipped"      # the fix cannot run, for example no alt-text provider
    ERROR = "error"          # the fix crashed and its changes were rolled back


@dataclass
class RemediationAction:
    rule_id: str
    location: str
    action: str
    review_recommended: bool = False   # the change rests on an assumption a person should confirm
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "location": self.location,
            "action": self.action,
            "review_recommended": self.review_recommended,
            "detail": self.detail,
        }


@dataclass
class RemediatorResult:
    remediator: str
    status: str = "completed"          # completed | partial | failed
    fixes: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: list[RemediationAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "remediator": self.remediator,
            "status": self.status,
            "fixes": self.fixes,
            "actions": [a.to_dict() for a in self.actions],
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


class RemediationContext:
    """Holds the one open python-docx Document that every remediator edits in turn."""

    def __init__(self, document, file_name: str, failing_rules: set[str],
                 options: RemediationOptions):
        self.document = document
        self.file_name = file_name
        self.failing_rules = failing_rules
        self.options = options

    @property
    def body(self):
        return self.document.element.body

    def snapshot(self) -> bytes:
        buffer = io.BytesIO()
        self.document.save(buffer)
        return buffer.getvalue()

    def restore(self, data: bytes) -> None:
        self.document = Document(io.BytesIO(data))


class FixRecorder:
    def __init__(self, rule_id: str):
        self.rule_id = rule_id
        self.actions: list[RemediationAction] = []
        self.skip_reason: str | None = None

    def applied(self, location: str, action: str, *, review: bool = False,
                detail: str | None = None) -> None:
        self.actions.append(RemediationAction(self.rule_id, location, action, review, detail))

    def skip(self, reason: str) -> None:
        self.skip_reason = reason


class BaseRemediator:
    """Subclasses map rule ids to fix methods. A fix runs only when its rule failed validation,
    and a fix that crashes is rolled back without touching the other fixes."""

    name = "BaseRemediator"
    fixes: dict[str, str] = {}

    def handles(self, failing_rules: set[str]) -> bool:
        return any(rule_id in failing_rules for rule_id in self.fixes)

    def remediate(self, ctx: RemediationContext) -> RemediatorResult:
        started = time.perf_counter()
        result = RemediatorResult(remediator=self.name)

        for rule_id, method_name in self.fixes.items():
            if rule_id not in ctx.failing_rules:
                continue
            snapshot = ctx.snapshot()
            recorder = FixRecorder(rule_id)
            try:
                getattr(self, method_name)(ctx, recorder)
            except Exception as exc:
                logger.exception("%s.%s failed", self.name, method_name)
                ctx.restore(snapshot)
                result.errors.append(f"{rule_id}: {type(exc).__name__}: {exc}")
                result.fixes[rule_id] = {"status": FixStatus.ERROR, "reason": str(exc), "actions": 0}
                continue

            if recorder.actions:
                status = FixStatus.APPLIED
            elif recorder.skip_reason:
                status = FixStatus.SKIPPED
            else:
                status = FixStatus.NO_CHANGE
            result.actions.extend(recorder.actions)
            result.fixes[rule_id] = {"status": status, "reason": recorder.skip_reason,
                                     "actions": len(recorder.actions)}

        if result.errors:
            applied = any(f["status"] == FixStatus.APPLIED for f in result.fixes.values())
            result.status = "partial" if applied else "failed"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
