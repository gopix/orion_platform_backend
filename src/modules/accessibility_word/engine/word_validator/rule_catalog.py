"""Loads config/accessibility_rules.json, the single source of rule definitions."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "accessibility_rules.json"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    analyzer: str
    category: str
    severity: str
    title: str
    recommendation: str
    wcag: tuple[str, ...] = ()
    enabled: bool = True


class RuleCatalog:
    def __init__(self, raw: dict[str, Any]):
        self.version: str = raw.get("version", "unknown")
        self.severity_weights: dict[str, float] = raw["scoring"]["severity_weights"]
        self.thresholds: dict[str, float] = raw["thresholds"]
        self._rules: dict[str, Rule] = {}
        for item in raw["rules"]:
            rule = Rule(
                rule_id=item["rule_id"],
                analyzer=item["analyzer"],
                category=item["category"],
                severity=item["severity"],
                title=item["title"],
                recommendation=item["recommendation"],
                wcag=tuple(item.get("wcag", ())),
                enabled=item.get("enabled", True),
            )
            if rule.severity not in self.severity_weights:
                raise ValueError(f"{rule.rule_id}: unknown severity {rule.severity}")
            self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> Rule:
        return self._rules[rule_id]

    def for_analyzer(self, analyzer: str) -> list[Rule]:
        return [rule for rule in self._rules.values() if rule.analyzer == analyzer]

    def threshold(self, name: str) -> float:
        return self.thresholds[name]


@lru_cache(maxsize=1)
def load_catalog() -> RuleCatalog:
    with _DEFAULT_PATH.open(encoding="utf-8") as fh:
        return RuleCatalog(json.load(fh))
