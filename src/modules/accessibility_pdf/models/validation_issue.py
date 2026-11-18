from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ValidationStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    INFO = "INFO"

@dataclass
class ValidationIssue:
    agent_name: str

    rule_id: str

    category: str

    severity: str

    page_no: int | None

    message: str

    recommendation: str

    # None  = not applicable (check passed because element doesn't exist or N/A)
    # True  = issue exists and can be auto-fixed
    # False = issue exists but requires manual action
    auto_fixable: bool | None

    status: str

    # True  = informational / data-collection check (e.g., TREE-*, structure stats)
    # False = real accessibility compliance check
    internal_check: bool = False