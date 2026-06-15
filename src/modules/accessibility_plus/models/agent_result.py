
from dataclasses import dataclass

from src.modules.accessibility_plus.models.validation_issue import ValidationIssue


@dataclass
class AgentResult:

    agent_name: str

    success: bool

    issue_count: int

    issues: list[ValidationIssue]