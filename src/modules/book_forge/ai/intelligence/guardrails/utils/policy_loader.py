"""PolicyLoader — build policies from configuration instead of code.

Lets guardrail policies be defined in JSON, YAML, or a plain dict (a database row
later) rather than hardcoded, so ops can tune guardrails without a deploy::

    policies:
      - type: pii
      - type: prompt_injection
      - type: publisher
        required_phrase: "Learning Objectives"
      - type: output_length
        min_chars: 100
        max_chars: 20000

Each entry's ``type`` maps to a policy class in the registry; the remaining keys
are passed as constructor arguments. Stateless (aside from the registry).
"""
import json
from typing import Any, Dict, List, Type, Union

from src.modules.book_forge.ai.intelligence.guardrails.exceptions import (
    GuardrailException,
)
from src.modules.book_forge.ai.intelligence.guardrails.policies import (
    BasePolicy,
    OutputLengthPolicy,
    PIIPolicy,
    PromptInjectionPolicy,
    PublisherPolicy,
)


class PolicyLoader:
    """Instantiate policies from JSON/YAML/dict configuration."""

    _REGISTRY: Dict[str, Type[BasePolicy]] = {
        "pii": PIIPolicy,
        "prompt_injection": PromptInjectionPolicy,
        "publisher": PublisherPolicy,
        "output_length": OutputLengthPolicy,
    }

    def from_dict(self, config: Union[dict, list]) -> List[BasePolicy]:
        """Build policies from a dict ({"policies": [...]}) or a bare list."""
        entries = config.get("policies", []) if isinstance(config, dict) else config
        policies: List[BasePolicy] = []
        for entry in entries:
            name, params = self._parse_entry(entry)
            policies.append(self._build(name, params))
        return policies

    def from_json(self, text: str) -> List[BasePolicy]:
        return self.from_dict(json.loads(text))

    def from_yaml(self, text: str) -> List[BasePolicy]:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on env
            raise GuardrailException(
                "PyYAML is required to load policies from YAML.", cause=exc
            )
        return self.from_dict(yaml.safe_load(text))

    def load_file(self, path: str) -> List[BasePolicy]:
        """Load policies from a .json or .yaml/.yml file."""
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if path.endswith((".yaml", ".yml")):
            return self.from_yaml(text)
        return self.from_json(text)

    @classmethod
    def register(cls, name: str, policy_cls: Type[BasePolicy]) -> None:
        """Register (or override) a policy type."""
        cls._REGISTRY[name.lower()] = policy_cls

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _parse_entry(entry: Any):
        if isinstance(entry, str):
            return entry, {}
        params = dict(entry)
        name = params.pop("type", None) or params.pop("name", None)
        return name, params

    def _build(self, name: Any, params: dict) -> BasePolicy:
        policy_cls = self._REGISTRY.get(str(name).lower())
        if policy_cls is None:
            raise GuardrailException(
                f"Unknown policy type: {name}.",
                details={"available": sorted(self._REGISTRY)},
            )
        try:
            return policy_cls(**params)
        except TypeError as exc:
            raise GuardrailException(
                f"Invalid configuration for policy '{name}': {exc}",
                details={"params": params},
                cause=exc,
            )
