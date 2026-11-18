from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
    func,
)

from src.core.database import Base

class WebAccessibilityIssuesModel(Base):
    """
    A persistent accessibility DEFECT, not a per-scan finding. Re-running a
    scan against a page that still has the same problem does NOT create a
    new row here - scan_service.run_scan()'s dedup upsert matches on
    (page_id, rule_id, element_selector) and bumps times_seen/
    last_seen_scan_id on the existing row instead. A row only gets created
    the first time a given defect is seen, and only gets marked RESOLVED
    once a later scan of the same page no longer finds it (see
    scan_service._resolve_stale_issues). A RESOLVED issue found again later
    becomes REOPENED, not a fresh OPEN row - see scan_service.py's module
    docstring for the full rationale and status transitions.

    page_id is a real FK to web_accessibility_pages as of the Page model
    (Website 1:N Page 1:N Scan 1:N Issue - see
    web_accessibility_pages_model.py). It previously held scan_id as a
    placeholder, back when no pages table existed; existing rows created
    before that migration need scripts/migrate_web_accessibility_pages.py
    to repoint them at a real page before this FK can be enforced.
    """

    __tablename__ = "web_accessibility_issues"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    # The scan that FIRST detected this defect - immutable after creation.
    # (Not necessarily the most recent scan to confirm it - see last_seen_scan_id.)
    scan_id = Column(BigInteger, ForeignKey("web_accessibility_scans.id"), nullable=False)
    page_id = Column(BigInteger, ForeignKey("web_accessibility_pages.id"), nullable=False)
    rule_id = Column(BigInteger, ForeignKey("web_accessibility_rules.id"), nullable=False)
    severity = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="OPEN")  # OPEN | RESOLVED
    element_selector = Column(String(2000), nullable=True)
    html_snippet = Column(Text, nullable=True)
    message = Column(String(2000), nullable=True)
    # Dedup/lifecycle tracking (see class docstring). Nullable so existing
    # rows from before this column existed don't need a backfill.
    times_seen = Column(Integer, nullable=False, default=1)
    last_seen_scan_id = Column(BigInteger, ForeignKey("web_accessibility_scans.id"), nullable=True)
    resolved_at = Column(TIMESTAMP, nullable=True)
    resolved_in_scan_id = Column(BigInteger, ForeignKey("web_accessibility_scans.id"), nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
            onupdate=func.current_timestamp())

    def to_dict(self, include_payload: bool = False):
        data = {
            "id": self.id,
            "scan_id": self.scan_id,
            "page_id": self.page_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "status": self.status,
            "element_selector": self.element_selector,
            "html_snippet": self.html_snippet,
            "message": self.message,
            "times_seen": self.times_seen,
            "last_seen_scan_id": self.last_seen_scan_id,
            "resolved_at": self.resolved_at,
            "resolved_in_scan_id": self.resolved_in_scan_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        return data
