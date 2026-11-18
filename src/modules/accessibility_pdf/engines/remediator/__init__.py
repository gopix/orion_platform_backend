"""
Accessibility Remediator package.

Public surface:
    BaseRemediatorAgent   – abstract base class for all remediator agents
    RemediationResult     – dataclass returned by every remediate() call
    RemediatorService     – central routing service
    remediation_service   – module-level singleton

Concrete agents are imported lazily by RemediatorService and are not
re-exported here to avoid heavy import chains at startup.
"""

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult
from .remediator_service import RemediatorService, remediation_service

__all__ = [
    "BaseRemediatorAgent",
    "RemediationResult",
    "RemediatorService",
    "remediation_service",
]
