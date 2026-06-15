from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import (
	AccessibilityEnginePipeline,
)
from src.modules.accessibility_plus.engines.validator.accessibility_agent_framework import (
	BaseAccessibilityValidatorAgent,
)

# Backward-compatible alias for older imports.
BaseAccessibilityAgent = BaseAccessibilityValidatorAgent

__all__ = [
	"BaseAccessibilityValidatorAgent",
	"BaseAccessibilityAgent",
	"AccessibilityEnginePipeline",
]
