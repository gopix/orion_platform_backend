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

    auto_fixable: bool
    
    status: str

    internal_check: bool = False