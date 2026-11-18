from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DECIMAL,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
    func,
)

from src.core.database import Base

class WebAccessibilityScansModel(Base):
    """
    A single scan RUN against one Page (Website 1:N Page 1:N Scan - see
    web_accessibility_pages_model.py). crawl_id is set only when this scan
    was queued in bulk by scan_service.crawl_website() (POST .../scan,
    all_pages=true) - NULL for a manually-queued single-page scan. See
    web_accessibility_crawls_model.py. website_id/url stay on this table
    too - not just page_id - so existing reads (this model's own to_dict(),
    the SSRF domain-match check in scan_service.create_scan()) don't need
    a join; they're kept in sync with the page's own website_id/url at
    scan-creation time (see scan_service._get_or_create_page) and should
    always agree with page_id's target.
    """

    __tablename__ = "web_accessibility_scans"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    website_id = Column(BigInteger, ForeignKey("web_accessibility_websites.id"), nullable=False)
    page_id = Column(BigInteger, ForeignKey("web_accessibility_pages.id"), nullable=True)
    crawl_id = Column(BigInteger, ForeignKey("web_accessibility_crawls.id"), nullable=True)
    url = Column(String(2048), nullable=False)
    title = Column(String(500), nullable=True)
    status = Column(String(50), nullable=False, default="QUEUED")
    http_status = Column(Integer, nullable=True)
    started_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    total_issues = Column(Integer, nullable=False, default=0)
    accessibility_score = Column(DECIMAL(5, 2), nullable=True)
    crawl_frequency = Column(String(50), nullable=True)
    authentication_required = Column(Boolean, nullable=False, default=False)
    authentication_type = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
            onupdate=func.current_timestamp())

    def to_dict(self, include_payload: bool = False):
        data = {
            "id": self.id,
            "website_id": self.website_id,
            "page_id": self.page_id,
            "crawl_id": self.crawl_id,
            "url": self.url,
            "title": self.title,
            "status": self.status,
            "http_status": self.http_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_issues": self.total_issues,
            "accessibility_score": self.accessibility_score,
            "crawl_frequency": self.crawl_frequency,
            "authentication_required": self.authentication_required,
            "authentication_type": self.authentication_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        return data
