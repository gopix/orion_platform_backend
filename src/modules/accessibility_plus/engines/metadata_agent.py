from __future__ import annotations

import re
from typing import Any

from src.modules.accessibility_plus.engines.accessibility_agent_framework import BaseAccessibilityAgent


class MetadataAgent(BaseAccessibilityAgent):
    agent_code = "METADATA_AGENT"

    MISSING_TITLE = "MISSING_TITLE"
    MISSING_LANGUAGE = "MISSING_LANGUAGE"
    INVALID_LANGUAGE_CODE = "INVALID_LANGUAGE_CODE"
    MISSING_AUTHOR = "MISSING_AUTHOR"
    MISSING_CREATION_DATE = "MISSING_CREATION_DATE"

    _LANGUAGE_CODE_PATTERN = re.compile(
        r"^[a-z]{2,3}(?:-[A-Z]{2}|-[A-Za-z0-9]{4,8})*$"
    )

    _METADATA_KEY_ALIASES = {
        "title": ["title", "document_title", "dc:title"],
        "language": ["language", "lang", "dc:language"],
        "author": ["author", "dc:creator"],
        "subject": ["subject", "dc:subject"],
        "keywords": ["keywords"],
        "creator": ["creator"],
        "producer": ["producer"],
        "creation_date": ["creation_date", "created", "creationdate"],
        "modification_date": ["modification_date", "modified", "moddate"],
    }

    supported_checks = {
        MISSING_TITLE,
        MISSING_LANGUAGE,
        INVALID_LANGUAGE_CODE,
        MISSING_AUTHOR,
        MISSING_CREATION_DATE,
    }

    def run_check(self, check_code: str, context: dict[str, Any]) -> dict[str, Any]:
        normalized_metadata = self._normalize_metadata(self._extract_metadata(context))

        if check_code == self.MISSING_TITLE:
            findings = self._check_missing_title(normalized_metadata)
        elif check_code == self.MISSING_LANGUAGE:
            findings = self._check_missing_language(normalized_metadata)
        elif check_code == self.INVALID_LANGUAGE_CODE:
            findings = self._check_invalid_language_code(normalized_metadata)
        elif check_code == self.MISSING_AUTHOR:
            findings = self._check_missing_author(normalized_metadata)
        elif check_code == self.MISSING_CREATION_DATE:
            findings = self._check_missing_creation_date(normalized_metadata)
        else:
            return {
                "check_code": check_code,
                "passed": False,
                "message": f"{check_code} is not implemented for {self.agent_code}",
                "value": [],
            }

        passed = len(findings) == 0
        return {
            "check_code": check_code,
            "passed": passed,
            "message": "No issues found" if passed else f"{len(findings)} issue(s) found",
            "value": findings,
        }

    def _check_missing_title(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        title = metadata.get("title")
        if title:
            return []

        return [
            self._build_finding(
                check_code=self.MISSING_TITLE,
                severity="HIGH",
                description="Document title metadata is missing",
                recommendation="Set PDF title metadata",
            )
        ]

    def _check_missing_language(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        language = metadata.get("language")
        if language:
            return []

        return [
            self._build_finding(
                check_code=self.MISSING_LANGUAGE,
                severity="HIGH",
                description="Primary document language missing",
                recommendation="Set document language metadata",
            )
        ]

    def _check_invalid_language_code(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        language = metadata.get("language")
        if not language:
            return []

        if self._LANGUAGE_CODE_PATTERN.match(language):
            return []

        return [
            self._build_finding(
                check_code=self.INVALID_LANGUAGE_CODE,
                severity="MEDIUM",
                description=f'Invalid document language code: "{language}"',
                recommendation="Use a valid BCP-47 style language code (e.g., en-US)",
            )
        ]

    def _check_missing_author(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        author = metadata.get("author")
        if author:
            return []

        return [
            self._build_finding(
                check_code=self.MISSING_AUTHOR,
                severity="LOW",
                description="Document author metadata is missing",
                recommendation="Set document author metadata",
            )
        ]

    def _check_missing_creation_date(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        creation_date = metadata.get("creation_date")
        if creation_date:
            return []

        return [
            self._build_finding(
                check_code=self.MISSING_CREATION_DATE,
                severity="LOW",
                description="Document creation date metadata is missing",
                recommendation="Set document creation date metadata",
            )
        ]

    def _extract_metadata(self, context: dict[str, Any]) -> dict[str, Any]:
        metadata = context.get("metadata")
        if isinstance(metadata, dict):
            return metadata

        # Fallback: some callers pass metadata fields directly in context.
        return context

    def _normalize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for target_key, aliases in self._METADATA_KEY_ALIASES.items():
            value = self._first_non_empty(metadata, aliases)
            normalized[target_key] = value
        return normalized

    def _build_finding(
        self,
        check_code: str,
        severity: str,
        description: str,
        recommendation: str,
    ) -> dict[str, Any]:
        return {
            "agent_code": self.agent_code,
            "check_code": check_code,
            "page": None,
            "severity": severity,
            "status": "FAILED",
            "description": description,
            "recommendation": recommendation,
        }

    @staticmethod
    def _first_non_empty(context: dict[str, Any], keys: list[str]) -> str | None:
        for key in keys:
            value = context.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None
